from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationStatus,
    HeatDemandEvaluationTrigger,
)
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingStatus,
    TemperatureNoDecisionReason,
)
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
        scheduled_failure_sink=RecordingScheduledFailureSink(),
        max_future_skew=timedelta(0),
        indeterminate_grace_period=grace,
        indeterminate_timeout_action=timeout_action,
    )
    return runtime, configured_clock, configured_scheduler, configured_port


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
    assert result.status is RuntimeProcessingStatus.COMMAND_EXECUTED
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


def test_actionable_timed_out_uncertainty_maps_safety_execution_and_suppression():
    runtime, clock, _, port = create_runtime(
        zone_names=("living_room", "bedroom"),
    )
    runtime.start()
    clock.current_time = NOW + GRACE
    current = measurement(23, timestamp=clock.current_time)

    first = runtime.process_temperature(current)
    second = runtime.process_temperature(current)

    assert first.status is RuntimeProcessingStatus.SAFETY_COMMAND_EXECUTED
    assert first.heat_demand_evaluation.status is HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED
    assert second.status is RuntimeProcessingStatus.SAFETY_COMMAND_SUPPRESSED
    assert second.heat_demand_evaluation.status is HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED
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
