import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import Event, get_ident
from types import SimpleNamespace

import pytest

from controlel.application.runtime.control_runtime import ControlRuntime as CoreControlRuntime
from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationStatus,
)
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingResult,
    RuntimeProcessingStatus,
    TemperatureNoDecisionReason,
)
from controlel.application.services.heating_diagnostics_boundary import (
    HeatingDiagnosticsBoundary,
    HeatingDiagnosticsProjectionResult,
)
from controlel.application.services.heating_diagnostics_projector import HeatingDiagnosticsProjector
from controlel.application.services.heating_performance_assessor import HeatingPerformanceAssessor
from controlel.application.services.shadow_heating_performance_monitor import ShadowHeatingPerformanceMonitor
from controlel.application.services.source_control_policy import SourceControlOutcome, SourceControlPolicy
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.heat_delivery import (
    HeatingDemandTransition,
    HeatingEpisode,
    HeatingEpisodeSample,
    HeatingEpisodeTerminationReason,
    HeatSourceObservation,
    ObservedValue,
)
from controlel.domain.source_control import (
    ReportedSourceEvidence,
    ReportedSourceState,
    TransitionHistoryKnowledge,
)
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId
from custom_components.controlel import ControlRuntime as HomeAssistantControlRuntime
from custom_components.controlel.config import (
    DiagnosticConfiguration,
    HomeAssistantSensorBinding,
)
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.failure_sink import HomeAssistantScheduledFailureSink
from custom_components.controlel.host import (
    HomeAssistantControlelHost,
    _command_outcome_for_evaluation,
    _reported_source_evidence,
    _source_control_snapshot_changes,
)
from custom_components.controlel.measurement_ingestion import (
    HomeAssistantMeasurementMapper,
)
from custom_components.controlel.operational import CommandOutcome
from custom_components.controlel.runtime_executor import HomeAssistantRuntimeExecutor

NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "source_outcome", "expected"),
    (
        (HeatDemandEvaluationStatus.RESILIENCE_COMMAND_EXECUTED, None, CommandOutcome.DISPATCHED),
        (HeatDemandEvaluationStatus.RESILIENCE_COMMAND_SUPPRESSED, None, CommandOutcome.SUPPRESSED),
        (
            HeatDemandEvaluationStatus.RESILIENCE_COMMAND_SUPPRESSED,
            SourceControlOutcome.SUPPRESS_DUPLICATE,
            CommandOutcome.SUPPRESSED_DUPLICATE,
        ),
        (HeatDemandEvaluationStatus.RESILIENCE_COMMAND_DEFERRED, None, CommandOutcome.DEFERRED),
        (HeatDemandEvaluationStatus.RESILIENCE_COMMAND_HELD, None, CommandOutcome.HELD),
        (HeatDemandEvaluationStatus.RESILIENCE_INDETERMINATE, None, CommandOutcome.NONE),
    ),
)
def test_core_0_6_resilience_statuses_have_truthful_ha_command_outcomes(
    status,
    source_outcome,
    expected,
) -> None:
    source_assessment = None
    if source_outcome is not None:
        source_assessment = SimpleNamespace(outcome=source_outcome)
    result = SimpleNamespace(status=status, source_control_assessment=source_assessment)

    assert _command_outcome_for_evaluation(result) is expected


def _disabled_source_state(policy: SourceControlPolicy):
    initial = policy.initial_state(NOW)
    assessment = policy.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW,
        current_state=initial,
    )
    return policy.record_dispatched(
        assessment,
        dispatched_at=NOW,
        safety_command=False,
    )


def test_core_0_4_precise_passive_boundary_has_no_active_lockout_claim() -> None:
    boundary = NOW + timedelta(minutes=5)
    policy = SourceControlPolicy(
        minimum_on_time=timedelta(minutes=10),
        minimum_off_time=timedelta(minutes=5),
    )
    state = _disabled_source_state(policy)

    changes = _source_control_snapshot_changes(state)

    assert changes["source_control_state"].value == "heating_not_requested"
    assert changes["earliest_next_enable_time"] == boundary
    assert changes["active_lockout_type"] is None
    assert changes["active_lockout_deadline"] is None
    assert changes["deferred_command"] is None
    assert changes["last_successful_disable_dispatch"] == NOW


def test_core_0_4_precise_deferred_enable_and_cancellation_are_projected() -> None:
    policy = SourceControlPolicy(
        minimum_on_time=timedelta(minutes=10),
        minimum_off_time=timedelta(minutes=5),
    )
    passive = _disabled_source_state(policy)
    requested_at = NOW + timedelta(seconds=1)
    deferred = policy.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=requested_at,
        current_state=passive,
    ).state

    changes = _source_control_snapshot_changes(deferred)

    assert changes["source_control_state"].value == "heating_requested_waiting_minimum_off"
    assert changes["active_lockout_type"].value == "minimum_off"
    assert changes["active_lockout_deadline"] == passive.earliest_next_enable_time
    assert changes["deferred_command"] == "enable_heating"
    assert changes["deferred_since"] == requested_at
    assert changes["deferred_deadline"] == passive.earliest_next_enable_time

    cancelled = policy.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=requested_at + timedelta(seconds=1),
        current_state=deferred,
    ).state
    cancelled_changes = _source_control_snapshot_changes(cancelled)

    assert cancelled_changes["source_control_state"].value == "heating_not_requested"
    assert cancelled_changes["earliest_next_enable_time"] == passive.earliest_next_enable_time
    assert cancelled_changes["active_lockout_type"] is None
    assert cancelled_changes["active_lockout_deadline"] is None
    assert cancelled_changes["deferred_command"] is None
    assert cancelled_changes["deferred_deadline"] is None


def test_core_0_4_precise_deferred_disable_and_safety_bypass_are_projected() -> None:
    policy = SourceControlPolicy(
        minimum_on_time=timedelta(minutes=10),
        minimum_off_time=timedelta(minutes=5),
    )
    initial = policy.initial_state(NOW)
    enable = policy.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW,
        current_state=initial,
    )
    enabled = policy.record_dispatched(enable, dispatched_at=NOW, safety_command=False)
    requested_at = NOW + timedelta(seconds=1)
    deferred = policy.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=requested_at,
        current_state=enabled,
    ).state

    changes = _source_control_snapshot_changes(deferred)

    assert changes["source_control_state"].value == "heating_not_requested_waiting_minimum_on"
    assert changes["active_lockout_type"].value == "minimum_on"
    assert changes["active_lockout_deadline"] == enabled.earliest_next_disable_time
    assert changes["deferred_command"] == "disable_heating"
    assert changes["last_successful_enable_dispatch"] == NOW

    safety = policy.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=requested_at,
        current_state=enabled,
        safety_command=True,
    )
    safety_state = policy.record_dispatched(
        safety,
        dispatched_at=requested_at,
        safety_command=True,
    )
    safety_changes = _source_control_snapshot_changes(safety_state)

    assert safety_changes["source_control_state"].value == "safety_override"
    assert safety_changes["safety_bypassed_lockout"] is True
    assert safety_changes["active_lockout_type"] is None
    assert safety_changes["deferred_command"] is None
    assert safety_changes["last_successful_enable_dispatch"] == NOW
    assert safety_changes["last_successful_disable_dispatch"] == requested_at


def host_config():
    return SimpleNamespace(
        zone_name="Room",
        zone_id=ZoneId("room"),
        sensor_name="Room temperature",
        sensor_id=SensorId("room_temperature"),
        temperature_entity_id="sensor.room",
        target_temperature=Temperature(21),
        heating_turn_on_differential=0.3,
        heating_turn_off_differential=0.1,
        heat_demand_confirmation_duration=timedelta(minutes=2),
        primary_measurement_max_age=timedelta(minutes=5),
        indeterminate_grace_period=timedelta(minutes=1),
        minimum_heating_on_time=timedelta(minutes=10),
        minimum_heating_off_time=timedelta(minutes=5),
        indeterminate_timeout_action=SimpleNamespace(value="disable_heating"),
        diagnostic_configuration=DiagnosticConfiguration(
            profile="basic",
            debug_duration=timedelta(hours=1),
            configured_debug_duration=timedelta(hours=1),
            profile_before_debug="detailed",
        ),
    )


@dataclass
class FakeState:
    state: str
    last_updated: datetime
    entity_id: str = "sensor.room"
    last_changed: datetime | None = None

    @property
    def attributes(self):
        return {"unit_of_measurement": "°C"}


def test_reported_source_mapping_is_explicit_without_startup_transition_history() -> None:
    for raw, expected in (
        ("on", ReportedSourceState.ENABLED),
        ("off", ReportedSourceState.DISABLED),
        ("unknown", ReportedSourceState.UNKNOWN),
        ("unavailable", ReportedSourceState.UNAVAILABLE),
    ):
        evidence = _reported_source_evidence(
            FakeState(raw, NOW, entity_id="switch.boiler"),
            "switch.boiler",
        )
        assert evidence is not None
        assert evidence.state is expected
        assert evidence.observed_at == NOW
        assert evidence.transition_at is None

    assert _reported_source_evidence(None, "switch.boiler") is None
    assert _reported_source_evidence(FakeState("on", NOW), "switch.boiler") is None


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    (
        ("off", "on", ReportedSourceState.ENABLED),
        ("on", "off", ReportedSourceState.DISABLED),
    ),
)
def test_genuine_stable_reported_transition_has_known_ha_timestamp(old, new, expected) -> None:
    changed_at = NOW + timedelta(seconds=1)
    evidence = _reported_source_evidence(
        FakeState(new, changed_at, entity_id="switch.boiler", last_changed=changed_at),
        "switch.boiler",
        previous_state=FakeState(old, NOW, entity_id="switch.boiler", last_changed=NOW),
    )

    assert evidence is not None
    assert evidence.state is expected
    assert evidence.transition_at == changed_at
    assert evidence.transition_history is TransitionHistoryKnowledge.KNOWN


@pytest.mark.parametrize("old", ["unknown", "unavailable"])
@pytest.mark.parametrize("new", ["on", "off"])
def test_indeterminate_to_stable_report_does_not_invent_transition_age(old, new) -> None:
    changed_at = NOW + timedelta(seconds=1)
    evidence = _reported_source_evidence(
        FakeState(new, changed_at, entity_id="switch.boiler", last_changed=changed_at),
        "switch.boiler",
        previous_state=FakeState(old, NOW, entity_id="switch.boiler", last_changed=NOW),
    )

    assert evidence is not None
    assert evidence.transition_at is None
    assert evidence.transition_history is TransitionHistoryKnowledge.UNKNOWN


@pytest.mark.parametrize(
    ("raw", "reported"), (("on", ReportedSourceState.ENABLED), ("off", ReportedSourceState.DISABLED))
)
def test_same_state_report_keeps_prior_transition_without_rearming(raw, reported) -> None:
    original_transition = NOW
    observed_at = NOW + timedelta(seconds=10)
    evidence = _reported_source_evidence(
        FakeState(raw, observed_at, entity_id="switch.boiler", last_changed=original_transition),
        "switch.boiler",
        previous_state=FakeState(raw, NOW, entity_id="switch.boiler", last_changed=original_transition),
        prior_evidence=ReportedSourceEvidence(reported, NOW, original_transition),
    )

    assert evidence is not None
    assert evidence.transition_at == original_transition


def test_command_echo_keeps_dispatch_and_reported_protection_separate_and_monotonic() -> None:
    policy = SourceControlPolicy(
        minimum_on_time=timedelta(seconds=60),
        minimum_off_time=timedelta(seconds=60),
    )
    requested = policy.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW,
        current_state=None,
    )
    dispatched = policy.record_dispatched(requested, dispatched_at=NOW, safety_command=False)
    visible_at = NOW + timedelta(seconds=2)
    evidence = _reported_source_evidence(
        FakeState("on", visible_at, entity_id="switch.boiler", last_changed=visible_at),
        "switch.boiler",
        previous_state=FakeState("off", NOW, entity_id="switch.boiler", last_changed=NOW),
    )
    assert evidence is not None

    corrective = policy.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(seconds=3),
        current_state=dispatched,
        corrective_reconciliation=True,
        reported_source_evidence=evidence,
    )
    report_protected = policy.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(seconds=60),
        current_state=corrective.state,
        corrective_reconciliation=True,
        reported_source_evidence=evidence,
        lockout_expiry_reevaluation=True,
    )
    repeated = _reported_source_evidence(
        FakeState("on", NOW + timedelta(seconds=10), entity_id="switch.boiler", last_changed=visible_at),
        "switch.boiler",
        previous_state=FakeState("on", visible_at, entity_id="switch.boiler", last_changed=visible_at),
        prior_evidence=evidence,
    )

    assert dispatched.last_successful_enable_dispatch == NOW
    assert evidence.transition_at == visible_at
    assert corrective.outcome is SourceControlOutcome.DEFER
    assert corrective.lockout_deadline == NOW + timedelta(seconds=60)
    assert report_protected.outcome is SourceControlOutcome.DEFER
    assert report_protected.lockout_deadline == visible_at + timedelta(seconds=60)
    assert repeated is not None
    assert repeated.transition_at == visible_at


def test_three_manual_on_attempts_each_establish_a_fresh_minimum_on_boundary() -> None:
    policy = SourceControlPolicy(
        minimum_on_time=timedelta(seconds=60),
        minimum_off_time=timedelta(seconds=60),
    )
    initial_time = NOW - timedelta(seconds=60)
    initial = policy.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=initial_time,
        current_state=None,
    )
    state = policy.record_dispatched(initial, dispatched_at=initial_time, safety_command=False)

    for attempt in range(3):
        transition_at = NOW + timedelta(minutes=2 * attempt)
        evidence = _reported_source_evidence(
            FakeState("on", transition_at, entity_id="switch.boiler", last_changed=transition_at),
            "switch.boiler",
            previous_state=FakeState(
                "off",
                transition_at - timedelta(seconds=1),
                entity_id="switch.boiler",
                last_changed=transition_at - timedelta(seconds=1),
            ),
        )
        assert evidence is not None
        deferred = policy.evaluate(
            desired_command=HeatingAction.DISABLE_HEATING,
            now=transition_at + timedelta(seconds=1),
            current_state=state,
            corrective_reconciliation=True,
            reported_source_evidence=evidence,
        )

        deadline = transition_at + timedelta(seconds=60)
        assert deferred.outcome is SourceControlOutcome.DEFER
        assert deferred.lockout_deadline == deadline

        due = policy.evaluate(
            desired_command=HeatingAction.DISABLE_HEATING,
            now=deadline,
            current_state=deferred.state,
            corrective_reconciliation=True,
            reported_source_evidence=evidence,
            lockout_expiry_reevaluation=True,
        )
        assert due.outcome is SourceControlOutcome.DISPATCH
        state = policy.record_dispatched(due, dispatched_at=deadline, safety_command=False)


class FakeHass:
    def async_create_task(self, target, name=None):
        return asyncio.create_task(target, name=name)


class FakeRuntime:
    def __init__(self):
        self.operations: list[tuple[str, object]] = []
        self.worker_threads: list[int] = []
        self.process_entered = Event()
        self.process_release = Event()
        self.process_release.set()
        self.start_entered = Event()
        self.start_release = Event()
        self.start_release.set()

    def process_temperature(self, measurement):
        self.worker_threads.append(get_ident())
        self.operations.append(("measurement", measurement.value.value))
        self.process_entered.set()
        self.process_release.wait()
        return RuntimeProcessingResult(
            status=RuntimeProcessingStatus.NO_DECISION,
            reason=TemperatureNoDecisionReason.SECONDARY_MEASUREMENT,
        )

    def start(self):
        self.worker_threads.append(get_ident())
        self.operations.append(("start", None))
        self.start_entered.set()
        self.start_release.wait()
        return SimpleNamespace(
            status=HeatDemandEvaluationStatus.INDETERMINATE_GRACE,
            next_evaluation_at=NOW,
        )

    def reevaluate_heat_demand(self):
        self.worker_threads.append(get_ident())
        self.operations.append(("reevaluate", None))
        return SimpleNamespace(
            status=HeatDemandEvaluationStatus.INDETERMINATE_GRACE,
            next_evaluation_at=NOW,
        )

    def mark_measurement_indeterminate(self):
        self.worker_threads.append(get_ident())
        self.operations.append(("indeterminate", None))
        return SimpleNamespace(
            status=HeatDemandEvaluationStatus.INDETERMINATE_GRACE,
            next_evaluation_at=NOW,
        )

    def stop(self):
        self.worker_threads.append(get_ident())
        self.operations.append(("stop", None))


def completed_shadow_episode(offset: int = 0) -> HeatingEpisode:
    started_at = NOW + timedelta(minutes=offset)
    ended_at = started_at + timedelta(minutes=1)
    samples = tuple(
        HeatingEpisodeSample(
            captured_at=timestamp,
            zone_temperature=ObservedValue.valid(temperature, timestamp),
            target_temperature=21.0,
            actuator_observations=(),
            source_observation=HeatSourceObservation(captured_at=timestamp),
        )
        for timestamp, temperature in ((started_at, 19.0), (ended_at, 19.5))
    )
    return HeatingEpisode(
        zone_id=ZoneId("room"),
        started_at=started_at,
        ended_at=ended_at,
        termination_reason=HeatingEpisodeTerminationReason.DEMAND_CLEARED,
        initial_target_temperature=21.0,
        current_target_temperature=21.0,
        initial_temperature=19.0,
        current_temperature=19.5,
        demand_transitions=(
            HeatingDemandTransition(demand=BuildingHeatDemandStatus.HEAT_REQUIRED, changed_at=started_at),
            HeatingDemandTransition(demand=BuildingHeatDemandStatus.NO_HEAT_REQUIRED, changed_at=ended_at),
        ),
        total_sample_count=2,
        samples_truncated=False,
        samples=samples,
    )


class ShadowAssessmentRuntime(FakeRuntime):
    def __init__(self, monitor: ShadowHeatingPerformanceMonitor) -> None:
        super().__init__()
        self.heating_performance_monitor = monitor
        self.heating_episode_observer = FakeEpisodeObserver()
        self._episode_offset = 0

    def process_temperature(self, measurement):
        result = super().process_temperature(measurement)
        episode = completed_shadow_episode(self._episode_offset)
        self.heating_episode_observer.completed.append(episode)
        self.heating_performance_monitor.submit_episode(episode)
        self._episode_offset += 2
        return result


class FakeEpisodeObserver:
    def __init__(self) -> None:
        self.active_episodes = ()
        self.completed = []

    @property
    def completed_episodes(self):
        return tuple(self.completed)


class BlockingShadowAssessor:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self._delegate = HeatingPerformanceAssessor()

    def assess(self, episode):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("shadow assessment was not released")
        return self._delegate.assess(episode)


class FailingShadowAssessor:
    def assess(self, episode):
        raise RuntimeError(f"shadow failure for {episode.zone_id.value}")


class BlockingDiagnosticsProjector:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self._delegate = HeatingDiagnosticsProjector()

    def project(self, **kwargs):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("diagnostic projection was not released")
        return self._delegate.project(**kwargs)


class FailingDiagnosticsProjector:
    def project(self, **kwargs):
        raise RuntimeError("password=secret must not be projected")


def create_shadow_test_host(
    runtime: FakeRuntime,
    *,
    heating_diagnostics_projector=None,
    heating_diagnostics_boundary=None,
    heating_diagnostics_enabled=True,
) -> HomeAssistantControlelHost:
    hass = FakeHass()
    failure_sink = HomeAssistantScheduledFailureSink(
        hass,
        HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
        "entry",
        logging.getLogger(__name__),
        create_issue=lambda *args, **kwargs: None,
        delete_issue=lambda *args: None,
        warning_severity="warning",
        error_severity="error",
    )
    host = HomeAssistantControlelHost(
        hass=hass,
        runtime=runtime,
        executor=HomeAssistantRuntimeExecutor(),
        measurement_mapper=HomeAssistantMeasurementMapper(
            HomeAssistantSensorBinding("sensor.room", SensorId("room_temperature"))
        ),
        failure_sink=failure_sink,
        config=host_config(),
        core_version="0.6.0",
        logger=logging.getLogger(__name__),
        state_subscriber=lambda hass, entity_id, listener: lambda: None,
        state_getter=lambda entity_id: None,
        shutdown_subscriber=lambda hass, listener: lambda: None,
        interval_subscriber=lambda hass, listener, interval: lambda: None,
        heating_diagnostics_boundary=(
            heating_diagnostics_boundary
            or (
                HeatingDiagnosticsBoundary(projector=heating_diagnostics_projector)
                if heating_diagnostics_projector is not None
                else None
            )
        ),
        heating_diagnostics_enabled=heating_diagnostics_enabled,
    )
    failure_sink.bind_fatal_handler(host.request_fatal_shutdown)
    return host


def test_home_assistant_runtime_start_does_not_evaluate_empty_core_state(monkeypatch):
    def fail_if_called(runtime):
        raise AssertionError("core startup evaluation must not run before a real HA state")

    monkeypatch.setattr(CoreControlRuntime, "start", fail_if_called)
    runtime = object.__new__(HomeAssistantControlRuntime)

    assert runtime.start() is None


def test_production_host_drains_completed_episode_after_control_returns() -> None:
    async def scenario():
        monitor = ShadowHeatingPerformanceMonitor()
        runtime = ShadowAssessmentRuntime(monitor)
        host = create_shadow_test_host(runtime)
        await host.async_initialize()

        result = await host.async_process_state(FakeState("19", NOW))
        for _ in range(100):
            if monitor.assessments:
                break
            await asyncio.sleep(0.001)

        await host.async_stop()
        return (
            result,
            monitor.assessments,
            len(host._shadow_assessment_tasks),
            host.snapshot_source.current.heating_diagnostics,
        )

    result, assessments, remaining_shadow_tasks, diagnostics = asyncio.run(scenario())

    assert result is not None
    assert result.status is RuntimeProcessingStatus.NO_DECISION
    assert len(assessments) == 1
    assert assessments[0].zone_id == ZoneId("room")
    assert remaining_shadow_tasks == 0
    assert diagnostics.schema_version == 1
    assert diagnostics.zones[0].active_episode is None
    assert diagnostics.zones[0].latest_completed_episode is not None
    assert diagnostics.zones[0].latest_assessment is not None
    assert diagnostics.zones[0].latest_assessment.status == "assessed"


def test_blocked_production_assessor_does_not_block_next_control_event() -> None:
    async def scenario():
        assessor = BlockingShadowAssessor()
        monitor = ShadowHeatingPerformanceMonitor(assessor=assessor)
        runtime = ShadowAssessmentRuntime(monitor)
        host = create_shadow_test_host(runtime)
        await host.async_initialize()

        first = await host.async_process_state(FakeState("19", NOW))
        while not assessor.entered.is_set():
            await asyncio.sleep(0)
        second = await asyncio.wait_for(
            host.async_process_state(FakeState("19.5", NOW + timedelta(seconds=1))),
            timeout=1,
        )
        operations_before_release = tuple(runtime.operations)
        assessor.release.set()
        await host.async_stop()
        return first, second, operations_before_release, monitor.assessments

    first, second, operations, assessments = asyncio.run(scenario())

    assert first is not None and second is not None
    assert [operation[0] for operation in operations] == ["start", "measurement", "measurement"]
    assert len(assessments) == 2


def test_production_assessor_failure_cannot_change_completed_control_result() -> None:
    async def scenario():
        monitor = ShadowHeatingPerformanceMonitor(assessor=FailingShadowAssessor())
        runtime = ShadowAssessmentRuntime(monitor)
        host = create_shadow_test_host(runtime)
        await host.async_initialize()

        result = await host.async_process_state(FakeState("19", NOW))
        for _ in range(100):
            if monitor.errors:
                break
            await asyncio.sleep(0.001)
        await host.async_stop()
        return (
            result,
            tuple(runtime.operations),
            monitor.errors,
            host.snapshot_source.current.heating_diagnostics,
        )

    result, operations, errors, diagnostics = asyncio.run(scenario())

    assert result is not None
    assert result.status is RuntimeProcessingStatus.NO_DECISION
    assert operations[:2] == (("start", None), ("measurement", 19.0))
    assert errors == {ZoneId("room"): "RuntimeError: shadow failure for room"}
    assert diagnostics.pipeline.health_code == "degraded"
    assert diagnostics.pipeline.assessment_errors[0].exception_type == "RuntimeError"


def test_blocked_diagnostic_projection_does_not_hold_runtime_or_delay_control_events() -> None:
    async def scenario():
        projector = BlockingDiagnosticsProjector()
        runtime = FakeRuntime()
        host = create_shadow_test_host(runtime, heating_diagnostics_projector=projector)
        await host.async_initialize()

        first = await host.async_process_state(FakeState("19", NOW))
        while not projector.entered.is_set():
            await asyncio.sleep(0)
        second = await asyncio.wait_for(
            host.async_process_state(FakeState("19.5", NOW + timedelta(seconds=1))),
            timeout=1,
        )
        operations = tuple(runtime.operations)
        projector.release.set()
        await host.async_stop()
        return first, second, operations

    first, second, operations = asyncio.run(scenario())

    assert first is not None and second is not None
    assert [operation[0] for operation in operations] == ["start", "measurement", "measurement"]


def test_failed_diagnostic_projection_is_safe_and_cannot_change_control_result() -> None:
    async def scenario():
        runtime = FakeRuntime()
        host = create_shadow_test_host(runtime, heating_diagnostics_projector=FailingDiagnosticsProjector())
        await host.async_initialize()

        result = await host.async_process_state(FakeState("19", NOW))
        for _ in range(100):
            if host.snapshot_source.current.heating_diagnostics.pipeline.projection_error is not None:
                break
            await asyncio.sleep(0.001)
        diagnostics = host.snapshot_source.current.heating_diagnostics
        await host.async_stop()
        return result, tuple(runtime.operations), diagnostics

    result, operations, diagnostics = asyncio.run(scenario())

    assert result is not None
    assert result.status is RuntimeProcessingStatus.NO_DECISION
    assert operations[:2] == (("start", None), ("measurement", 19.0))
    assert diagnostics.pipeline.health_code == "unavailable"
    assert diagnostics.pipeline.projection_error is not None
    assert diagnostics.pipeline.projection_error.exception_type == "RuntimeError"
    assert "password=secret" not in str(diagnostics)


def test_stale_diagnostic_projection_cannot_overwrite_newer_generation() -> None:
    class OutOfOrderBoundary:
        def __init__(self) -> None:
            self.calls = 0
            self.first_entered = Event()
            self.release_first = Event()

        def project(self, *, current, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return HeatingDiagnosticsProjectionResult(snapshot=current)
            if self.calls == 2:
                self.first_entered.set()
                if not self.release_first.wait(timeout=5):
                    raise TimeoutError("older diagnostic generation was not released")
                return HeatingDiagnosticsProjectionResult(
                    snapshot=replace(current, updated_at="2026-07-23T10:00:01+00:00")
                )
            return HeatingDiagnosticsProjectionResult(snapshot=replace(current, updated_at="2026-07-23T10:00:02+00:00"))

    async def scenario():
        boundary = OutOfOrderBoundary()
        runtime = FakeRuntime()
        host = create_shadow_test_host(runtime, heating_diagnostics_boundary=boundary)
        await host.async_initialize()
        while boundary.calls < 1:
            await asyncio.sleep(0)

        publications = []
        unsubscribe = host.snapshot_source.subscribe(
            lambda snapshot: publications.append(snapshot.heating_diagnostics.updated_at)
        )
        first = await host.async_process_state(FakeState("19", NOW))
        while not boundary.first_entered.is_set():
            await asyncio.sleep(0)
        second = await asyncio.wait_for(
            host.async_process_state(FakeState("19.5", NOW + timedelta(seconds=1))),
            timeout=1,
        )
        for _ in range(100):
            if host.snapshot_source.current.heating_diagnostics.updated_at == "2026-07-23T10:00:02+00:00":
                break
            await asyncio.sleep(0.001)
        operations_before_release = tuple(runtime.operations)
        boundary.release_first.set()
        await host._async_wait_for_heating_diagnostics()
        final_updated_at = host.snapshot_source.current.heating_diagnostics.updated_at
        unsubscribe()
        await host.async_stop()
        return first, second, operations_before_release, publications, final_updated_at

    first, second, operations, publications, final_updated_at = asyncio.run(scenario())

    assert first is not None and second is not None
    assert [operation[0] for operation in operations] == ["start", "measurement", "measurement"]
    assert final_updated_at == "2026-07-23T10:00:02+00:00"
    assert "2026-07-23T10:00:01+00:00" not in publications
    assert publications.count("2026-07-23T10:00:02+00:00") == 1


def test_start_precedes_snapshot_buffer_drain_live_events_and_stop():
    async def scenario():
        event_loop_thread = get_ident()
        hass = FakeHass()
        executor = HomeAssistantRuntimeExecutor()
        runtime = FakeRuntime()
        runtime.process_release.clear()
        runtime.start_release.clear()
        listener_holder = {}
        unsubscribed: list[None] = []

        def subscribe(hass, entity_id, listener):
            listener_holder["listener"] = listener
            return lambda: unsubscribed.append(None)

        failure_sink = HomeAssistantScheduledFailureSink(
            hass,
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            "entry",
            logging.getLogger(__name__),
            create_issue=lambda *args, **kwargs: None,
            delete_issue=lambda *args: None,
            warning_severity="warning",
            error_severity="error",
        )
        host = HomeAssistantControlelHost(
            hass=hass,
            runtime=runtime,
            executor=executor,
            measurement_mapper=HomeAssistantMeasurementMapper(
                HomeAssistantSensorBinding(
                    "sensor.room",
                    SensorId("room_temperature"),
                )
            ),
            failure_sink=failure_sink,
            config=host_config(),
            core_version="0.4.0",
            logger=logging.getLogger(__name__),
            state_subscriber=subscribe,
            state_getter=lambda entity_id: FakeState("19", NOW),
            shutdown_subscriber=lambda hass, listener: lambda: None,
            interval_subscriber=lambda hass, listener, interval: lambda: None,
        )
        failure_sink.bind_fatal_handler(host.request_fatal_shutdown)

        initialize = asyncio.create_task(host.async_initialize())
        while not runtime.start_entered.is_set():
            await asyncio.sleep(0)
        listener_holder["listener"](FakeState("20", NOW.replace(second=1)))
        runtime.start_release.set()

        while not runtime.process_entered.is_set():
            await asyncio.sleep(0)
        listener_holder["listener"](FakeState("21", NOW.replace(second=2)))
        runtime.process_release.set()
        await initialize

        listener_holder["listener"](FakeState("22", NOW.replace(second=3)))
        while len(runtime.operations) < 5:
            await asyncio.sleep(0)

        duplicate = FakeState("22", NOW.replace(second=3))
        listener_holder["listener"](duplicate)
        await asyncio.sleep(0.01)

        await host.async_stop()
        await host.async_stop()
        listener_holder["listener"](FakeState("23", NOW.replace(second=4)))
        await asyncio.sleep(0)
        return (
            runtime,
            host,
            unsubscribed,
            event_loop_thread,
        )

    runtime, host, unsubscribed, event_loop_thread = asyncio.run(scenario())

    assert runtime.operations == [
        ("start", None),
        ("measurement", 19.0),
        ("measurement", 20.0),
        ("measurement", 21.0),
        ("measurement", 22.0),
        ("stop", None),
    ]
    assert len(set(runtime.worker_threads)) == 1
    assert runtime.worker_threads[0] != event_loop_thread
    assert unsubscribed == [None]
    assert host.accepting is False
    assert host.stopped is True


@pytest.mark.parametrize("state_value", ["unavailable", "unknown"])
def test_start_precedes_explicit_indeterminate_snapshot_initialization(state_value):
    async def scenario():
        hass = FakeHass()
        executor = HomeAssistantRuntimeExecutor()
        runtime = FakeRuntime()
        failure_sink = HomeAssistantScheduledFailureSink(
            hass,
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            "entry",
            logging.getLogger(__name__),
            create_issue=lambda *args, **kwargs: None,
            delete_issue=lambda *args: None,
            warning_severity="warning",
            error_severity="error",
        )
        host = HomeAssistantControlelHost(
            hass=hass,
            runtime=runtime,
            executor=executor,
            measurement_mapper=HomeAssistantMeasurementMapper(
                HomeAssistantSensorBinding(
                    "sensor.room",
                    SensorId("room_temperature"),
                )
            ),
            failure_sink=failure_sink,
            config=host_config(),
            core_version="0.4.0",
            logger=logging.getLogger(__name__),
            state_subscriber=lambda hass, entity_id, listener: lambda: None,
            state_getter=lambda entity_id: FakeState(state_value, NOW),
            shutdown_subscriber=lambda hass, listener: lambda: None,
            interval_subscriber=lambda hass, listener, interval: lambda: None,
        )
        failure_sink.bind_fatal_handler(host.request_fatal_shutdown)
        await host.async_initialize()
        await host.async_stop()
        return runtime.operations

    assert asyncio.run(scenario()) == [
        ("start", None),
        ("indeterminate", None),
        ("stop", None),
    ]


def test_absent_snapshot_waits_for_one_buffered_real_state_without_indeterminate():
    async def scenario():
        hass = FakeHass()
        runtime = FakeRuntime()
        runtime.start_release.clear()
        listener_holder = {}

        def subscribe(hass, entity_id, listener):
            listener_holder["listener"] = listener
            return lambda: None

        failure_sink = HomeAssistantScheduledFailureSink(
            hass,
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            "entry",
            logging.getLogger(__name__),
            create_issue=lambda *args, **kwargs: None,
            delete_issue=lambda *args: None,
            warning_severity="warning",
            error_severity="error",
        )
        host = HomeAssistantControlelHost(
            hass=hass,
            runtime=runtime,
            executor=HomeAssistantRuntimeExecutor(),
            measurement_mapper=HomeAssistantMeasurementMapper(
                HomeAssistantSensorBinding("sensor.room", SensorId("room_temperature"))
            ),
            failure_sink=failure_sink,
            config=host_config(),
            core_version="0.4.0",
            logger=logging.getLogger(__name__),
            state_subscriber=subscribe,
            state_getter=lambda entity_id: None,
            shutdown_subscriber=lambda hass, listener: lambda: None,
            interval_subscriber=lambda hass, listener, interval: lambda: None,
        )
        failure_sink.bind_fatal_handler(host.request_fatal_shutdown)

        initialize = asyncio.create_task(host.async_initialize())
        while not runtime.start_entered.is_set():
            await asyncio.sleep(0)
        listener_holder["listener"](FakeState("20", NOW))
        runtime.start_release.set()
        await initialize
        await host.async_stop()
        return runtime.operations

    assert asyncio.run(scenario()) == [
        ("start", None),
        ("measurement", 20.0),
        ("stop", None),
    ]
