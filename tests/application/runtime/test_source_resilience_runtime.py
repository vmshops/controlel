from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationStatus,
)
from controlel.application.state.source_reconciliation_state import (
    SourceReconciliationStatus,
)
from controlel.application.state.source_recovery_state import SourceRecoveryStatus
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.entities.zone import Zone
from controlel.domain.heat_delivery import ObservationQuality
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.operating_mode import (
    OperatingMode,
    SafeHeatingProfile,
    SafeHeatingTemperatureEvidence,
)
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.source_control import (
    ReportedSourceEvidence,
    ReportedSourceState,
    SourceOwnership,
)
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
SENSOR_ID = SensorId("living_room_temperature")


class MutableClock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current


class ManualTask:
    def __init__(self, when: datetime, callback: Callable[[], None]) -> None:
        self.when = when
        self.callback = callback
        self.cancelled = False
        self.fired = False

    def cancel(self) -> None:
        self.cancelled = True

    def invoke(self) -> None:
        self.fired = True
        self.callback()


class ManualScheduler:
    def __init__(self) -> None:
        self.tasks: list[ManualTask] = []

    def schedule_at(self, when: datetime, callback: Callable[[], None]) -> ManualTask:
        task = ManualTask(when, callback)
        self.tasks.append(task)
        return task

    def task_at(self, when: datetime) -> ManualTask:
        return next(task for task in self.tasks if task.when == when and not task.cancelled)


class RecordingSource:
    def __init__(self) -> None:
        self.commands: list[HeatSourceCommand] = []
        self.failure: Exception | None = None

    def execute(self, command: HeatSourceCommand) -> None:
        self.commands.append(command)
        if self.failure is not None:
            raise self.failure


class FailureSink:
    def __init__(self) -> None:
        self.failures = []

    def report(self, failure) -> None:
        self.failures.append(failure)


def _runtime(
    *,
    ownership: SourceOwnership = SourceOwnership.CONTROLEL_OWNED,
    minimum_on: timedelta = timedelta(0),
    safe_profile: SafeHeatingProfile | None = None,
) -> tuple[ControlRuntime, MutableClock, ManualScheduler, RecordingSource]:
    sensors = SensorRepository()
    zones = ZoneRepository()
    sensors.add(Sensor(sensor_id=SENSOR_ID, zone_id=ZoneId("living_room"), name="Living room"))
    zones.add(
        Zone(
            zone_id=ZoneId("living_room"),
            primary_sensor_id=SENSOR_ID,
            primary_measurement_max_age=timedelta(hours=4),
            name="Living room",
            target_temperature=Temperature(22),
        )
    )
    clock = MutableClock()
    scheduler = ManualScheduler()
    source = RecordingSource()
    runtime = ControlRuntime(
        sensor_repository=sensors,
        zone_repository=zones,
        heat_source_port=source,
        clock=clock,
        scheduler=scheduler,
        scheduled_failure_sink=FailureSink(),
        max_future_skew=timedelta(0),
        indeterminate_grace_period=timedelta(hours=6),
        indeterminate_timeout_action=HeatingAction.DISABLE_HEATING,
        minimum_heating_on_time=minimum_on,
        source_ownership=ownership,
        safe_heating_profile=safe_profile,
    )
    return runtime, clock, scheduler, source


def _measurement(value: float, at: datetime) -> Measurement:
    return Measurement(sensor_id=SENSOR_ID, value=Temperature(value), timestamp=at)


def _report(
    state: ReportedSourceState,
    at: datetime,
    *,
    transition_at: datetime | None = None,
) -> ReportedSourceEvidence:
    return ReportedSourceEvidence(state=state, observed_at=at, transition_at=transition_at)


def test_external_on_no_heat_is_held_then_corrected_without_command_storm() -> None:
    runtime, clock, scheduler, source = _runtime()
    runtime.ingest_reported_source_state(_report(ReportedSourceState.ENABLED, NOW))

    held = runtime.process_temperature(_measurement(24, NOW)).heat_demand_evaluation

    assert held.status is HeatDemandEvaluationStatus.RESILIENCE_COMMAND_HELD
    assert source.commands == []
    diagnostics = runtime.source_resilience_diagnostics(now=NOW)
    assert diagnostics.desired_source_state == HeatingAction.DISABLE_HEATING.value
    assert diagnostics.reported_source_state == ReportedSourceState.ENABLED.value
    assert diagnostics.drift_detected is True
    assert diagnostics.corrective_action_blocked_reason == "unknown_transition_age_hold"
    deadline = NOW + timedelta(minutes=5)
    assert held.next_evaluation_at == deadline

    clock.current = deadline
    scheduler.task_at(deadline).invoke()
    assert [command.action for command in source.commands] == [HeatingAction.DISABLE_HEATING]
    assert runtime.source_reconciliation_state.status is SourceReconciliationStatus.CORRECTION_PENDING

    runtime.ingest_reported_source_state(_report(ReportedSourceState.ENABLED, deadline))
    assert len(source.commands) == 1

    agreed = runtime.ingest_reported_source_state(
        _report(ReportedSourceState.DISABLED, deadline + timedelta(seconds=1))
    )
    assert agreed.source_reconciliation_assessment.status is SourceReconciliationStatus.AGREED
    assert len(source.commands) == 1


def test_known_minimum_on_remains_authoritative_for_corrective_disable() -> None:
    runtime, clock, scheduler, source = _runtime(minimum_on=timedelta(minutes=10))
    runtime.process_temperature(_measurement(19, NOW))
    runtime.ingest_reported_source_state(_report(ReportedSourceState.ENABLED, NOW, transition_at=NOW))
    clock.current = NOW + timedelta(minutes=1)

    deferred = runtime.process_temperature(_measurement(24, clock.current)).heat_demand_evaluation

    assert deferred.status is HeatDemandEvaluationStatus.RESILIENCE_COMMAND_DEFERRED
    assert [command.action for command in source.commands] == [HeatingAction.ENABLE_HEATING]
    deadline = NOW + timedelta(minutes=10)
    clock.current = deadline
    scheduler.task_at(deadline).invoke()
    assert [command.action for command in source.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]


def test_failed_corrective_dispatch_is_retryable_only_after_retry_deadline() -> None:
    runtime, clock, scheduler, source = _runtime()
    runtime.ingest_reported_source_state(
        _report(ReportedSourceState.ENABLED, NOW, transition_at=NOW - timedelta(hours=1))
    )
    source.failure = RuntimeError("failed")
    with pytest.raises(RuntimeError, match="failed"):
        runtime.process_temperature(_measurement(24, NOW))
    assert len(source.commands) == 1

    source.failure = None
    runtime.ingest_reported_source_state(_report(ReportedSourceState.ENABLED, NOW))
    assert len(source.commands) == 1
    retry_at = NOW + timedelta(seconds=30)
    clock.current = retry_at
    scheduler.task_at(retry_at).invoke()
    assert len(source.commands) == 2


def test_external_ownership_diagnoses_but_does_not_issue_corrective_duplicate() -> None:
    runtime, _, _, source = _runtime(ownership=SourceOwnership.EXTERNAL)
    runtime.process_temperature(_measurement(24, NOW))
    runtime.ingest_reported_source_state(_report(ReportedSourceState.ENABLED, NOW))

    assert len(source.commands) == 1
    assert runtime.source_reconciliation_state.status is SourceReconciliationStatus.OBSERVED_EXTERNAL


def test_external_off_with_heat_demand_retries_enable_as_corrective_intent() -> None:
    runtime, _, _, source = _runtime()
    runtime.process_temperature(_measurement(19, NOW))

    result = runtime.ingest_reported_source_state(
        _report(
            ReportedSourceState.DISABLED,
            NOW,
            transition_at=NOW - timedelta(minutes=10),
        )
    )

    assert result.status is HeatDemandEvaluationStatus.RESILIENCE_COMMAND_EXECUTED
    assert [command.action for command in source.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.ENABLE_HEATING,
    ]


def test_recovery_with_reported_on_and_valid_heat_demand_does_not_toggle_source() -> None:
    runtime, _, _, source = _runtime()
    runtime.begin_source_recovery()
    runtime.ingest_reported_source_state(_report(ReportedSourceState.ENABLED, NOW))

    result = runtime.process_temperature(_measurement(19, NOW)).heat_demand_evaluation

    assert result.status is HeatDemandEvaluationStatus.RESILIENCE_COMMAND_SUPPRESSED
    assert runtime.source_recovery_state.status is SourceRecoveryStatus.COMPLETE
    assert source.commands == []
    assert runtime.source_control_state is None


def test_recovery_with_no_heat_and_reported_on_uses_unknown_age_hold() -> None:
    runtime, _, _, source = _runtime()
    runtime.begin_source_recovery()
    runtime.ingest_reported_source_state(_report(ReportedSourceState.ENABLED, NOW))

    result = runtime.process_temperature(_measurement(24, NOW)).heat_demand_evaluation

    assert result.status is HeatDemandEvaluationStatus.RESILIENCE_COMMAND_HELD
    assert result.next_evaluation_at == NOW + timedelta(minutes=5)
    assert source.commands == []


def test_recovery_with_reported_off_and_no_heat_does_not_toggle_source() -> None:
    runtime, _, _, source = _runtime()
    runtime.begin_source_recovery()
    runtime.ingest_reported_source_state(_report(ReportedSourceState.DISABLED, NOW))

    result = runtime.process_temperature(_measurement(24, NOW)).heat_demand_evaluation

    assert result.status is HeatDemandEvaluationStatus.RESILIENCE_COMMAND_SUPPRESSED
    assert source.commands == []


def test_recovery_with_reported_off_and_heat_uses_unknown_age_hold() -> None:
    runtime, _, _, source = _runtime()
    runtime.begin_source_recovery()
    runtime.ingest_reported_source_state(_report(ReportedSourceState.DISABLED, NOW))

    result = runtime.process_temperature(_measurement(19, NOW)).heat_demand_evaluation

    assert result.status is HeatDemandEvaluationStatus.RESILIENCE_COMMAND_HELD
    assert result.next_evaluation_at == NOW + timedelta(minutes=5)
    assert source.commands == []


def test_recovery_with_unknown_source_is_bounded_and_does_not_immediately_enable() -> None:
    runtime, clock, scheduler, source = _runtime()
    runtime.begin_source_recovery()

    held = runtime.process_temperature(_measurement(19, NOW)).heat_demand_evaluation
    assert held.status is HeatDemandEvaluationStatus.RESILIENCE_COMMAND_HELD
    assert source.commands == []

    deadline = NOW + timedelta(seconds=30)
    clock.current = deadline
    scheduler.task_at(deadline).invoke()
    assert [command.action for command in source.commands] == [HeatingAction.ENABLE_HEATING]


def test_emergency_off_uses_existing_safety_disable_bypass() -> None:
    runtime, clock, _, source = _runtime(minimum_on=timedelta(minutes=10))
    runtime.process_temperature(_measurement(19, NOW))
    runtime.ingest_reported_source_state(_report(ReportedSourceState.ENABLED, NOW))
    clock.current = NOW + timedelta(minutes=1)

    result = runtime.set_operating_mode(OperatingMode.EMERGENCY_OFF)

    assert result.status is HeatDemandEvaluationStatus.RESILIENCE_COMMAND_EXECUTED
    assert [command.action for command in source.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]
    assert runtime.source_control_state.safety_bypass_active is True
    clock.current += timedelta(seconds=1)
    runtime.ingest_reported_source_state(_report(ReportedSourceState.ENABLED, clock.current))
    assert len(source.commands) == 2


def test_manual_recovery_expiry_requests_disable_when_normal_demand_is_unknown() -> None:
    runtime, clock, scheduler, source = _runtime(ownership=SourceOwnership.EXTERNAL)
    activated = runtime.set_operating_mode(OperatingMode.MANUAL_RECOVERY_HEAT)
    deadline = activated.operating_mode_assessment.state.manual_recovery_deadline

    assert [command.action for command in source.commands] == [HeatingAction.ENABLE_HEATING]
    assert deadline == NOW + timedelta(hours=2)
    clock.current = deadline
    scheduler.task_at(deadline).invoke()
    assert [command.action for command in source.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]


def test_reload_cancellation_does_not_recreate_manual_deadline_or_toggle_immediately() -> None:
    runtime, _, _, source = _runtime()
    runtime.set_operating_mode(OperatingMode.MANUAL_RECOVERY_HEAT)

    recovery = runtime.cancel_manual_recovery_for_reload()

    assert recovery.status is SourceRecoveryStatus.WAITING
    assert runtime.operating_mode_state.manual_recovery_deadline is None
    assert len(source.commands) == 1


def test_reconstructed_runtime_records_manual_recovery_reload_cancellation_without_timer() -> None:
    runtime, _, _, source = _runtime()

    runtime.begin_source_recovery(manual_recovery_cancelled=True)

    assert runtime.operating_mode_state.mode is OperatingMode.NORMAL
    assert runtime.operating_mode_state.reason.value == "manual_recovery_cancelled_reload"
    assert runtime.operating_mode_state.manual_recovery_deadline is None
    assert source.commands == []


def test_repeated_recovery_with_legitimate_on_heat_never_oscillates() -> None:
    for _ in range(2):
        runtime, _, _, source = _runtime()
        runtime.begin_source_recovery()
        runtime.ingest_reported_source_state(_report(ReportedSourceState.ENABLED, NOW))
        runtime.process_temperature(_measurement(19, NOW))
        assert source.commands == []


def test_stale_reported_source_event_cannot_overwrite_newer_evidence() -> None:
    runtime, clock, _, _ = _runtime()
    clock.current = NOW + timedelta(minutes=1)
    runtime.ingest_reported_source_state(_report(ReportedSourceState.ENABLED, clock.current))

    with pytest.raises(ValueError, match="must not regress"):
        runtime.ingest_reported_source_state(_report(ReportedSourceState.DISABLED, NOW))

    assert runtime.reported_source_evidence.state is ReportedSourceState.ENABLED


def test_safe_heating_uses_separate_evidence_without_changing_zone_demand() -> None:
    profile = SafeHeatingProfile(
        room_target_temperature=19,
        turn_on_differential=1,
        turn_off_differential=1,
        preferred_sensor_id=SensorId("safe_room"),
    )
    runtime, _, _, source = _runtime(
        ownership=SourceOwnership.EXTERNAL,
        safe_profile=profile,
    )
    runtime.set_operating_mode(OperatingMode.SAFE_HEATING)

    result = runtime.ingest_safe_heating_temperature(
        SafeHeatingTemperatureEvidence(
            sensor_id=SensorId("safe_room"),
            value=17,
            quality=ObservationQuality.VALID,
            observed_at=NOW,
        )
    )

    assert result.status is HeatDemandEvaluationStatus.RESILIENCE_COMMAND_EXECUTED
    assert [command.action for command in source.commands] == [HeatingAction.ENABLE_HEATING]
    assert runtime.zone_demand_store.list_current() == []
