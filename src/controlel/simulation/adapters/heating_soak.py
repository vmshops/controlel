"""One bounded deterministic soak validation for the heating Shadow adapter."""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from controlel.application.runtime.heat_demand_evaluation_result import HeatDemandEvaluationStatus
from controlel.application.runtime.runtime_processing_result import RuntimeProcessingStatus
from controlel.simulation.adapters.heating import HeatingSimulationAdapter
from controlel.simulation.model import (
    ReplayArtifact,
    RuntimeOrigin,
    SimulationMode,
    SimulationOutcome,
    SimulationReport,
)
from controlel.simulation.runner import ScenarioRunner
from controlel.simulation.scenario import Scenario, canonical_json

HEATING_SOAK_GENERATOR_VERSION = 1
HEATING_SOAK_MAX_DURATION = timedelta(days=2)
HEATING_SOAK_MAX_TIMELINE_EVENTS = 512
HEATING_SOAK_MIN_EVENT_INTERVAL = timedelta(minutes=5)
HEATING_SOAK_MAX_EVENT_INTERVAL = timedelta(minutes=30)
_ANOMALY_CODES = {
    "heating_anomaly_started": "started",
    "heating_anomaly_changed": "active",
    "heating_anomaly_cleared": "cleared",
    "heating_anomaly_observation_ended": "observation_ended",
}


class HeatingSoakOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class HeatingSoakConfiguration(BaseModel):
    """Fixed-purpose bounds and seed for the v0.1 heating soak."""

    seed: int = Field(ge=0, le=2**63 - 1)
    start_at: datetime = datetime(2026, 1, 15, tzinfo=UTC)
    virtual_duration: timedelta = timedelta(hours=24)
    event_interval: timedelta = timedelta(minutes=10)
    restart_count: int = Field(default=4, ge=2, le=8)
    inject_reproducible_source_failure: bool = False

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("start_at")
    @classmethod
    def start_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("start_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def bounds_must_fit_one_soak(self) -> HeatingSoakConfiguration:
        if not timedelta(hours=2) <= self.virtual_duration <= HEATING_SOAK_MAX_DURATION:
            raise ValueError("virtual_duration must be between 2 hours and 2 days")
        if not HEATING_SOAK_MIN_EVENT_INTERVAL <= self.event_interval <= HEATING_SOAK_MAX_EVENT_INTERVAL:
            raise ValueError("event_interval must be between 5 and 30 minutes")
        slot_count = int(self.virtual_duration // self.event_interval)
        if slot_count < self.restart_count * 3 + 6:
            raise ValueError("duration and interval do not provide enough bounded slots for requested restarts")
        return self

    def canonical_data(self) -> dict[str, object]:
        return {
            "event_interval_seconds": self.event_interval.total_seconds(),
            "generator_version": HEATING_SOAK_GENERATOR_VERSION,
            "inject_reproducible_source_failure": self.inject_reproducible_source_failure,
            "restart_count": self.restart_count,
            "seed": self.seed,
            "start_at": self.start_at,
            "virtual_duration_seconds": self.virtual_duration.total_seconds(),
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.canonical_data()).encode("utf-8")).hexdigest()


class HeatingSoakReport(BaseModel):
    """Compact deterministic summary; full evidence remains in HeatingSoakResult."""

    generator_version: int = HEATING_SOAK_GENERATOR_VERSION
    seed: int
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    virtual_duration_seconds: float = Field(ge=0)
    event_count: int = Field(ge=1)
    event_limit: int = HEATING_SOAK_MAX_TIMELINE_EVENTS
    restart_count: int = Field(ge=0)
    anomaly_started_count: int = Field(ge=0)
    anomaly_changed_count: int = Field(ge=0)
    anomaly_cleared_count: int = Field(ge=0)
    anomaly_observation_ended_count: int = Field(ge=0)
    command_count: int = Field(ge=0)
    dispatched_command_count: int = Field(ge=0)
    failed_command_count: int = Field(ge=0)
    outcome: HeatingSoakOutcome
    failed_invariants: tuple[str, ...] = ()
    scenario_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    replay_expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    model_config = ConfigDict(frozen=True, extra="forbid")


class HeatingSoakResult(BaseModel):
    """Replay-complete soak evidence and its compact summary."""

    configuration: HeatingSoakConfiguration
    scenario: Scenario
    simulation_report: SimulationReport
    replay_artifact: ReplayArtifact
    report: HeatingSoakReport

    model_config = ConfigDict(frozen=True, extra="forbid")


class HeatingSoakRunner:
    """Generate and execute the one fixed v0.1 heating soak validation."""

    def __init__(self, *, environment_id: str = "shadow-soak") -> None:
        self._scenario_runner = ScenarioRunner(HeatingSimulationAdapter, environment_id=environment_id)

    def run(self, configuration: HeatingSoakConfiguration) -> HeatingSoakResult:
        scenario = generate_heating_soak_scenario(configuration)
        simulation_report = self._scenario_runner.run(scenario)
        replay_artifact = ReplayArtifact.from_execution(scenario, simulation_report)
        failed_invariants, anomaly_counts = _check_invariants(scenario, simulation_report, configuration)
        command_records = tuple(record for record in simulation_report.records if record.kind == "command.source")
        summary = HeatingSoakReport(
            seed=configuration.seed,
            configuration_fingerprint=configuration.fingerprint,
            virtual_duration_seconds=(simulation_report.ended_at - simulation_report.run.started_at).total_seconds(),
            event_count=len(scenario.timeline),
            restart_count=sum(item.event.type == "runtime.restart" for item in scenario.timeline),
            anomaly_started_count=anomaly_counts["started"],
            anomaly_changed_count=anomaly_counts["active"],
            anomaly_cleared_count=anomaly_counts["cleared"],
            anomaly_observation_ended_count=anomaly_counts["observation_ended"],
            command_count=len(command_records),
            dispatched_command_count=sum(
                record.payload.get("dispatch_outcome") == "dispatched" for record in command_records
            ),
            failed_command_count=sum(record.payload.get("dispatch_outcome") == "failed" for record in command_records),
            outcome=HeatingSoakOutcome.PASS if not failed_invariants else HeatingSoakOutcome.FAIL,
            failed_invariants=failed_invariants,
            scenario_hash=scenario.content_hash,
            semantic_fingerprint=simulation_report.semantic_fingerprint,
            replay_expected_fingerprint=replay_artifact.expected_semantic_fingerprint,
        )
        return HeatingSoakResult(
            configuration=configuration,
            scenario=scenario,
            simulation_report=simulation_report,
            replay_artifact=replay_artifact,
            report=summary,
        )


def generate_heating_soak_scenario(configuration: HeatingSoakConfiguration) -> Scenario:
    """Materialize one replay-authoritative scenario from the fixed soak recipe."""

    rng = random.Random(configuration.seed)
    slot_count = int(configuration.virtual_duration // configuration.event_interval)
    eligible_restart_slots = tuple(range(3, slot_count - 2))
    restart_slots = set(rng.sample(eligible_restart_slots, configuration.restart_count))
    failure_slot = min(restart_slots) if configuration.inject_reproducible_source_failure else None
    unavailable_slots = _select_unavailable_slots(rng, slot_count, restart_slots)
    source_slots = set(range(6 + configuration.seed % 5, slot_count + 1, 12)) | restart_slots
    checkpoint_stride = max(1, int(timedelta(hours=6) // configuration.event_interval))

    timeline: list[dict[str, object]] = [
        {
            "at": configuration.start_at,
            "event": {"type": "runtime.start"},
        }
    ]
    temperature = 19.5
    sensor_available = True
    last_temperature_observed_at = configuration.start_at
    reported_source_state = "disabled"

    for slot in range(1, slot_count + 1):
        delivery_at = configuration.start_at + slot * configuration.event_interval
        temperature = _next_external_temperature(temperature, slot, rng)

        if slot == failure_slot:
            timeline.append(
                {
                    "at": delivery_at,
                    "event": {
                        "type": "source.command_port_changed",
                        "payload": {
                            "outcome": "fail",
                            "failure_reason_code": "soak_injected_source_dispatch_failure",
                        },
                    },
                }
            )

        if slot in restart_slots:
            timeline.append({"at": delivery_at, "event": {"type": "runtime.restart"}})
            reported_source_state = "disabled" if slot == failure_slot else reported_source_state

        if slot in source_slots:
            if slot not in restart_slots:
                reported_source_state = "enabled" if reported_source_state == "disabled" else "disabled"
            source_observed_at = delivery_at - timedelta(minutes=1 + rng.randrange(3))
            timeline.append(
                {
                    "at": delivery_at,
                    "event": {
                        "type": "source.reported_state_changed",
                        "payload": {
                            "state": reported_source_state,
                            "observed_at": source_observed_at,
                            "transition_at": source_observed_at - timedelta(minutes=1),
                        },
                    },
                }
            )

        observation_delay = timedelta(minutes=rng.choice((0, 0, 0, 1, 2, 3)))
        observed_at = max(last_temperature_observed_at, delivery_at - observation_delay)
        if slot in unavailable_slots:
            timeline.append(
                {
                    "at": delivery_at,
                    "event": {
                        "type": "sensor.availability_changed",
                        "subject": "soak_temperature",
                        "payload": {
                            "availability": "unavailable",
                            "observed_at": observed_at,
                        },
                    },
                }
            )
            sensor_available = False
        elif not sensor_available:
            timeline.append(
                {
                    "at": delivery_at,
                    "event": {
                        "type": "sensor.availability_changed",
                        "subject": "soak_temperature",
                        "payload": {
                            "availability": "available",
                            "value": temperature,
                            "observed_at": observed_at,
                        },
                    },
                }
            )
            sensor_available = True
            last_temperature_observed_at = observed_at
        else:
            if slot == failure_slot:
                temperature = 18.5
            timeline.append(
                {
                    "at": delivery_at,
                    "event": {
                        "type": "sensor.temperature_observed",
                        "subject": "soak_temperature",
                        "payload": {"value": temperature, "observed_at": observed_at},
                    },
                }
            )
            last_temperature_observed_at = observed_at

        if slot % checkpoint_stride == 0 or slot == slot_count:
            timeline.append({"at": delivery_at, "event": {"type": "simulation.checkpoint"}})

    timeline.append(
        {
            "at": configuration.start_at + configuration.virtual_duration,
            "event": {"type": "runtime.stop"},
        }
    )
    if len(timeline) > HEATING_SOAK_MAX_TIMELINE_EVENTS:
        raise ValueError(f"generated timeline has {len(timeline)} events; limit is {HEATING_SOAK_MAX_TIMELINE_EVENTS}")
    return Scenario.from_mapping(
        {
            "schema_version": 1,
            "scenario_id": f"heating_soak_seed_{configuration.seed}",
            "name": f"Deterministic heating soak seed {configuration.seed}",
            "description": "Bounded external observations and lifecycle changes; no building physics.",
            "tags": ["heating", "shadow-soak", f"seed-{configuration.seed}"],
            "module": "heating",
            "module_contract_version": 1,
            "start_at": configuration.start_at,
            "configuration": {
                "zone_id": "soak_zone",
                "zone_name": "Soak zone",
                "sensor_id": "soak_temperature",
                "sensor_name": "Soak temperature",
                "target_temperature": 21.0,
                "primary_measurement_max_age": "30m",
                "max_future_skew": "1m",
                "indeterminate_grace_period": "5m",
                "indeterminate_timeout_action": "disable_heating",
                "heating_turn_on_differential": 0.2,
                "heating_turn_off_differential": 0.2,
                "heat_demand_confirmation_duration": "0s",
                "minimum_heating_on_time": "2m",
                "minimum_heating_off_time": "2m",
            },
            "initial_state": {
                "zone_temperature": 19.5,
                "zone_temperature_observed_at": configuration.start_at,
                "source_reported_state": "disabled",
                "source_reported_observed_at": configuration.start_at,
                "source_transition_at": configuration.start_at - timedelta(minutes=15),
            },
            "timeline": timeline,
            "expectations": [{"type": "run.no_unhandled_error"}],
        }
    )


def _select_unavailable_slots(
    rng: random.Random,
    slot_count: int,
    restart_slots: set[int],
) -> set[int]:
    candidates = list(range(3, slot_count - 1))
    rng.shuffle(candidates)
    selected: set[int] = set()
    target_count = max(2, min(8, slot_count // 30))
    for slot in candidates:
        if slot in restart_slots or slot + 1 in restart_slots or slot - 1 in restart_slots:
            continue
        if any(abs(slot - existing) <= 1 for existing in selected):
            continue
        selected.add(slot)
        if len(selected) == target_count:
            break
    return selected


def _next_external_temperature(current: float, slot: int, rng: random.Random) -> float:
    """Generate explicit observations; this is an input pattern, not physics."""

    cycle = slot % 48
    trend = -0.12 if cycle < 12 else (0.2 if cycle < 30 else -0.15)
    jitter = rng.choice((-0.05, 0.0, 0.0, 0.05))
    return round(min(22.2, max(18.0, current + trend + jitter)), 2)


def _check_invariants(
    scenario: Scenario,
    report: SimulationReport,
    configuration: HeatingSoakConfiguration,
) -> tuple[tuple[str, ...], dict[str, int]]:
    failures: list[str] = []
    if report.outcome is not SimulationOutcome.PASSED:
        failures.append(f"simulation_outcome_{report.outcome.value}")
    if len(scenario.timeline) > HEATING_SOAK_MAX_TIMELINE_EVENTS:
        failures.append("timeline_event_limit_exceeded")
    if scenario.timeline[-1].delivery_at - scenario.start_at > configuration.virtual_duration:
        failures.append("scenario_duration_limit_exceeded")
    if any(
        later.delivery_at < earlier.delivery_at
        for earlier, later in zip(scenario.timeline, scenario.timeline[1:], strict=False)
    ):
        failures.append("scenario_timeline_moved_backwards")

    delivered = tuple(record.delivered_at for record in report.records if record.delivered_at is not None)
    if any(later < earlier for earlier, later in zip(delivered, delivered[1:], strict=False)):
        failures.append("virtual_delivery_time_moved_backwards")
    if any(
        record.origin is not RuntimeOrigin.SHADOW_SIMULATION or record.mode is not SimulationMode.SCENARIO
        for record in report.records
    ):
        failures.append("non_shadow_output_detected")

    commands = tuple(record for record in report.records if record.kind == "command.source")
    forbidden_command_fields = {"reported_state", "physical_state", "observed_state"}
    if any(forbidden_command_fields.intersection(record.payload) for record in commands):
        failures.append("command_fabricated_reported_state")
    explicit_source_inputs = 1 + sum(item.event.type == "source.reported_state_changed" for item in scenario.timeline)
    captured_source_inputs = sum(record.kind == "initial.source_reported_state" for record in report.records) + sum(
        record.kind == "timeline.event" and record.payload.get("event_type") == "source.reported_state_changed"
        for record in report.records
    )
    if report.outcome is SimulationOutcome.PASSED and captured_source_inputs != explicit_source_inputs:
        failures.append("reported_source_input_was_inferred_or_lost")

    valid_runtime_statuses = {item.value for item in RuntimeProcessingStatus} | {
        item.value for item in HeatDemandEvaluationStatus
    }
    if any(
        record.payload.get("status") not in valid_runtime_statuses
        for record in report.records
        if record.kind == "runtime.result"
    ):
        failures.append("runtime_result_structurally_invalid")
    failures.extend(_check_successful_correction_waits_for_new_evidence(report))
    failures.extend(_check_recovery_holds(report))
    anomaly_failures, anomaly_counts = _check_anomaly_lifecycle(report)
    failures.extend(anomaly_failures)
    if any("timeline_livelock" in error for error in report.errors):
        failures.append("scheduler_livelock")
    return tuple(dict.fromkeys(failures)), anomaly_counts


def _check_successful_correction_waits_for_new_evidence(report: SimulationReport) -> tuple[str, ...]:
    source_evidence_generation = 0
    previous_command: tuple[str, str, int] | None = None
    for record in report.records:
        if record.kind == "initial.source_reported_state" or (
            record.kind == "timeline.event" and record.payload.get("event_type") == "source.reported_state_changed"
        ):
            source_evidence_generation += 1
            continue
        if record.kind != "command.source":
            continue
        command = (
            str(record.payload.get("action")),
            str(record.payload.get("dispatch_outcome")),
            source_evidence_generation,
        )
        if (
            previous_command is not None
            and previous_command[0] == command[0]
            and previous_command[1] == "dispatched"
            and previous_command[2] == command[2]
        ):
            return ("successful_source_correction_repeated_without_new_evidence",)
        previous_command = command
    return ()


def _check_recovery_holds(report: SimulationReport) -> tuple[str, ...]:
    failures: list[str] = []
    records = report.records
    startup_indexes = tuple(
        index
        for index, record in enumerate(records)
        if record.kind == "timeline.event" and record.payload.get("event_type") in {"runtime.start", "runtime.restart"}
    )
    for position, start_index in enumerate(startup_indexes):
        end_index = startup_indexes[position + 1] if position + 1 < len(startup_indexes) else len(records)
        segment = records[start_index:end_index]
        has_source_input = any(
            record.kind == "initial.source_reported_state"
            or (record.kind == "timeline.event" and record.payload.get("event_type") == "source.reported_state_changed")
            for record in segment
        )
        has_temperature_input = any(
            record.kind == "initial.temperature"
            or (
                record.kind == "timeline.event"
                and record.payload.get("event_type") in {"sensor.temperature_observed", "sensor.availability_changed"}
            )
            for record in segment
        )
        held = any(
            record.kind == "operational_event" and record.payload.get("event_code") == "corrective_action_held"
            for record in segment
        )
        if has_source_input and has_temperature_input and not held:
            failures.append(f"recovery_hold_missing_after_startup_{position}")
    return tuple(failures)


def _check_anomaly_lifecycle(report: SimulationReport) -> tuple[tuple[str, ...], dict[str, int]]:
    states: dict[str, str] = {}
    counts = {value: 0 for value in _ANOMALY_CODES.values()}
    failures: list[str] = []
    for record in report.records:
        if record.kind != "operational_event":
            continue
        event_code = record.payload.get("event_code")
        lifecycle = _ANOMALY_CODES.get(str(event_code))
        if lifecycle is None:
            continue
        counts[lifecycle] += 1
        anomaly_id = record.payload.get("activity_id")
        if not isinstance(anomaly_id, str) or not anomaly_id:
            failures.append("anomaly_transition_missing_identity")
            continue
        previous = states.get(anomaly_id)
        if lifecycle == "started":
            if previous is not None:
                failures.append(f"duplicate_anomaly_start:{anomaly_id}")
            states[anomaly_id] = "active"
        elif previous != "active":
            failures.append(f"impossible_anomaly_{lifecycle}:{anomaly_id}")
        elif lifecycle in {"cleared", "observation_ended"}:
            states[anomaly_id] = lifecycle
    return tuple(failures), counts
