import pytest
from pydantic import ValidationError

from controlel.domain.regulation.context import ControlContext
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId


def test_control_context_creation():
    context = ControlContext(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        current_temperature=Temperature(21.2),
        target_temperature=Temperature(22),
    )

    assert context.sensor_id == SensorId(value="living_room_temperature")
    assert context.zone_id == ZoneId(value="living_room")
    assert context.current_temperature.value == 21.2
    assert context.target_temperature.value == 22


def test_control_context_requires_sensor_id():
    with pytest.raises(ValidationError, match="sensor_id"):
        ControlContext(
            zone_id=ZoneId(value="living_room"),
            current_temperature=Temperature(21.2),
            target_temperature=Temperature(22),
        )


def test_control_context_requires_zone_id():
    with pytest.raises(ValidationError, match="zone_id"):
        ControlContext(
            sensor_id=SensorId(value="living_room_temperature"),
            current_temperature=Temperature(21.2),
            target_temperature=Temperature(22),
        )
