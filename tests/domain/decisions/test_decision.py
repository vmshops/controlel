import pytest
from pydantic import ValidationError

from controlel.domain.decisions.decision import Decision
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


def test_decision_creation():
    decision = Decision(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        action="enable_heating",
    )

    assert decision.sensor_id == SensorId(value="living_room_temperature")
    assert decision.zone_id == ZoneId(value="living_room")
    assert decision.action == "enable_heating"


def test_decision_requires_sensor_id():
    with pytest.raises(ValidationError, match="sensor_id"):
        Decision(
            zone_id=ZoneId(value="living_room"),
            action="enable_heating",
        )


def test_decision_requires_zone_id():
    with pytest.raises(ValidationError, match="zone_id"):
        Decision(
            sensor_id=SensorId(value="living_room_temperature"),
            action="enable_heating",
        )
