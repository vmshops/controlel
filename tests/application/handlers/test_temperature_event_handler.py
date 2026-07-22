from datetime import UTC, datetime, timedelta

from controlel.application.handlers.temperature_event_handler import (
    TemperatureEventHandler,
)
from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.domain.events.temperature_measured_event import (
    TemperatureMeasuredEvent,
)
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature


class RecordingControlLoop:
    def __init__(self):
        self.contexts = []

    def process(self, context):
        self.contexts.append(context)
        return context


def create_event(
    value: float,
    timestamp: datetime | None = None,
) -> TemperatureMeasuredEvent:
    measurement = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(value),
        timestamp=timestamp or datetime.now(UTC),
    )
    return TemperatureMeasuredEvent(measurement=measurement)


def test_accepted_measurement_is_recorded():
    state_store = RuntimeStateStore()
    handler = TemperatureEventHandler(
        state_store=state_store,
        target_temperature=Temperature(22),
    )
    event = create_event(19)

    handler.handle(event)

    assert state_store.get_latest(event.measurement.sensor_id) == event.measurement


def test_stale_measurement_does_not_invoke_control_loop():
    state_store = RuntimeStateStore()
    newest_timestamp = datetime.now(UTC)
    newest_event = create_event(20, newest_timestamp)
    stale_event = create_event(19, newest_timestamp - timedelta(minutes=1))
    state_store.record(newest_event.measurement)
    control_loop = RecordingControlLoop()
    handler = TemperatureEventHandler(
        state_store=state_store,
        target_temperature=Temperature(22),
    )
    handler.control_loop = control_loop

    result = handler.handle(stale_event)

    assert result is None
    assert control_loop.contexts == []
    assert state_store.get_latest(newest_event.measurement.sensor_id) == (newest_event.measurement)


def test_injected_target_temperature_is_used():
    state_store = RuntimeStateStore()
    control_loop = RecordingControlLoop()
    handler = TemperatureEventHandler(
        state_store=state_store,
        target_temperature=Temperature(18),
    )
    handler.control_loop = control_loop

    handler.handle(create_event(19))

    assert control_loop.contexts[0].target_temperature == Temperature(18)


def test_accepted_measurement_preserves_decision_behavior():
    handler = TemperatureEventHandler(
        state_store=RuntimeStateStore(),
        target_temperature=Temperature(22),
    )

    result = handler.handle(create_event(19))

    assert result.decision.action == "enable_heating"
