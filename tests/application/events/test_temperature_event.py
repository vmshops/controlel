from controlel.domain.events.temperature_measured_event import TemperatureMeasuredEvent
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.temperature import Temperature


def test_temperature_event_creation():
    measurement = Measurement(
        value=Temperature(20),
    )

    event = TemperatureMeasuredEvent(
        measurement=measurement,
    )

    assert event.event_type == "temperature_measured"
    assert event.measurement == measurement
