from datetime import UTC, datetime

from controlel.domain.decisions.decision import Decision
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


def test_decision_contains_reason():
    decision = Decision(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        action=DecisionAction.ENABLE_HEATING,
        reason="temperature_below_target",
    )

    assert decision.reason == "temperature_below_target"
