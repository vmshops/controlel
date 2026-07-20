from controlel.application.events.event_bus import EventBus
from controlel.domain.events.temperature_measured_event import (
    TemperatureMeasuredEvent,
)
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.temperature import Temperature


def test_event_bus_dispatches_event():
    called = False

    def handler(event):
        nonlocal called
        called = True

    bus = EventBus()

    bus.subscribe(
        TemperatureMeasuredEvent,
        handler,
    )

    event = TemperatureMeasuredEvent(
        measurement=Measurement(
            value=Temperature(20),
        )
    )

    bus.publish(event)

    assert called is True
