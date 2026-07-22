from controlel.application.events.event_bus import EventBus
from controlel.domain.events.temperature_measured_event import (
    TemperatureMeasuredEvent,
)
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature


def test_typed_event_notifies_subscriber_and_discards_return_value():
    received_events = []

    def handler(event):
        received_events.append(event)
        return "observer result"

    bus = EventBus()

    bus.subscribe(
        TemperatureMeasuredEvent,
        handler,
    )

    event = TemperatureMeasuredEvent(
        measurement=Measurement(
            sensor_id=SensorId(value="living_room_temperature"),
            value=Temperature(20),
        )
    )

    result = bus.publish(event)

    assert result is None
    assert received_events == [event]
