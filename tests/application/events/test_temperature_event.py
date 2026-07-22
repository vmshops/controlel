from controlel.domain.events.temperature_measured_event import TemperatureMeasuredEvent
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature


def test_temperature_event_creation():
    measurement = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(20),
    )

    event = TemperatureMeasuredEvent(
        measurement=measurement,
    )

    assert event.event_type == "temperature_measured"
    assert event.measurement == measurement
