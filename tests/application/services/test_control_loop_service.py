from datetime import UTC, datetime

from controlel.application.services.control_loop_service import ControlLoopService
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.regulation.context import ControlContext
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId


def test_control_loop_creates_decision_event():
    context = ControlContext(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        current_temperature=Temperature(19),
        target_temperature=Temperature(22),
    )

    service = ControlLoopService()

    event = service.process(context)

    assert isinstance(event, DecisionCreatedEvent)
    assert event.decision.action is DecisionAction.ENABLE_HEATING
    assert event.decision.sensor_id == context.sensor_id
    assert event.decision.zone_id == context.zone_id
    assert event.decision.observed_at == context.observed_at
