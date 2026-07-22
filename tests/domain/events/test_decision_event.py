from controlel.domain.decisions.decision import Decision
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


def test_decision_created_event_contains_decision():
    decision = Decision(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        action="enable_heating",
        reason="temperature_below_target",
    )

    event = DecisionCreatedEvent(
        decision=decision,
    )

    assert event.decision == decision
    assert "sensor_id" not in DecisionCreatedEvent.model_fields
    assert "zone_id" not in DecisionCreatedEvent.model_fields
