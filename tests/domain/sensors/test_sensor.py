import pytest
from pydantic import ValidationError

from controlel.domain.capabilities.capability import Capability
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


def test_sensor_with_capabilities():
    sensor = Sensor(
        sensor_id=SensorId(value="living_room_sensor"),
        zone_id=ZoneId(value="living_room"),
        name="Living room sensor",
        capabilities=[
            Capability(name="temperature"),
            Capability(name="humidity"),
        ],
    )

    assert len(sensor.capabilities) == 2
    assert sensor.capabilities[0].name == "temperature"


def test_sensor_preserves_typed_zone_association():
    sensor = Sensor(
        sensor_id=SensorId(value="living_room_sensor"),
        zone_id=ZoneId(value="living_room"),
        name="Living room sensor",
    )

    assert sensor.zone_id == ZoneId(value="living_room")


def test_sensor_requires_zone_id():
    with pytest.raises(ValidationError, match="zone_id"):
        Sensor(
            sensor_id=SensorId(value="living_room_sensor"),
            name="Living room sensor",
        )
