from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.failsafe_runtime import FailsafeRuntime
from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationStatus,
    HeatDemandEvaluationTrigger,
)
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingStatus,
    TemperatureNoDecisionReason,
)
from controlel.application.runtime.runtime_supervisor import RuntimeSupervisor
from controlel.application.services.demand_arbitrator import IdentityDemandArbitrator
from controlel.application.services.heat_demand_safety_policy import (
    HeatDemandClockRegressionError,
)
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.decisions.decision import Decision
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.entities.zone import Zone
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.operating_mode import OperatingMode, SafeHeatingProfile
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
MAX_AGE = timedelta(minutes=5)
GRACE = timedelta(minutes=2)


class MutableClock:
    def __init__(self, current_time: datetime = NOW):
        self.current_time = current_time
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.current_time


class ManualTask:
    def __init__(
        self,
        when: datetime,
        callback: Callable[[], None],
        cancel_error: Exception | None = None,
    ):
        self.when = when
        self.callback = callback
        self.cancel_error = cancel_error
        self.cancelled = False
        self.fired = False
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancelled = True

    def invoke(self) -> None:
        self.fired = True
        self.callback()


class ManualScheduler:
    def __init__(self):
        self.tasks: list[ManualTask] = []
        self.schedule_error: Exception | None = None
        self.next_cancel_error: Exception | None = None

    def schedule_at(
        self,
        when: datetime,
        callback: Callable[[], None],
    ) -> ManualTask:
        if self.schedule_error is not None:
            raise self.schedule_error
        task = ManualTask(when, callback, self.next_cancel_error)
        self.next_cancel_error = None
        self.tasks.append(task)
        return task

    @property
    def active(self) -> list[ManualTask]:
        return [task for task in self.tasks if not task.cancelled and not task.fired]


class RecordingScheduledFailureSink:
    def __init__(self):
        self.failures = []

    def report(self, failure) -> None:
        self.failures.append(failure)


class RecordingHeatSource:
    def __init__(self):
        self.commands: list[HeatSourceCommand] = []
        self.error: Exception | None = None

    def execute(self, command: HeatSourceCommand) -> None:
        self.commands.append(command)
        if self.error is not None:
            raise self.error


class ObserveOnlyControlLoop:
    def process(self, context) -> DecisionCreatedEvent:
        return DecisionCreatedEvent(
            decision=Decision(
                sensor_id=context.sensor_id,
                zone_id=context.zone_id,
                observed_at=context.observed_at,
                action=DecisionAction.OBSERVE_ONLY,
            )
        )


def create_runtime(
    *,
    zone_names: tuple[str, ...] = ("living_room",),
    clock: MutableClock | None = None,
    scheduler: ManualScheduler | None = None,
    port: RecordingHeatSource | None = None,
    grace: timedelta = GRACE,
    timeout_action: HeatingAction = HeatingAction.DISABLE_HEATING,
    turn_on_differential: float = 0.0,
    turn_off_differential: float = 0.0,
    confirmation_duration: timedelta = timedelta(0),
    minimum_on: timedelta = timedelta(0),
    minimum_off: timedelta = timedelta(0),
    demand_arbitrator=None,
    scheduled_failure_sink=None,
) -> tuple[ControlRuntime, MutableClock, ManualScheduler, RecordingHeatSource]:
    configured_clock = clock or MutableClock()
    configured_scheduler = scheduler or ManualScheduler()
    configured_port = port or RecordingHeatSource()
    sensors = SensorRepository()
    zones = ZoneRepository()
    for name in zone_names:
        sensor_id = SensorId(value=f"{name}_temperature")
        zone_id = ZoneId(value=name)
        sensors.add(Sensor(sensor_id=sensor_id, zone_id=zone_id, name=name))
        zones.add(
            Zone(
                zone_id=zone_id,
                primary_sensor_id=sensor_id,
                primary_measurement_max_age=MAX_AGE,
                name=name,
                target_temperature=Temperature(22),
            )
        )
    runtime = ControlRuntime(
        sensor_repository=sensors,
        zone_repository=zones,
        heat_source_port=configured_port,
        clock=configured_clock,
        scheduler=configured_scheduler,
        scheduled_failure_sink=scheduled_failure_sink or RecordingScheduledFailureSink(),
        max_future_skew=timedelta(0),
        indeterminate_grace_period=grace,
        indeterminate_timeout_action=timeout_action,
        heating_turn_on_differential=turn_on_differential,
        heating_turn_off_differential=turn_off_differential,
        heat_demand_confirmation_duration=confirmation_duration,
        minimum_heating_on_time=minimum_on,
        minimum_heating_off_time=minimum_off,
        demand_arbitrator=demand_arbitrator,
    )
    return runtime, configured_clock, configured_scheduler, configured_port


class ForceNoHeatArbitrator:
    def __init__(self) -> None:
        self.received = []

    def resolve(self, aggregate_demand):
        self.received.append(aggregate_demand)
        return aggregate_demand.model_copy(update={"status": BuildingHeatDemandStatus.NO_HEAT_REQUIRED})


def test_single_zone_runtime_is_differentially_equivalent_to_frozen_identity_seam() -> None:
    def exercise(demand_arbitrator=None):
        runtime, clock, scheduler, port = create_runtime(
            confirmation_duration=timedelta(minutes=2),
            demand_arbitrator=demand_arbitrator,
        )
        first = runtime.process_temperature(measurement(19))
        clock.current_time = NOW + timedelta(minutes=1)
        repeated = runtime.process_temperature(measurement(19, timestamp=clock.current_time))
        confirmation_deadline = runtime.zone_heat_demand_confirmation_state.confirmation_deadline
        clock.current_time = confirmation_deadline
        next(task for task in scheduler.active if task.when == confirmation_deadline).invoke()
        clock.current_time += timedelta(seconds=1)
        cleared = runtime.process_temperature(measurement(23, timestamp=clock.current_time))
        return (
            (first.status, repeated.status, cleared.status),
            tuple(command.action for command in port.commands),
            confirmation_deadline,
            runtime.source_control_state,
        )

    assert exercise() == exercise(IdentityDemandArbitrator())


def test_single_zone_source_timing_safety_and_deferred_state_match_identity_seam() -> None:
    def exercise(demand_arbitrator=None):
        runtime, clock, scheduler, port = create_runtime(
            minimum_on=timedelta(minutes=2),
            minimum_off=timedelta(minutes=2),
            demand_arbitrator=demand_arbitrator,
        )
        initial = runtime.process_temperature(measurement(23))
        clock.current_time = NOW + timedelta(minutes=1)
        deferred_enable = runtime.process_temperature(measurement(19, timestamp=clock.current_time))
        enable_deadline = runtime.source_control_state.deferred_deadline
        clock.current_time = enable_deadline
        next(task for task in scheduler.active if task.when == enable_deadline).invoke()
        clock.current_time = NOW + timedelta(minutes=3)
        deferred_disable = runtime.process_temperature(measurement(23, timestamp=clock.current_time))
        disable_deadline = runtime.source_control_state.deferred_deadline
        clock.current_time = disable_deadline
        next(task for task in scheduler.active if task.when == disable_deadline).invoke()

        safety_runtime, safety_clock, _, safety_port = create_runtime(
            grace=timedelta(0),
            demand_arbitrator=demand_arbitrator,
        )
        safety_runtime.process_temperature(measurement(19))
        safety_clock.current_time = NOW + MAX_AGE + datetime.resolution
        safety = safety_runtime.reevaluate_heat_demand()
        return (
            (initial.status, deferred_enable.status, deferred_disable.status),
            (enable_deadline, disable_deadline),
            tuple(command.action for command in port.commands),
            runtime.source_control_state,
            safety.status,
            tuple(command.action for command in safety_port.commands),
            safety_runtime.source_control_state,
        )

    assert exercise() == exercise(IdentityDemandArbitrator())


def measurement(
    value: float,
    *,
    sensor: str = "living_room_temperature",
    timestamp: datetime = NOW,
) -> Measurement:
    return Measurement(
        sensor_id=SensorId(value=sensor),
        value=Temperature(value),
        timestamp=timestamp,
    )


def test_confirmation_deadline_is_owned_by_serial_runtime_scheduler() -> None:
    runtime, clock, scheduler, port = create_runtime(confirmation_duration=timedelta(minutes=2))

    pending = runtime.process_temperature(measurement(19))
    confirmation_task = scheduler.active[0]

    assert pending.heat_demand_evaluation.building_heat_demand.status is (BuildingHeatDemandStatus.NO_HEAT_REQUIRED)
    assert confirmation_task.when == NOW + timedelta(minutes=2)
    assert [command.action for command in port.commands] == [HeatingAction.DISABLE_HEATING]

    clock.current_time = confirmation_task.when
    confirmation_task.invoke()

    assert runtime.zone_heat_demand_confirmation_state.confirmed_demand is (BuildingHeatDemandStatus.HEAT_REQUIRED)
    assert [command.action for command in port.commands] == [
        HeatingAction.DISABLE_HEATING,
        HeatingAction.ENABLE_HEATING,
    ]


def test_hysteresis_enable_threshold_equality_starts_confirmation() -> None:
    runtime, clock, scheduler, _ = create_runtime(
        turn_on_differential=0.3,
        turn_off_differential=0.1,
        confirmation_duration=timedelta(minutes=2),
    )
    runtime.process_temperature(measurement(22.2))
    clock.current_time += timedelta(seconds=1)

    pending = runtime.process_temperature(measurement(21.7, timestamp=clock.current_time))

    assert pending.heat_demand_evaluation.hysteresis_assessment.state.demand.value == "heat_required"
    assert pending.heat_demand_evaluation.confirmation_assessment.state.phase.value == "confirmation_pending"
    assert scheduler.active[0].when == clock.current_time + timedelta(minutes=2)


def test_startup_inside_hysteresis_deadband_uses_raw_no_heat_without_confirmation() -> None:
    runtime, _, scheduler, _ = create_runtime(
        turn_on_differential=0.3,
        turn_off_differential=0.1,
        confirmation_duration=timedelta(minutes=2),
    )

    result = runtime.process_temperature(measurement(22.0))

    assert result.heat_demand_evaluation.hysteresis_assessment.state.demand.value == "no_heat_required"
    assert result.heat_demand_evaluation.confirmation_assessment.state.phase.value == "no_heat_required"
    assert result.heat_demand_evaluation.confirmation_assessment.state.confirmation_deadline is None
    assert [task.when for task in scheduler.active] == [NOW + MAX_AGE + datetime.resolution]


def test_unchanged_confirmation_is_temporally_refreshed_across_stale_and_grace_deadlines() -> None:
    runtime, clock, scheduler, port = create_runtime(
        grace=timedelta(minutes=15),
        confirmation_duration=timedelta(minutes=2),
    )
    initial = runtime.process_temperature(measurement(23))
    stale_at = NOW + MAX_AGE + datetime.resolution

    assert initial.heat_demand_evaluation.confirmation_assessment.state.last_evaluated_at == NOW
    clock.current_time = stale_at
    next(task for task in scheduler.active if task.when == stale_at).invoke()

    refreshed = runtime.zone_heat_demand_confirmation_assessment
    grace_at = stale_at + timedelta(minutes=15)
    assert refreshed is not None
    assert refreshed.state.last_evaluated_at == stale_at
    assert runtime._stopped is False
    assert runtime.scheduled_failure_sink.failures == []
    assert next(task for task in scheduler.active if task.when == grace_at)

    clock.current_time = grace_at
    next(task for task in scheduler.active if task.when == grace_at).invoke()

    assert runtime.zone_heat_demand_confirmation_assessment.state.last_evaluated_at == grace_at
    assert runtime._stopped is False
    assert runtime.scheduled_failure_sink.failures == []
    assert [command.action for command in port.commands] == [HeatingAction.DISABLE_HEATING]


def test_unchanged_confirmation_is_temporally_refreshed_at_source_control_deadline() -> None:
    runtime, clock, scheduler, port = create_runtime(
        confirmation_duration=timedelta(0),
        minimum_off=timedelta(minutes=4),
    )
    runtime.process_temperature(measurement(23))
    clock.current_time = NOW + timedelta(minutes=1)
    deferred = runtime.process_temperature(measurement(19, timestamp=clock.current_time))
    source_deadline = deferred.heat_demand_evaluation.next_evaluation_at

    clock.current_time = source_deadline
    next(task for task in scheduler.active if task.when == source_deadline).invoke()

    assert runtime.zone_heat_demand_confirmation_assessment.state.last_evaluated_at == source_deadline
    assert runtime.scheduled_failure_sink.failures == []
    assert [command.action for command in port.commands] == [
        HeatingAction.DISABLE_HEATING,
        HeatingAction.ENABLE_HEATING,
    ]


def test_multi_zone_unchanged_confirmations_share_scheduled_evaluation_time() -> None:
    runtime, clock, scheduler, _ = create_runtime(
        zone_names=("living_room", "bedroom"),
        grace=timedelta(minutes=15),
        confirmation_duration=timedelta(minutes=2),
    )
    runtime.process_temperature(measurement(23))
    runtime.process_temperature(measurement(23, sensor="bedroom_temperature"))
    stale_at = NOW + MAX_AGE + datetime.resolution

    clock.current_time = stale_at
    next(task for task in scheduler.active if task.when == stale_at).invoke()

    assert {
        assessment.state.last_evaluated_at for assessment in runtime.zone_heat_demand_confirmation_assessments.values()
    } == {stale_at}
    assert runtime.scheduled_failure_sink.failures == []


def test_scheduled_control_runtime_fatal_automatically_hands_source_protection_to_failsafe() -> None:
    class FailingAfterInitialEvaluation:
        calls = 0

        def resolve(self, aggregate_demand):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("scheduled runtime failed")
            return aggregate_demand

    clock, scheduler, source = MutableClock(), ManualScheduler(), RecordingHeatSource()

    def create_failsafe(port):
        return FailsafeRuntime(
            port,
            SafeHeatingProfile(21, 0.3, 0.1, SensorId("fallback")),
            minimum_on_time=timedelta(minutes=10),
            minimum_off_time=timedelta(minutes=5),
        )

    supervisor = RuntimeSupervisor(source, clock, scheduler=scheduler, failsafe_factory=create_failsafe)
    runtime, _, _, _ = create_runtime(
        clock=clock,
        scheduler=scheduler,
        port=supervisor.normal_port(),
        minimum_on=timedelta(minutes=10),
        minimum_off=timedelta(minutes=5),
        demand_arbitrator=FailingAfterInitialEvaluation(),
        scheduled_failure_sink=supervisor.scheduled_failure_sink(),
    )
    supervisor.attach_normal_runtime(runtime)
    runtime.process_temperature(measurement(19))
    stale = scheduler.active[0]

    clock.current_time = stale.when
    stale.invoke()

    assert supervisor.state.failsafe_mode is OperatingMode.EMERGENCY_OFF
    assert supervisor._failsafe.source_control_state.last_successful_enable_dispatch == NOW
    assert [item.action for item in source.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]


def test_restart_with_changed_duration_starts_one_fresh_confirmation_interval() -> None:
    first_runtime, first_clock, first_scheduler, first_port = create_runtime(
        confirmation_duration=timedelta(minutes=2),
    )
    first_runtime.process_temperature(measurement(19))
    stale_task = first_scheduler.active[0]
    first_runtime.stop()
    first_commands = list(first_port.commands)
    first_clock.current_time = stale_task.when
    stale_task.invoke()

    restart_clock = MutableClock(NOW + timedelta(seconds=30))
    restarted, _, restart_scheduler, _ = create_runtime(
        clock=restart_clock,
        confirmation_duration=timedelta(minutes=3),
    )
    pending = restarted.process_temperature(
        measurement(19, timestamp=restart_clock.current_time),
    )

    assert stale_task.cancelled is True
    assert first_port.commands == first_commands
    assert pending.heat_demand_evaluation.confirmation_assessment.state.confirmation_started_at == (
        restart_clock.current_time
    )
    assert pending.heat_demand_evaluation.confirmation_assessment.state.confirmation_deadline == (
        restart_clock.current_time + timedelta(minutes=3)
    )
    assert len(restart_scheduler.active) == 1


def test_transient_demand_is_cancelled_without_source_enable_or_lockout() -> None:
    runtime, clock, scheduler, port = create_runtime(
        confirmation_duration=timedelta(minutes=2),
        minimum_off=timedelta(minutes=5),
    )
    runtime.process_temperature(measurement(19))
    stale_confirmation = scheduler.active[0]
    clock.current_time = NOW + timedelta(minutes=1)

    runtime.process_temperature(measurement(23, timestamp=clock.current_time))
    commands_before_stale_callback = list(port.commands)
    stale_confirmation.invoke()

    assert stale_confirmation.cancelled is True
    assert port.commands == commands_before_stale_callback
    assert all(command.action is not HeatingAction.ENABLE_HEATING for command in port.commands)
    assert runtime.source_control_state.deferred_command is None


def test_confirmed_zone_demand_then_waits_for_independent_minimum_off() -> None:
    runtime, clock, scheduler, port = create_runtime(
        confirmation_duration=timedelta(minutes=2),
        minimum_off=timedelta(minutes=5),
    )
    runtime.process_temperature(measurement(23))
    clock.current_time = NOW + timedelta(seconds=1)
    runtime.process_temperature(measurement(19, timestamp=clock.current_time))
    confirmation_task = scheduler.active[0]
    clock.current_time = confirmation_task.when

    confirmation_task.invoke()

    assert runtime.zone_heat_demand_confirmation_state.confirmed_demand is (BuildingHeatDemandStatus.HEAT_REQUIRED)
    assert runtime.source_control_state.deferred_command is (HeatingAction.ENABLE_HEATING)
    assert runtime.source_control_state.next_reevaluation_deadline == (NOW + timedelta(minutes=5))
    assert [command.action for command in port.commands] == [HeatingAction.DISABLE_HEATING]


def test_arbitrator_receives_only_confirmed_zone_demand() -> None:
    arbitrator = ForceNoHeatArbitrator()
    runtime, clock, scheduler, _ = create_runtime(
        confirmation_duration=timedelta(minutes=2),
        demand_arbitrator=arbitrator,
    )

    runtime.process_temperature(measurement(19))
    assert arbitrator.received[-1].status is BuildingHeatDemandStatus.NO_HEAT_REQUIRED
    assert arbitrator.received[-1].eligible_demands[0].requires_heat is False

    confirmation_task = scheduler.active[0]
    clock.current_time = confirmation_task.when
    confirmation_task.invoke()

    assert arbitrator.received[-1].status is BuildingHeatDemandStatus.HEAT_REQUIRED
    assert arbitrator.received[-1].eligible_demands[0].requires_heat is True


def test_stop_and_fatal_reject_confirmation_callback() -> None:
    for terminal in ("stop", "fatal"):
        runtime, clock, scheduler, port = create_runtime(confirmation_duration=timedelta(minutes=2))
        runtime.process_temperature(measurement(19))
        task = scheduler.active[0]
        commands_before = list(port.commands)
        if terminal == "stop":
            runtime.stop()
        else:
            runtime.fatal_shutdown(None, NOW + timedelta(seconds=1))
            commands_before = list(port.commands)
        clock.current_time = task.when

        task.invoke()

        assert task.cancelled is True
        assert port.commands == commands_before


def test_indeterminate_measurement_invalidates_pending_callback_and_starts_grace() -> None:
    runtime, _, scheduler, port = create_runtime(confirmation_duration=timedelta(minutes=2))
    runtime.process_temperature(measurement(19))
    stale_confirmation = scheduler.active[0]

    result = runtime.mark_measurement_indeterminate()

    assert stale_confirmation.cancelled is True
    assert scheduler.active != [stale_confirmation]
    assert result.status is HeatDemandEvaluationStatus.INDETERMINATE_GRACE
    assert runtime.zone_heat_demand_confirmation_state.last_reason.value == (
        "heat_demand_confirmation_cancelled_measurement_indeterminate"
    )
    assert all(command.action is not HeatingAction.ENABLE_HEATING for command in port.commands)


def test_already_confirmed_demand_uses_existing_safety_grace_when_indeterminate() -> None:
    runtime, clock, scheduler, port = create_runtime(confirmation_duration=timedelta(minutes=2))
    runtime.process_temperature(measurement(19))
    task = scheduler.active[0]
    clock.current_time = task.when
    task.invoke()

    clock.current_time += timedelta(seconds=1)
    result = runtime.mark_measurement_indeterminate()

    assert result.status is HeatDemandEvaluationStatus.INDETERMINATE_GRACE
    assert result.safety_assessment.state.last_determinate_status is (BuildingHeatDemandStatus.HEAT_REQUIRED)
    assert runtime.zone_heat_demand_confirmation_state.confirmed_demand is (BuildingHeatDemandStatus.HEAT_REQUIRED)
    assert port.commands[-1].action is HeatingAction.ENABLE_HEATING


def test_constructor_has_no_clock_schedule_command_or_state_side_effects():
    runtime, clock, scheduler, port = create_runtime()

    assert clock.calls == 0
    assert scheduler.tasks == []
    assert port.commands == []
    assert runtime.heat_demand_safety_state_store.get() is None


def test_positive_startup_grace_and_repeated_start_keep_period_and_timer():
    runtime, clock, scheduler, port = create_runtime()

    first = runtime.start()
    second = runtime.start()

    assert first.trigger is HeatDemandEvaluationTrigger.STARTUP
    assert first.status is HeatDemandEvaluationStatus.INDETERMINATE_GRACE
    assert first.safety_assessment.state.indeterminate_since == NOW
    assert first.next_evaluation_at == NOW + GRACE
    assert second.safety_assessment.state.indeterminate_since == NOW
    assert len(scheduler.tasks) == 1
    assert scheduler.active == scheduler.tasks
    assert port.commands == []
    assert clock.calls == 2


@pytest.mark.parametrize("timeout_action", list(HeatingAction))
def test_zero_grace_startup_executes_then_suppresses_explicit_timeout_action(timeout_action):
    runtime, _, scheduler, port = create_runtime(
        grace=timedelta(0),
        timeout_action=timeout_action,
    )

    first = runtime.start()
    second = runtime.start()

    assert first.status is HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED
    assert second.status is HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED
    assert first.command.action is timeout_action
    assert len(port.commands) == 1
    assert scheduler.tasks == []


def test_manual_reevaluation_uses_retained_state_and_can_reach_timeout():
    runtime, clock, scheduler, port = create_runtime()
    runtime.start()
    clock.current_time = NOW + GRACE

    result = runtime.reevaluate_heat_demand()

    assert result.trigger is HeatDemandEvaluationTrigger.MANUAL
    assert result.status is HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED
    assert result.command.action is HeatingAction.DISABLE_HEATING
    assert scheduler.tasks[0].cancelled is True
    assert scheduler.active == []
    assert len(port.commands) == 1


def test_actionable_demand_replaces_startup_timer_and_unchanged_deadline_is_kept():
    runtime, clock, scheduler, _ = create_runtime()
    runtime.start()
    startup_task = scheduler.tasks[0]

    first = runtime.process_temperature(measurement(19))
    expiry_task = scheduler.tasks[-1]
    second = runtime.process_temperature(measurement(19))

    assert first.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert second.status is RuntimeProcessingStatus.COMMAND_SUPPRESSED
    assert startup_task.cancelled is True
    assert expiry_task.when == NOW + MAX_AGE + datetime.resolution
    assert len(scheduler.tasks) == 2
    assert scheduler.active == [expiry_task]
    assert clock.calls == 7


def test_changed_demand_deadline_replaces_timer_and_stale_callback_is_no_op():
    runtime, clock, scheduler, port = create_runtime()
    runtime.process_temperature(measurement(19))
    old_task = scheduler.tasks[0]
    state_before = runtime.heat_demand_safety_state_store.get()
    clock.current_time = NOW + timedelta(minutes=1)

    runtime.process_temperature(
        measurement(19, timestamp=clock.current_time),
    )
    new_task = scheduler.tasks[-1]
    commands_before = list(port.commands)
    old_task.invoke()

    assert old_task.cancelled is True
    assert new_task.when == clock.current_time + MAX_AGE + datetime.resolution
    assert scheduler.active == [new_task]
    assert runtime.heat_demand_safety_state_store.get() is not state_before
    assert port.commands == commands_before


def test_replacement_schedule_failure_preserves_old_trigger_and_prevents_command():
    runtime, _, scheduler, port = create_runtime()
    runtime.start()
    old_task = scheduler.tasks[0]
    error = RuntimeError("schedule failed")
    scheduler.schedule_error = error

    with pytest.raises(RuntimeError) as raised:
        runtime.process_temperature(measurement(19))

    assert raised.value is error
    assert scheduler.active == [old_task]
    assert runtime.zone_demand_store.get(ZoneId(value="living_room")).requires_heat is True
    assert (
        runtime.heat_demand_safety_state_store.get().last_determinate_status is BuildingHeatDemandStatus.HEAT_REQUIRED
    )
    assert port.commands == []
    assert runtime.heat_source_state_store.get() is None


def test_old_handle_cancel_failure_propagates_with_new_timer_active_and_old_stale():
    scheduler = ManualScheduler()
    cancel_error = RuntimeError("cancel failed")
    scheduler.next_cancel_error = cancel_error
    runtime, _, _, port = create_runtime(scheduler=scheduler)
    runtime.start()
    old_task = scheduler.tasks[0]

    with pytest.raises(RuntimeError) as raised:
        runtime.process_temperature(measurement(19))

    assert raised.value is cancel_error
    assert len(scheduler.tasks) == 2
    new_task = scheduler.tasks[1]
    commands_before = list(port.commands)
    old_task.invoke()
    assert port.commands == commands_before
    assert runtime._scheduled_deadline == new_task.when


def test_premature_callback_rearms_without_evaluation_or_state_change():
    runtime, clock, scheduler, port = create_runtime()
    runtime.start()
    task = scheduler.tasks[0]
    state = runtime.heat_demand_safety_state_store.get()
    calls_before = clock.calls

    task.invoke()

    assert runtime.heat_demand_safety_state_store.get() is state
    assert port.commands == []
    assert len(scheduler.tasks) == 2
    assert scheduler.tasks[-1].when == task.when
    assert clock.calls == calls_before + 1


def test_duplicate_and_cancelled_callbacks_are_harmless():
    runtime, clock, scheduler, port = create_runtime()
    runtime.process_temperature(measurement(19))
    task = scheduler.tasks[0]
    clock.current_time = task.when

    task.invoke()
    state = runtime.heat_demand_safety_state_store.get()
    commands = list(port.commands)
    task.invoke()

    assert runtime.heat_demand_safety_state_store.get() is state
    assert port.commands == commands

    current = scheduler.active[0]
    clock.current_time += timedelta(seconds=1)
    runtime.process_temperature(measurement(19, timestamp=clock.current_time))
    current.invoke()
    assert port.commands == commands


def test_enabled_last_true_expiry_begins_grace_at_expiry_plus_one_microsecond():
    runtime, clock, scheduler, port = create_runtime()
    runtime.process_temperature(measurement(19))
    expiry_task = scheduler.active[0]
    clock.current_time = expiry_task.when

    expiry_task.invoke()

    state = runtime.heat_demand_safety_state_store.get()
    assert state.indeterminate_since == expiry_task.when
    assert port.commands[0].action is HeatingAction.ENABLE_HEATING
    assert len(port.commands) == 1
    assert scheduler.active[0].when == expiry_task.when + GRACE


def test_disabled_source_becoming_incomplete_uses_same_grace_without_immediate_action():
    runtime, clock, scheduler, port = create_runtime()
    runtime.process_temperature(measurement(23))
    expiry_task = scheduler.active[0]
    clock.current_time = expiry_task.when

    expiry_task.invoke()

    assert runtime.heat_demand_safety_state_store.get().indeterminate_since == expiry_task.when
    assert [command.action for command in port.commands] == [HeatingAction.DISABLE_HEATING]


def test_late_expiry_callback_consumes_grace_and_executes_safety_action_without_decision():
    runtime, clock, scheduler, port = create_runtime()
    decisions: list[DecisionCreatedEvent] = []
    runtime.event_bus.subscribe(DecisionCreatedEvent, decisions.append)
    runtime.process_temperature(measurement(19))
    expiry_task = scheduler.active[0]
    clock.current_time = expiry_task.when + GRACE

    expiry_task.invoke()

    state = runtime.heat_demand_safety_state_store.get()
    assert state.indeterminate_since == expiry_task.when
    assert [command.action for command in port.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]
    assert len(decisions) == 1


def test_remaining_fresh_true_overrides_expired_uncertainty_and_reschedules():
    runtime, clock, scheduler, port = create_runtime(zone_names=("living_room", "bedroom"))
    runtime.process_temperature(measurement(19))
    clock.current_time = NOW + timedelta(minutes=1)
    runtime.process_temperature(measurement(19, sensor="bedroom_temperature", timestamp=clock.current_time))
    first_expiry = min(task.when for task in scheduler.active)
    clock.current_time = first_expiry

    scheduler.active[0].invoke()

    assert (
        runtime.heat_demand_safety_state_store.get().last_determinate_status is BuildingHeatDemandStatus.HEAT_REQUIRED
    )
    assert len(port.commands) == 1
    assert scheduler.active[0].when == NOW + timedelta(minutes=6) + datetime.resolution


def test_all_fresh_false_disables_but_false_expiry_becomes_indeterminate():
    runtime, clock, scheduler, port = create_runtime(zone_names=("living_room", "bedroom"))
    runtime.process_temperature(measurement(23))
    result = runtime.process_temperature(
        measurement(23, sensor="bedroom_temperature"),
    )
    assert result.status is RuntimeProcessingStatus.COMMAND_SUPPRESSED
    assert port.commands[-1].action is HeatingAction.DISABLE_HEATING

    expiry_task = scheduler.active[0]
    clock.current_time = expiry_task.when
    expiry_task.invoke()

    assert runtime.heat_demand_safety_state_store.get().indeterminate_since == expiry_task.when
    assert len(port.commands) == 1


def test_demand_arriving_during_startup_grace_clears_period_and_replaces_timer():
    runtime, clock, scheduler, port = create_runtime()
    runtime.start()
    clock.current_time = NOW + timedelta(minutes=1)

    result = runtime.process_temperature(measurement(19, timestamp=clock.current_time))

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert runtime.heat_demand_safety_state_store.get().indeterminate_since is None
    assert scheduler.tasks[0].cancelled is True
    assert scheduler.active[0].when == clock.current_time + MAX_AGE + datetime.resolution
    assert port.commands[-1].action is HeatingAction.ENABLE_HEATING


def test_sensor_recovery_after_safety_disable_enables_source():
    runtime, clock, _, port = create_runtime(grace=timedelta(0))
    runtime.start()
    clock.current_time = NOW + timedelta(seconds=1)

    result = runtime.process_temperature(measurement(19, timestamp=clock.current_time))

    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert [command.action for command in port.commands] == [
        HeatingAction.DISABLE_HEATING,
        HeatingAction.ENABLE_HEATING,
    ]


def test_valid_no_heat_ends_startup_uncertainty_even_with_other_zone_missing():
    runtime, clock, _, port = create_runtime(
        zone_names=("living_room", "bedroom"),
    )
    runtime.start()
    clock.current_time = NOW + GRACE
    current = measurement(23, timestamp=clock.current_time)

    first = runtime.process_temperature(current)
    second = runtime.process_temperature(current)

    assert first.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert first.heat_demand_evaluation.status is HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED
    assert second.status is RuntimeProcessingStatus.COMMAND_SUPPRESSED
    assert second.heat_demand_evaluation.status is HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED
    assert [command.action for command in port.commands] == [HeatingAction.DISABLE_HEATING]


def test_timeout_failure_retains_state_and_later_manual_retry_executes():
    runtime, clock, scheduler, port = create_runtime()
    failure_sink = runtime.scheduled_failure_sink
    runtime.start()
    timeout_task = scheduler.active[0]
    clock.current_time = timeout_task.when
    error = RuntimeError("source failed")
    port.error = error

    timeout_task.invoke()

    assert failure_sink.failures[0].error is error
    assert failure_sink.failures[0].scheduled_for == timeout_task.when
    assert runtime.heat_demand_safety_state_store.get().indeterminate_since == NOW
    assert runtime.heat_source_state_store.get() is None
    assert scheduler.active == []

    port.error = None
    result = runtime.reevaluate_heat_demand()
    assert result.status is HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED
    assert len(port.commands) == 2


def test_source_failure_keeps_demand_safety_and_installed_deadline():
    runtime, _, scheduler, port = create_runtime()
    error = RuntimeError("source failed")
    port.error = error

    with pytest.raises(RuntimeError):
        runtime.process_temperature(measurement(19))

    assert runtime.zone_demand_store.get(ZoneId(value="living_room")).requires_heat
    assert (
        runtime.heat_demand_safety_state_store.get().last_determinate_status is BuildingHeatDemandStatus.HEAT_REQUIRED
    )
    assert len(scheduler.active) == 1
    assert runtime.heat_source_state_store.get() is None
    assert runtime.source_control_state.last_dispatch_timestamp is None
    assert runtime.source_control_state.minimum_on_deadline is None
    assert runtime.source_control_state.minimum_off_deadline is None


def test_no_decision_and_observe_only_do_not_reset_safety_state_or_timer():
    runtime, _, scheduler, _ = create_runtime()
    runtime.start()
    state = runtime.heat_demand_safety_state_store.get()
    task = scheduler.active[0]

    rejected = runtime.process_temperature(measurement(19, timestamp=NOW + timedelta(seconds=1)))
    assert rejected.reason is TemperatureNoDecisionReason.TIMESTAMP_ADMISSION_REJECTED
    assert runtime.heat_demand_safety_state_store.get() is state
    assert scheduler.active == [task]

    runtime.temperature_handler.control_loop = ObserveOnlyControlLoop()
    observed = runtime.process_temperature(measurement(19))
    assert observed.status is RuntimeProcessingStatus.DECISION_WITHOUT_COMMAND
    assert runtime.heat_demand_safety_state_store.get() is state
    assert scheduler.active == [task]


def test_completed_evaluation_after_backward_clock_change_raises_regression():
    runtime, clock, _, _ = create_runtime()
    runtime.start()
    clock.current_time = NOW - datetime.resolution

    with pytest.raises(HeatDemandClockRegressionError):
        runtime.reevaluate_heat_demand()


def test_runtime_distinguishes_raw_demand_from_hysteresis_deadband_hold():
    runtime, clock, _, port = create_runtime(
        turn_on_differential=0.3,
        turn_off_differential=0.1,
    )

    enabled = runtime.process_temperature(measurement(21.5))
    clock.current_time += timedelta(minutes=1)
    held = runtime.process_temperature(measurement(22.0, timestamp=clock.current_time))
    clock.current_time += timedelta(minutes=1)
    disabled = runtime.process_temperature(measurement(22.1, timestamp=clock.current_time))

    assert enabled.heat_demand_evaluation.hysteresis_assessment.state.demand.value == "heat_required"
    assert held.decision_event.decision.action.value == "disable_heating"
    assert held.heat_demand_evaluation.hysteresis_assessment.raw_requires_heat is False
    assert held.heat_demand_evaluation.hysteresis_assessment.state.demand.value == "heat_required"
    assert held.status is RuntimeProcessingStatus.COMMAND_SUPPRESSED
    assert disabled.status is RuntimeProcessingStatus.COMMAND_EXECUTED
    assert [command.action for command in port.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]


def test_source_control_consumes_arbitrated_aggregate_not_zone_state():
    arbitrator = ForceNoHeatArbitrator()
    runtime, _, _, port = create_runtime(demand_arbitrator=arbitrator)

    result = runtime.process_temperature(measurement(19))

    assert len(arbitrator.received) == 1
    assert arbitrator.received[0].status is BuildingHeatDemandStatus.HEAT_REQUIRED
    assert result.heat_demand_evaluation.building_heat_demand.status is (BuildingHeatDemandStatus.NO_HEAT_REQUIRED)
    assert [command.action for command in port.commands] == [HeatingAction.DISABLE_HEATING]


def test_runtime_reevaluates_current_demand_at_minimum_on_deadline():
    runtime, clock, scheduler, port = create_runtime(minimum_on=timedelta(minutes=2))
    runtime.process_temperature(measurement(19))
    clock.current_time += timedelta(minutes=1)

    deferred = runtime.process_temperature(measurement(23, timestamp=clock.current_time))
    deadline_task = scheduler.active[0]

    assert deferred.status is RuntimeProcessingStatus.COMMAND_DEFERRED
    assert deadline_task.when == NOW + timedelta(minutes=2)
    assert len(port.commands) == 1

    clock.current_time = deadline_task.when
    deadline_task.invoke()

    assert [command.action for command in port.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]
    assert runtime.source_control_state.deferred_command is None


def test_runtime_cancels_deferred_transition_and_rejects_stale_callback():
    runtime, clock, scheduler, port = create_runtime(minimum_on=timedelta(minutes=2))
    runtime.process_temperature(measurement(19))
    clock.current_time += timedelta(minutes=1)
    runtime.process_temperature(measurement(23, timestamp=clock.current_time))
    stale_task = scheduler.active[0]
    clock.current_time += timedelta(seconds=30)

    cancelled = runtime.process_temperature(measurement(19, timestamp=clock.current_time))
    commands_before = list(port.commands)
    stale_task.invoke()

    assert cancelled.status is RuntimeProcessingStatus.COMMAND_SUPPRESSED
    assert stale_task.cancelled is True
    assert runtime.source_control_state.deferred_command is None
    assert port.commands == commands_before


def test_two_zones_keep_independent_confirmation_deadlines_and_cancellation() -> None:
    runtime, clock, scheduler, port = create_runtime(
        zone_names=("zone_a", "zone_b"),
        confirmation_duration=timedelta(minutes=2),
    )
    runtime.process_temperature(measurement(19, sensor="zone_a_temperature"))
    zone_a = ZoneId(value="zone_a")
    zone_b = ZoneId(value="zone_b")
    a_deadline = runtime.zone_heat_demand_confirmation_states[zone_a].confirmation_deadline
    a_confirmation_state = runtime.zone_heat_demand_confirmation_states[zone_a]
    a_started_at = runtime.zone_heat_demand_confirmation_states[zone_a].confirmation_started_at
    a_hysteresis = runtime.temperature_hysteresis_states[zone_a]
    source_disable_at = runtime.source_control_state.last_successful_disable_dispatch
    source_enable_boundary = runtime.source_control_state.earliest_next_enable_time
    schedule_generation = runtime._schedule_generation

    clock.current_time = NOW + timedelta(seconds=30)
    runtime.process_temperature(measurement(19, sensor="zone_b_temperature", timestamp=clock.current_time))

    assert runtime.zone_heat_demand_confirmation_states[zone_a].confirmation_deadline == a_deadline
    assert runtime.zone_heat_demand_confirmation_states[zone_a].confirmation_started_at == a_started_at
    assert runtime.zone_heat_demand_confirmation_states[zone_a] is not a_confirmation_state
    assert runtime.zone_heat_demand_confirmation_states[zone_a].last_evaluated_at == clock.current_time
    assert runtime.temperature_hysteresis_states[zone_a] is a_hysteresis
    assert runtime.source_control_state.last_successful_disable_dispatch == source_disable_at
    assert runtime.source_control_state.earliest_next_enable_time == source_enable_boundary
    assert runtime._schedule_generation == schedule_generation
    assert runtime.zone_heat_demand_confirmation_states[zone_b].confirmation_deadline == (
        clock.current_time + timedelta(minutes=2)
    )

    clock.current_time = a_deadline
    scheduler.active[0].invoke()
    assert runtime.zone_heat_demand_confirmation_states[zone_a].phase.value == "heat_required_confirmed"
    assert runtime.zone_heat_demand_confirmation_states[zone_b].phase.value == "confirmation_pending"
    assert [command.action for command in port.commands] == [
        HeatingAction.DISABLE_HEATING,
        HeatingAction.ENABLE_HEATING,
    ]

    clock.current_time += timedelta(seconds=1)
    cancelled = runtime.process_temperature(measurement(23, sensor="zone_b_temperature", timestamp=clock.current_time))
    assert cancelled.heat_demand_evaluation.building_heat_demand.status is (BuildingHeatDemandStatus.HEAT_REQUIRED)
    assert runtime.zone_heat_demand_confirmation_states[zone_b].phase.value == "no_heat_required"
    assert len(port.commands) == 2


def test_multi_zone_stale_confirmation_callback_cannot_resurrect_demand() -> None:
    runtime, clock, scheduler, port = create_runtime(
        zone_names=("zone_a", "zone_b"),
        confirmation_duration=timedelta(minutes=2),
    )
    runtime.process_temperature(measurement(19, sensor="zone_a_temperature"))
    stale = scheduler.active[0]
    clock.current_time = NOW + timedelta(seconds=30)
    runtime.process_temperature(measurement(19, sensor="zone_b_temperature", timestamp=clock.current_time))
    clock.current_time += timedelta(seconds=1)
    runtime.process_temperature(measurement(23, sensor="zone_a_temperature", timestamp=clock.current_time))
    commands_before = list(port.commands)
    clock.current_time = stale.when
    stale.invoke()

    assert stale.cancelled is True
    assert port.commands == commands_before
    assert runtime.zone_heat_demand_confirmation_states[ZoneId(value="zone_a")].phase.value == ("no_heat_required")


def test_multi_zone_deferred_enable_survives_requesting_zone_change() -> None:
    runtime, clock, scheduler, port = create_runtime(
        zone_names=("zone_a", "zone_b"),
        minimum_off=timedelta(minutes=5),
    )
    runtime.process_temperature(measurement(23, sensor="zone_a_temperature"))
    runtime.process_temperature(measurement(23, sensor="zone_b_temperature"))
    clock.current_time = NOW + timedelta(minutes=1)
    runtime.process_temperature(measurement(19, sensor="zone_a_temperature", timestamp=clock.current_time))
    deferred_since = runtime.source_control_state.deferred_since
    deferred_deadline = runtime.source_control_state.deferred_deadline
    successful_disable_at = runtime.source_control_state.last_successful_disable_dispatch
    schedule_generation = runtime._schedule_generation
    clock.current_time += timedelta(minutes=1)
    runtime.process_temperature(measurement(19, sensor="zone_b_temperature", timestamp=clock.current_time))
    clock.current_time += timedelta(minutes=1)
    runtime.process_temperature(measurement(23, sensor="zone_a_temperature", timestamp=clock.current_time))

    assert runtime.source_control_state.deferred_command is HeatingAction.ENABLE_HEATING
    assert runtime.source_control_state.deferred_since == deferred_since
    assert runtime.source_control_state.deferred_deadline == deferred_deadline
    assert runtime.source_control_state.last_successful_disable_dispatch == successful_disable_at
    assert runtime._schedule_generation == schedule_generation
    assert [command.action for command in port.commands] == [HeatingAction.DISABLE_HEATING]
    deadline = runtime.source_control_state.next_reevaluation_deadline
    clock.current_time = deadline
    next(task for task in scheduler.active if task.when == deadline).invoke()
    assert [command.action for command in port.commands] == [
        HeatingAction.DISABLE_HEATING,
        HeatingAction.ENABLE_HEATING,
    ]


def test_multi_zone_deferred_enable_cancels_when_all_requests_clear() -> None:
    runtime, clock, scheduler, port = create_runtime(
        zone_names=("zone_a", "zone_b"),
        minimum_off=timedelta(minutes=5),
    )
    runtime.process_temperature(measurement(23, sensor="zone_a_temperature"))
    clock.current_time = NOW + timedelta(minutes=1)
    runtime.process_temperature(measurement(19, sensor="zone_a_temperature", timestamp=clock.current_time))
    stale = next(task for task in scheduler.active if task.when == NOW + timedelta(minutes=5))
    clock.current_time += timedelta(minutes=1)
    runtime.process_temperature(measurement(23, sensor="zone_a_temperature", timestamp=clock.current_time))

    assert runtime.source_control_state.deferred_command is None
    commands_before = list(port.commands)
    clock.current_time = stale.when
    stale.invoke()
    assert port.commands == commands_before


def test_multi_zone_minimum_on_applies_only_when_final_request_clears() -> None:
    runtime, clock, scheduler, port = create_runtime(
        zone_names=("zone_a", "zone_b"),
        minimum_on=timedelta(minutes=5),
    )
    runtime.process_temperature(measurement(19, sensor="zone_a_temperature"))
    runtime.process_temperature(measurement(19, sensor="zone_b_temperature"))
    clock.current_time = NOW + timedelta(minutes=1)
    runtime.process_temperature(measurement(23, sensor="zone_a_temperature", timestamp=clock.current_time))
    final = runtime.process_temperature(measurement(23, sensor="zone_b_temperature", timestamp=clock.current_time))

    assert final.status is RuntimeProcessingStatus.COMMAND_DEFERRED
    assert runtime.source_control_state.deferred_command is HeatingAction.DISABLE_HEATING
    assert [command.action for command in port.commands] == [HeatingAction.ENABLE_HEATING]
    deadline = runtime.source_control_state.next_reevaluation_deadline
    clock.current_time = deadline
    next(task for task in scheduler.active if task.when == deadline).invoke()
    assert [command.action for command in port.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]


def test_runtime_safety_disable_bypasses_minimum_on_lockout():
    runtime, clock, _, port = create_runtime(
        grace=timedelta(0),
        minimum_on=timedelta(minutes=10),
    )
    runtime.process_temperature(measurement(19))
    clock.current_time = NOW + MAX_AGE + timedelta(seconds=1)

    result = runtime.reevaluate_heat_demand()

    assert result.status is HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED
    assert result.source_control_assessment.safety_bypassed_lockout is True
    assert [command.action for command in port.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]


def test_fatal_shutdown_bypasses_minimum_on_and_invalidates_deferred_callback():
    runtime, clock, scheduler, port = create_runtime(minimum_on=timedelta(minutes=2))
    runtime.process_temperature(measurement(19))
    clock.current_time += timedelta(minutes=1)
    runtime.process_temperature(measurement(23, timestamp=clock.current_time))
    stale_task = scheduler.active[0]

    result = runtime.fatal_shutdown(None, clock.current_time)
    commands_after_fatal = list(port.commands)
    stale_task.invoke()

    assert result.emergency_disable_attempted is True
    assert result.emergency_disable_outcome.value == "fatal_shutdown_disable_dispatched"
    assert [command.action for command in port.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]
    assert port.commands == commands_after_fatal
    assert runtime.source_control_state.phase.value == "fatal_error"
    assert runtime.source_control_state.minimum_on_deadline is None
    assert runtime.source_control_state.minimum_off_deadline is None
    assert runtime.source_control_state.deferred_command is None
    assert runtime.source_control_state.next_reevaluation_deadline is None


def test_fatal_enable_failure_attempts_one_emergency_disable_without_history():
    error = RuntimeError("enable failed")
    port = RecordingHeatSource()
    port.error = error
    runtime, clock, _, _ = create_runtime(port=port)

    with pytest.raises(RuntimeError, match="enable failed"):
        runtime.process_temperature(measurement(19))
    assert runtime.source_control_state.last_dispatch_timestamp is None

    port.error = None
    result = runtime.fatal_shutdown(
        HeatingAction.ENABLE_HEATING,
        clock.current_time,
    )

    assert result.emergency_disable_outcome.value == "fatal_shutdown_disable_dispatched"
    assert [command.action for command in port.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]
    assert runtime.source_control_state.last_dispatch_timestamp is None
    assert runtime.source_control_state.minimum_off_deadline is None


def test_fatal_disable_failure_does_not_recursively_dispatch_disable():
    port = RecordingHeatSource()
    runtime, clock, _, _ = create_runtime(port=port)
    runtime.process_temperature(measurement(19))
    clock.current_time += timedelta(minutes=1)
    port.error = RuntimeError("disable failed")

    with pytest.raises(RuntimeError, match="disable failed"):
        runtime.process_temperature(measurement(23, timestamp=clock.current_time))

    result = runtime.fatal_shutdown(
        HeatingAction.DISABLE_HEATING,
        clock.current_time,
    )

    assert result.emergency_disable_attempted is False
    assert result.emergency_disable_outcome.value == "fatal_shutdown_disable_skipped_already_failed"
    assert [command.action for command in port.commands] == [
        HeatingAction.ENABLE_HEATING,
        HeatingAction.DISABLE_HEATING,
    ]


def test_failed_emergency_disable_is_attempted_once_without_retry_or_lockout():
    port = RecordingHeatSource()
    port.error = RuntimeError("emergency disable failed")
    runtime, clock, _, _ = create_runtime(port=port)

    first = runtime.fatal_shutdown(None, clock.current_time)
    second = runtime.fatal_shutdown(None, clock.current_time)

    assert first is second
    assert first.emergency_disable_attempted is True
    assert first.emergency_disable_outcome.value == "fatal_shutdown_disable_failed"
    assert first.emergency_failure_type == "RuntimeError"
    assert [command.action for command in port.commands] == [
        HeatingAction.DISABLE_HEATING,
    ]
    assert runtime.source_control_state.minimum_off_deadline is None
