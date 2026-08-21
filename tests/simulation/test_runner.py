from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from controlel.application.runtime.control_runtime_assembly import ControlRuntimeAssembly
from controlel.application.runtime.control_runtime_startup import ControlRuntimeStartup
from controlel.application.services.operational_event_recorder import OperationalEventRecorder
from controlel.application.services.operational_event_stream import OperationalEventStream
from controlel.domain.capabilities.temperature_capability import TemperatureCapability
from controlel.domain.entities.zone import Zone
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.source_control import ReportedSourceEvidence, SourceCapabilities, SourceOwnership
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId
from controlel.simulation import (
    DeterministicScheduler,
    HeatingSimulationAdapter,
    ProvenanceEnvelope,
    ReplayArtifact,
    RuntimeOrigin,
    Scenario,
    ScenarioRunner,
    SimulationMode,
    SimulationOutcome,
    SimulationRecorder,
    SimulationRun,
    VirtualClock,
)
from controlel.simulation.adapters.heating import HeatingInitialState, HeatingScenarioConfiguration
from controlel.simulation.scenario import normalize_json

ROOT = Path(__file__).parents[2]
EXAMPLE = ROOT / "docs" / "examples" / "shadow" / "room_temperature_sensor_failure.yaml"


def _scenario() -> Scenario:
    return Scenario.from_yaml(EXAMPLE.read_text(encoding="utf-8"))


def test_same_scenario_produces_the_same_semantic_fingerprint() -> None:
    runner = ScenarioRunner(HeatingSimulationAdapter)

    first = runner.run(_scenario(), run_id="first-run")
    second = runner.run(_scenario(), run_id="second-run")

    assert first.semantic_fingerprint == second.semantic_fingerprint
    assert [record.semantic_data() for record in first.records] == [record.semantic_data() for record in second.records]
    assert first.run.run_id != second.run.run_id


def test_shadow_startup_matches_real_production_neutral_recovery_lifecycle() -> None:
    scenario_data = normalize_json(_scenario().canonical_data())
    assert isinstance(scenario_data, dict)
    initial_data = scenario_data["initial_state"]
    assert isinstance(initial_data, dict)
    initial_data.update(
        {
            "source_reported_state": "disabled",
            "source_reported_observed_at": "2026-01-15T08:00:00Z",
            "source_transition_at": "2026-01-15T07:45:00Z",
        }
    )
    scenario = Scenario.from_mapping(scenario_data)
    configuration = HeatingScenarioConfiguration.model_validate(scenario.configuration)
    initial = HeatingInitialState.model_validate(scenario.initial_state)

    class RecordingSourcePort:
        def __init__(self) -> None:
            self.commands = []

        def execute(self, command) -> None:
            self.commands.append(command)

    class NoOpFailureSink:
        def report(self, failure) -> None:
            pass

    zone_id = ZoneId(configuration.zone_id)
    sensor_id = SensorId(configuration.sensor_id)
    sensors = SensorRepository()
    zones = ZoneRepository()
    sensors.add(
        Sensor(
            id=uuid5(NAMESPACE_URL, f"controlel-startup-test:sensor:{sensor_id.value}"),
            sensor_id=sensor_id,
            zone_id=zone_id,
            name=configuration.sensor_name,
            capabilities=[TemperatureCapability()],
            created_at=scenario.start_at,
            updated_at=scenario.start_at,
        )
    )
    zones.add(
        Zone(
            id=uuid5(NAMESPACE_URL, f"controlel-startup-test:zone:{zone_id.value}"),
            zone_id=zone_id,
            primary_sensor_id=sensor_id,
            primary_measurement_max_age=configuration.primary_measurement_max_age,
            name=configuration.zone_name,
            target_temperature=Temperature(configuration.target_temperature),
            created_at=scenario.start_at,
            updated_at=scenario.start_at,
        )
    )
    real_clock = VirtualClock(scenario.start_at)
    real_events = OperationalEventRecorder(OperationalEventStream(capacity=1000))
    real_source = RecordingSourcePort()
    real_runtime = ControlRuntimeAssembly(
        sensor_repository=sensors,
        zone_repository=zones,
        heat_delivery_controller=None,
        clock=real_clock,
        scheduler=DeterministicScheduler(real_clock),
        scheduled_failure_sink=NoOpFailureSink(),
        max_future_skew=configuration.max_future_skew,
        indeterminate_grace_period=configuration.indeterminate_grace_period,
        indeterminate_timeout_action=configuration.indeterminate_timeout_action,
        heating_turn_on_differential=configuration.heating_turn_on_differential,
        heating_turn_off_differential=configuration.heating_turn_off_differential,
        heat_demand_confirmation_duration=configuration.heat_demand_confirmation_duration,
        minimum_heating_on_time=configuration.minimum_heating_on_time,
        minimum_heating_off_time=configuration.minimum_heating_off_time,
        source_ownership=SourceOwnership.CONTROLEL_OWNED,
        source_capabilities=SourceCapabilities(),
        operational_event_recorder=real_events,
    ).build(real_source)
    real_startup = ControlRuntimeStartup(real_runtime)
    real_startup.begin()
    assert initial.source_reported_state is not None
    assert initial.source_reported_observed_at is not None
    real_source_result = real_startup.ingest_reported_source(
        ReportedSourceEvidence(
            state=initial.source_reported_state,
            observed_at=initial.source_reported_observed_at,
            transition_at=initial.source_transition_at,
        )
    )
    assert initial.zone_temperature is not None
    assert initial.zone_temperature_observed_at is not None
    real_temperature_result = real_startup.ingest_temperature(
        Measurement(
            sensor_id=sensor_id,
            value=Temperature(initial.zone_temperature),
            timestamp=initial.zone_temperature_observed_at,
        )
    )

    shadow_clock = VirtualClock(scenario.start_at)
    shadow_recorder = SimulationRecorder(
        SimulationRun(
            run_id="shadow-startup",
            environment_id="shadow",
            scenario_id=scenario.scenario_id,
            started_at=scenario.start_at,
        )
    )
    shadow = HeatingSimulationAdapter(
        scenario,
        shadow_clock,
        DeterministicScheduler(shadow_clock, shadow_recorder),
        shadow_recorder,
    )
    shadow.dispatch(scenario.timeline[0])

    shadow_results = {
        record.payload["operation"]: record.payload["status"]
        for record in shadow.recorder.records
        if record.kind == "runtime.result"
    }
    real_event_codes = [event.event_code.value for event in real_events.stream.snapshot().events]
    shadow_event_codes = [
        event.event_code.value for event in shadow._operational_event_recorder.stream.snapshot().events
    ]
    shadow_commands = [record.payload for record in shadow.recorder.records if record.kind == "command.source"]

    assert shadow.runtime.source_recovery_state == real_runtime.source_recovery_state
    assert shadow_results["initial.source_reported_state"] == real_source_result.status.value
    assert shadow_results["initial.temperature"] == real_temperature_result.status.value
    assert real_source_result.status.value == "resilience_command_held"
    assert [command.action.value for command in real_source.commands] == ["enable_heating"]
    assert [command["action"] for command in shadow_commands] == ["enable_heating"]
    assert shadow_event_codes == real_event_codes
    assert shadow_event_codes.index("runtime_started") < shadow_event_codes.index("corrective_action_held")
    assert shadow_event_codes.index("corrective_action_held") < shadow_event_codes.index("source_enable_requested")


def test_simulation_records_are_isolated_shadow_provenance() -> None:
    report = ScenarioRunner(HeatingSimulationAdapter).run(_scenario())

    assert report.records
    assert {record.origin for record in report.records} == {RuntimeOrigin.SHADOW_SIMULATION}
    assert {record.environment_id for record in report.records} == {"shadow-local"}
    real = ProvenanceEnvelope(
        record_id="real-record:00000001",
        origin=RuntimeOrigin.REAL,
        environment_id="real-home",
        run_id="real-runtime-generation:1",
        mode=SimulationMode.REAL,
        scenario_id=None,
        kind="operational_event",
        recorded_at=report.run.started_at,
    )
    assert real.origin is RuntimeOrigin.REAL
    assert real.environment_id != report.records[0].environment_id
    with pytest.raises(ValidationError):
        SimulationRun(
            run_id="invalid-real-run",
            environment_id="real",
            scenario_id="scenario",
            started_at=report.run.started_at,
            origin=RuntimeOrigin.REAL,
        )


def test_runner_rejects_structural_but_untrusted_adapter() -> None:
    class UntrustedAdapter:
        adapter_version = "0.1"

    with pytest.raises(TypeError, match="trusted simulation adapter"):
        ScenarioRunner(UntrustedAdapter)  # type: ignore[arg-type]


def test_replay_artifact_is_self_contained_and_reproduces_the_fingerprint() -> None:
    scenario = _scenario()
    runner = ScenarioRunner(HeatingSimulationAdapter)
    report = runner.run(scenario, run_id="original")

    artifact = ReplayArtifact.from_execution(scenario, report)
    replayed = runner.replay(artifact, run_id="replayed")

    assert artifact.scenario_hash == scenario.content_hash
    assert artifact.canonical_scenario == scenario.canonical_data()
    assert artifact.source_core_version == report.core_version
    assert artifact.module_adapter_version == HeatingSimulationAdapter.adapter_version
    assert replayed.semantic_fingerprint == artifact.expected_semantic_fingerprint
    assert replayed.outcome is SimulationOutcome.PASSED


def test_replay_rejects_tampered_expected_fingerprint() -> None:
    scenario = _scenario()
    runner = ScenarioRunner(HeatingSimulationAdapter)
    artifact = ReplayArtifact.from_execution(scenario, runner.run(scenario))
    tampered = artifact.model_copy(update={"expected_semantic_fingerprint": "0" * 64})

    with pytest.raises(ValueError, match="semantic fingerprint does not match"):
        runner.replay(tampered)


def test_replay_rejects_metadata_that_disagrees_with_embedded_scenario() -> None:
    scenario = _scenario()
    runner = ScenarioRunner(HeatingSimulationAdapter)
    artifact = ReplayArtifact.from_execution(scenario, runner.run(scenario))
    tampered = artifact.model_copy(update={"module": "lighting"})

    with pytest.raises(ValueError, match="module does not match canonical scenario"):
        runner.replay(tampered)


def test_room_temperature_sensor_failure_uses_existing_runtime_diagnostics() -> None:
    report = ScenarioRunner(HeatingSimulationAdapter).run(_scenario())
    event_codes = {record.payload["event_code"] for record in report.records if record.kind == "operational_event"}

    assert report.outcome is SimulationOutcome.PASSED
    assert not report.errors
    assert "measurement_became_valid" in event_codes
    assert "measurement_became_unavailable" in event_codes
    assert any(record.kind == "diagnostics.heating" for record in report.records)
    unavailable = next(
        record
        for record in report.records
        if record.kind == "timeline.event" and record.payload["event_type"] == "sensor.availability_changed"
    )
    assert unavailable.scheduled_for == unavailable.delivered_at
    assert unavailable.evidence_at == unavailable.delivered_at


def test_delayed_evidence_retains_observation_and_delivery_timestamps() -> None:
    scenario_data = normalize_json(_scenario().canonical_data())
    assert isinstance(scenario_data, dict)
    timeline = scenario_data["timeline"]
    assert isinstance(timeline, list)
    unavailable = timeline[1]
    assert isinstance(unavailable, dict)
    event = unavailable["event"]
    assert isinstance(event, dict)
    payload = event["payload"]
    assert isinstance(payload, dict)
    payload["observed_at"] = "2026-01-15T08:07:00Z"
    scenario = Scenario.from_mapping(scenario_data)

    report = ScenarioRunner(HeatingSimulationAdapter).run(scenario)
    delivered = next(
        record
        for record in report.records
        if record.kind == "timeline.event" and record.payload["event_type"] == "sensor.availability_changed"
    )

    assert delivered.evidence_at is not None
    assert delivered.delivered_at is not None
    assert delivered.evidence_at < delivered.delivered_at


def test_unsatisfied_expectation_produces_a_fail_report() -> None:
    scenario_data = normalize_json(_scenario().canonical_data())
    assert isinstance(scenario_data, dict)
    scenario_data["expectations"] = [
        {"type": "operational_event.exists", "event_code": "runtime_fatal"},
    ]
    scenario = Scenario.from_mapping(scenario_data)

    report = ScenarioRunner(HeatingSimulationAdapter).run(scenario)

    assert report.outcome is SimulationOutcome.FAILED
