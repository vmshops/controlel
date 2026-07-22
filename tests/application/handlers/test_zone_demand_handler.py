from datetime import UTC, datetime

import pytest

from controlel.application.handlers.zone_demand_handler import ZoneDemandHandler
from controlel.domain.decisions.decision import Decision
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId

OBSERVED_AT = datetime(2026, 1, 1, 11, 55, tzinfo=UTC)
SENSOR_ID = SensorId(value="living_room_temperature")
ZONE_ID = ZoneId(value="living_room")


def create_event(action: DecisionAction) -> DecisionCreatedEvent:
    return DecisionCreatedEvent(
        decision=Decision(
            sensor_id=SENSOR_ID,
            zone_id=ZONE_ID,
            observed_at=OBSERVED_AT,
            action=action,
        )
    )


@pytest.mark.parametrize(
    ("action", "requires_heat"),
    [
        (DecisionAction.ENABLE_HEATING, True),
        (DecisionAction.DISABLE_HEATING, False),
    ],
)
def test_actionable_decision_maps_to_zone_demand(action, requires_heat):
    event = create_event(action)

    demand = ZoneDemandHandler().handle(event)

    assert demand is not None
    assert demand.zone_id is ZONE_ID
    assert demand.requires_heat is requires_heat
    assert demand.source_sensor_id is SENSOR_ID
    assert demand.observed_at is OBSERVED_AT
    assert demand.observed_at != event.decision.timestamp


def test_observe_only_returns_none():
    assert ZoneDemandHandler().handle(create_event(DecisionAction.OBSERVE_ONLY)) is None


def test_mapping_is_explicitly_exhaustive_for_current_enum():
    handler = ZoneDemandHandler()

    assert {event_action for event_action in DecisionAction} == {
        DecisionAction.ENABLE_HEATING,
        DecisionAction.DISABLE_HEATING,
        DecisionAction.OBSERVE_ONLY,
    }
    assert all(handler.handle(create_event(action)) is not None for action in list(DecisionAction)[:2])


def test_unhandled_future_action_fails_loudly():
    event = create_event(DecisionAction.ENABLE_HEATING)
    object.__setattr__(event.decision, "action", "future_action")

    with pytest.raises(ValueError, match="Unhandled DecisionAction"):
        ZoneDemandHandler().handle(event)
