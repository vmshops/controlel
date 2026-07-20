from datetime import UTC, datetime

from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.temperature import Temperature


def test_measurement_creation():
    measurement = Measurement(
        value=Temperature(22.5),
        source="living_room_sensor",
    )

    assert measurement.value.value == 22.5
    assert measurement.source == "living_room_sensor"
    assert isinstance(measurement.timestamp, datetime)


def test_measurement_timestamp_is_utc():
    measurement = Measurement(
        value=Temperature(22.5),
        source="living_room_sensor",
    )

    assert measurement.timestamp.tzinfo == UTC
