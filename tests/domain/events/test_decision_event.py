from datetime import UTC, datetime

from controlel.domain.decisions.decision import Decision
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


def test_decision_created_event_contains_decision():
    decision = Decision(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        action=DecisionAction.ENABLE_HEATING,
        reason="temperature_below_target",
    )

    event = DecisionCreatedEvent(
        decision=decision,
    )

    assert event.decision == decision
    assert "sensor_id" not in DecisionCreatedEvent.model_fields
    assert "zone_id" not in DecisionCreatedEvent.model_fields
