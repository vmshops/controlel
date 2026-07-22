from controlel.domain.decisions.decision import Decision
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


def test_decision_contains_reason():
    decision = Decision(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        action="enable_heating",
        reason="temperature_below_target",
    )

    assert decision.reason == "temperature_below_target"
