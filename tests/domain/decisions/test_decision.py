from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from controlel.domain.decisions.decision import Decision
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId

SENSOR_ID = SensorId(value="living_room_temperature")
ZONE_ID = ZoneId(value="living_room")


def create_decision(action: DecisionAction | str) -> Decision:
    return Decision(
        sensor_id=SENSOR_ID,
        zone_id=ZONE_ID,
        action=action,
        reason="temperature_below_target",
        metadata={"current_temperature": 19},
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize("action", list(DecisionAction))
def test_decision_accepts_and_retains_each_typed_action(action: DecisionAction):
    decision = create_decision(action)

    assert decision.action is action


@pytest.mark.parametrize("action", list(DecisionAction))
def test_decision_parses_each_serialized_action(action: DecisionAction):
    decision = create_decision(action.value)

    assert type(decision.action) is DecisionAction
    assert decision.action is action


@pytest.mark.parametrize("invalid_action", ["unknown", "enable_heatin"])
def test_decision_rejects_unknown_or_misspelled_action(invalid_action: str):
    with pytest.raises(ValidationError, match="action"):
        create_decision(invalid_action)


def test_decision_action_is_required():
    with pytest.raises(ValidationError, match="action"):
        Decision(sensor_id=SENSOR_ID, zone_id=ZONE_ID)


def test_decision_preserves_data_and_serializes_action_as_stable_string():
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    decision = create_decision(DecisionAction.ENABLE_HEATING)

    assert decision.sensor_id is SENSOR_ID
    assert decision.zone_id is ZONE_ID
    assert decision.reason == "temperature_below_target"
    assert decision.metadata == {"current_temperature": 19}
    assert decision.timestamp == timestamp
    assert decision.model_dump()["action"] is DecisionAction.ENABLE_HEATING
    assert decision.model_dump(mode="json")["action"] == "enable_heating"


def test_decision_requires_sensor_id():
    with pytest.raises(ValidationError, match="sensor_id"):
        Decision(zone_id=ZONE_ID, action=DecisionAction.ENABLE_HEATING)


def test_decision_requires_zone_id():
    with pytest.raises(ValidationError, match="zone_id"):
        Decision(sensor_id=SENSOR_ID, action=DecisionAction.ENABLE_HEATING)
