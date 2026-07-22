from controlel.domain.decisions.decision import Decision
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


def test_decision_contains_metadata():
    decision = Decision(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        action=DecisionAction.ENABLE_HEATING,
        reason="temperature_below_target",
        metadata={
            "current_temperature": 20,
            "target_temperature": 22,
        },
    )

    assert decision.metadata["current_temperature"] == 20
    assert decision.metadata["target_temperature"] == 22
