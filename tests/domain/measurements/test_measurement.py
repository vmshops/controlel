from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature


def test_measurement_creation():
    measurement = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(22.5),
    )

    assert measurement.sensor_id == SensorId(value="living_room_temperature")
    assert measurement.value.value == 22.5
    assert isinstance(measurement.timestamp, datetime)


def test_measurement_timestamp_is_utc():
    measurement = Measurement(
        sensor_id=SensorId(value="living_room_temperature"),
        value=Temperature(22.5),
    )

    assert measurement.timestamp.tzinfo == UTC


def test_measurement_rejects_naive_timestamp():
    with pytest.raises(ValidationError, match="timestamp must be timezone-aware"):
        Measurement(
            sensor_id=SensorId(value="living_room_temperature"),
            value=Temperature(22.5),
            timestamp=datetime(2026, 1, 1),
        )
