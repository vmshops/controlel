from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Event, Thread

import pytest

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.runtime_lifecycle import (
    RuntimeReentrancyError,
    RuntimeStoppedError,
)
from controlel.application.services.heat_demand_safety_policy import (
    HeatDemandClockRegressionError,
)
from controlel.application.state.heat_demand_safety_state import (
    HeatDemandSafetyState,
)
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.entities.zone import Zone
from controlel.domain.events.temperature_measured_event import TemperatureMeasuredEvent
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
    def __init__(self):
        self.current_time = NOW
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.current_time


class ManualTask:
    def __init__(self, when: datetime, callback: Callable[[], None]):
        self.when = when
        self.callback = callback
        self.cancel_calls = 0
        self.cancel_error: Exception | None = None
        self.cancel_hook: Callable[[], None] | None = None

    def cancel(self) -> None:
        self.cancel_calls += 1
        if self.cancel_hook is not None:
            self.cancel_hook()
        if self.cancel_error is not None:
            raise self.cancel_error

    def invoke(self) -> None:
        self.callback()


class ManualScheduler:
    def __init__(self):
        self.tasks: list[ManualTask] = []
        self.schedule_error: Exception | None = None
        self.invoke_synchronously = False

    def schedule_at(
        self,
        when: datetime,
        callback: Callable[[], None],
    ) -> ManualTask:
        if self.schedule_error is not None:
            raise self.schedule_error
        task = ManualTask(when, callback)
        self.tasks.append(task)
        if self.invoke_synchronously:
            task.invoke()
        return task


class RecordingFailureSink:
    def __init__(self):
        self.failures = []
        self.on_report: Callable[[], None] | None = None
        self.error: Exception | None = None

    def report(self, failure) -> None:
        self.failures.append(failure)
        if self.on_report is not None:
            self.on_report()
        if self.error is not None:
            raise self.error


class RecordingHeatSource:
    def __init__(self):
        self.commands: list[HeatSourceCommand] = []
        self.error: Exception | None = None

    def execute(self, command: HeatSourceCommand) -> None:
        self.commands.append(command)
        if self.error is not None:
            raise self.error


def create_runtime(
    *,
    scheduler: ManualScheduler | None = None,
    sink: RecordingFailureSink | None = None,
    port: RecordingHeatSource | None = None,
) -> tuple[
    ControlRuntime,
    MutableClock,
    ManualScheduler,
    RecordingFailureSink,
    RecordingHeatSource,
]:
    clock = MutableClock()
    configured_scheduler = scheduler or ManualScheduler()
    configured_sink = sink or RecordingFailureSink()
    configured_port = port or RecordingHeatSource()
    sensor_id = SensorId(value="living_room_temperature")
    zone_id = ZoneId(value="living_room")
    sensors = SensorRepository()
    sensors.add(Sensor(sensor_id=sensor_id, zone_id=zone_id, name="living room"))
    zones = ZoneRepository()
    zones.add(
        Zone(
            zone_id=zone_id,
            primary_sensor_id=sensor_id,
            primary_measurement_max_age=MAX_AGE,
            name="living room",
            target_temperature=Temperature(22),
        )
    )
    runtime = ControlRuntime(
        sensor_repository=sensors,
        zone_repository=zones,
        heat_source_port=configured_port,
        clock=clock,
        scheduler=configured_scheduler,
        scheduled_failure_sink=configured_sink,
        max_future_skew=timedelta(0),
        indeterminate_grace_period=GRACE,
        indeterminate_timeout_action=HeatingAction.DISABLE_HEATING,
    )
    return runtime, clock, configured_scheduler, configured_sink, configured_port


def measurement(
    value: float = 19,
    timestamp: datetime = NOW,
) -> Measurement:
    return Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(value),
        timestamp=timestamp,
    )


def test_constructor_is_open_and_side_effect_free():
    runtime, clock, scheduler, sink, port = create_runtime()

    assert runtime._stopped is False
    assert runtime._active_operation is None
    assert runtime._execution_lock.locked() is False
    assert clock.calls == 0
    assert scheduler.tasks == []
    assert sink.failures == []
    assert port.commands == []


def test_reentrancy_error_exposes_both_stable_operation_names():
    error = RuntimeReentrancyError(
        active_operation="start",
        attempted_operation="stop",
    )

    assert error.active_operation == "start"
    assert error.attempted_operation == "stop"
    assert "start" in str(error)
    assert "stop" in str(error)


def test_stop_before_start_is_terminal_idempotent_and_sends_no_command():
    runtime, _, _, _, port = create_runtime()

    assert runtime.stop() is None
    assert runtime.stop() is None

    assert runtime._stopped is True
    assert port.commands == []
    for operation in (
        runtime.start,
        lambda: runtime.process_temperature(measurement()),
        runtime.reevaluate_heat_demand,
    ):
        with pytest.raises(RuntimeStoppedError, match="stopped"):
            operation()


@pytest.mark.parametrize("create_timer", ["grace", "eligibility"])
def test_stop_cancels_active_timer_after_invalidating_generation(create_timer):
    runtime, _, scheduler, sink, port = create_runtime()
    if create_timer == "grace":
        runtime.start()
    else:
        runtime.process_temperature(measurement())
    task = scheduler.tasks[-1]
    previous_generation = runtime._schedule_generation

    def assert_shutdown_order() -> None:
        assert runtime._stopped is True
        assert runtime._schedule_generation == previous_generation + 1
        assert runtime._scheduled_handle is None
        assert runtime._scheduled_deadline is None

    task.cancel_hook = assert_shutdown_order
    runtime.stop()
    task.invoke()

    assert task.cancel_calls == 1
    assert sink.failures == []
    assert len(port.commands) == (0 if create_timer == "grace" else 1)


def test_cancel_failure_leaves_runtime_stopped_and_repeated_stop_does_not_cancel_again():
    runtime, _, scheduler, _, _ = create_runtime()
    runtime.start()
    task = scheduler.tasks[0]
    error = RuntimeError("cancel failed")
    task.cancel_error = error

    with pytest.raises(RuntimeError) as raised:
        runtime.stop()

    assert raised.value is error
    assert runtime._stopped is True
    assert runtime._scheduled_handle is None
    assert runtime._scheduled_deadline is None
    assert runtime.stop() is None
    assert task.cancel_calls == 1


def test_observer_reentry_raises_before_nested_measurement_mutation():
    runtime, _, _, _, _ = create_runtime()
    nested = measurement(23, NOW + timedelta(seconds=1))
    errors = []

    def reenter(_event) -> None:
        try:
            runtime.process_temperature(nested)
        except RuntimeReentrancyError as error:
            errors.append(error)

    runtime.event_bus.subscribe(TemperatureMeasuredEvent, reenter)
    runtime.process_temperature(measurement())

    error = errors[0]
    assert error.active_operation == "process_temperature"
    assert error.attempted_operation == "process_temperature"
    assert "process_temperature" in str(error)
    assert runtime.state_store.get_latest(nested.sensor_id).timestamp == NOW


def test_overlapping_public_operations_fail_immediately_without_mutation():
    runtime, _, _, sink, _ = create_runtime()
    entered = Event()
    release = Event()
    outer_errors = []

    def block(_event) -> None:
        entered.set()
        assert release.wait(timeout=5)

    runtime.event_bus.subscribe(TemperatureMeasuredEvent, block)

    def run_outer() -> None:
        try:
            runtime.process_temperature(measurement())
        except Exception as error:
            outer_errors.append(error)

    thread = Thread(target=run_outer)
    thread.start()
    assert entered.wait(timeout=5)

    attempts = (
        ("process_temperature", lambda: runtime.process_temperature(measurement(23))),
        ("reevaluate_heat_demand", runtime.reevaluate_heat_demand),
        ("stop", runtime.stop),
    )
    for attempted_operation, operation in attempts:
        with pytest.raises(RuntimeReentrancyError) as raised:
            operation()
        assert raised.value.active_operation == "process_temperature"
        assert raised.value.attempted_operation == attempted_operation

    release.set()
    thread.join(timeout=5)
    assert thread.is_alive() is False
    assert outer_errors == []
    assert sink.failures == []
    assert runtime._stopped is False


def test_scheduled_callback_overlapping_processing_is_reported_without_consumption():
    runtime, clock, scheduler, sink, _ = create_runtime()
    runtime.start()
    task = scheduler.tasks[0]
    clock.current_time = task.when
    entered = Event()
    release = Event()

    def block(_event) -> None:
        entered.set()
        assert release.wait(timeout=5)

    runtime.event_bus.subscribe(TemperatureMeasuredEvent, block)
    thread = Thread(target=lambda: runtime.process_temperature(measurement(timestamp=clock.current_time)))
    thread.start()
    assert entered.wait(timeout=5)

    task.invoke()

    failure = sink.failures[0]
    assert isinstance(failure.error, RuntimeReentrancyError)
    assert failure.error.active_operation == "process_temperature"
    assert failure.error.attempted_operation == "scheduled_callback"
    assert runtime._scheduled_handle is task
    release.set()
    thread.join(timeout=5)
    assert thread.is_alive() is False


def test_non_compliant_synchronous_scheduler_callback_reports_reentrancy():
    scheduler = ManualScheduler()
    scheduler.invoke_synchronously = True
    runtime, _, _, sink, _ = create_runtime(scheduler=scheduler)

    runtime.start()

    failure = sink.failures[0]
    assert isinstance(failure.error, RuntimeReentrancyError)
    assert failure.error.active_operation == "start"
    assert failure.error.attempted_operation == "scheduled_callback"


def test_port_reentry_fails_outer_dispatch_without_recording_applied_state():
    runtime, _, _, _, port = create_runtime()

    def reenter(_command) -> None:
        runtime.reevaluate_heat_demand()

    original_execute = port.execute

    def execute(command) -> None:
        original_execute(command)
        reenter(command)

    port.execute = execute

    with pytest.raises(RuntimeReentrancyError) as raised:
        runtime.process_temperature(measurement())

    assert raised.value.active_operation == "process_temperature"
    assert raised.value.attempted_operation == "reevaluate_heat_demand"
    assert runtime.heat_source_state_store.get() is None


def test_overlapping_processing_allows_at_most_one_active_source_execution():
    runtime, _, _, _, port = create_runtime()
    entered = Event()
    release = Event()
    active = 0
    maximum_active = 0

    def execute(command) -> None:
        nonlocal active, maximum_active
        port.commands.append(command)
        active += 1
        maximum_active = max(maximum_active, active)
        entered.set()
        assert release.wait(timeout=5)
        active -= 1

    port.execute = execute
    outer_errors = []
    thread = Thread(
        target=lambda: _capture_error(
            lambda: runtime.process_temperature(measurement()),
            outer_errors,
        )
    )
    thread.start()
    assert entered.wait(timeout=5)

    with pytest.raises(RuntimeReentrancyError):
        runtime.process_temperature(measurement(23))

    release.set()
    thread.join(timeout=5)
    assert thread.is_alive() is False
    assert outer_errors == []
    assert maximum_active == 1
    assert len(port.commands) == 1


def _capture_error(operation: Callable[[], object], errors: list[Exception]) -> None:
    try:
        operation()
    except Exception as error:
        errors.append(error)


def test_scheduled_aggregation_and_clock_regression_failures_reach_exact_sink():
    runtime, clock, scheduler, sink, _ = create_runtime()
    runtime.start()
    task = scheduler.tasks[0]
    clock.current_time = task.when
    aggregation_error = RuntimeError("aggregation failed")

    def fail_aggregation():
        raise aggregation_error

    runtime.heat_demand_aggregator.evaluate = fail_aggregation
    task.invoke()

    assert sink.failures[0].error is aggregation_error
    assert sink.failures[0].scheduled_for == task.when

    runtime, clock, scheduler, sink, _ = create_runtime()
    runtime.start()
    task = scheduler.tasks[0]
    runtime.heat_demand_safety_state_store.save(
        HeatDemandSafetyState(
            indeterminate_since=NOW,
            last_evaluated_at=task.when + timedelta(seconds=1),
        )
    )
    clock.current_time = task.when
    task.invoke()

    assert isinstance(sink.failures[0].error, HeatDemandClockRegressionError)


def test_scheduled_configuration_failure_reaches_sink():
    runtime, clock, scheduler, sink, _ = create_runtime()
    runtime.start()
    task = scheduler.tasks[0]
    runtime.zone_demand_store.record(
        ZoneDemand(
            zone_id=ZoneId(value="living_room"),
            requires_heat=True,
            source_sensor_id=SensorId(value="wrong_sensor"),
            observed_at=NOW,
        )
    )
    clock.current_time = task.when

    task.invoke()

    assert "wrong_sensor" in str(sink.failures[0].error)


def test_scheduled_scheduler_and_source_failures_reach_sink():
    runtime, clock, scheduler, sink, port = create_runtime()
    runtime.process_temperature(measurement())
    expiry_task = scheduler.tasks[-1]
    clock.current_time = expiry_task.when
    schedule_error = RuntimeError("replacement failed")
    scheduler.schedule_error = schedule_error

    expiry_task.invoke()

    assert sink.failures[0].error is schedule_error

    runtime, clock, scheduler, sink, port = create_runtime()
    runtime.process_temperature(measurement())
    expiry_task = scheduler.tasks[-1]
    clock.current_time = expiry_task.when + GRACE
    source_error = RuntimeError("source failed")
    port.error = source_error

    expiry_task.invoke()

    assert sink.failures[0].error is source_error
    assert runtime.heat_source_state_store.get().applied_action is HeatingAction.ENABLE_HEATING


def test_scheduled_cancellation_failure_reaches_sink():
    runtime, clock, scheduler, sink, _ = create_runtime()
    runtime.start()
    task = scheduler.tasks[0]
    clock.current_time = task.when
    cancellation_error = RuntimeError("cancellation failed")

    def fail_replacement(_deadline) -> None:
        raise cancellation_error

    runtime._replace_scheduled_evaluation = fail_replacement
    task.invoke()

    assert sink.failures[0].error is cancellation_error


def test_failure_sink_runs_after_guard_release_and_may_stop_runtime():
    runtime, clock, scheduler, sink, _ = create_runtime()
    runtime.start()
    task = scheduler.tasks[0]
    clock.current_time = task.when
    error = RuntimeError("scheduled failure")

    def fail_aggregation():
        raise error

    runtime.heat_demand_aggregator.evaluate = fail_aggregation
    sink.on_report = runtime.stop
    task.invoke()

    assert sink.failures[0].error is error
    assert runtime._stopped is True
    assert runtime._execution_lock.locked() is False


def test_failure_sink_exception_escapes_callback_boundary():
    runtime, clock, scheduler, sink, _ = create_runtime()
    runtime.start()
    task = scheduler.tasks[0]
    clock.current_time = task.when
    runtime.heat_demand_aggregator.evaluate = lambda: (_ for _ in ()).throw(RuntimeError("scheduled failure"))
    sink_error = RuntimeError("sink failed")
    sink.error = sink_error

    with pytest.raises(RuntimeError) as raised:
        task.invoke()

    assert raised.value is sink_error


def test_stale_duplicate_and_stopped_callbacks_report_nothing():
    runtime, clock, scheduler, sink, _ = create_runtime()
    runtime.process_temperature(measurement())
    first = scheduler.tasks[0]
    clock.current_time = NOW + timedelta(minutes=1)
    runtime.process_temperature(measurement(timestamp=clock.current_time))
    replacement = scheduler.tasks[-1]

    first.invoke()
    runtime.stop()
    replacement.invoke()
    replacement.invoke()

    assert sink.failures == []


def test_synchronous_failure_propagates_without_using_scheduled_sink():
    runtime, _, _, sink, _ = create_runtime()
    error = RuntimeError("manual aggregation failed")
    runtime.heat_demand_aggregator.evaluate = lambda: (_ for _ in ()).throw(error)

    with pytest.raises(RuntimeError) as raised:
        runtime.reevaluate_heat_demand()

    assert raised.value is error
    assert sink.failures == []


def test_scheduled_base_exception_is_not_caught_or_reported():
    runtime, clock, scheduler, sink, _ = create_runtime()
    runtime.start()
    task = scheduler.tasks[0]
    clock.current_time = task.when

    def interrupt():
        raise KeyboardInterrupt

    runtime.heat_demand_aggregator.evaluate = interrupt
    with pytest.raises(KeyboardInterrupt):
        task.invoke()

    assert sink.failures == []
