from controlel.application.services.control_loop_service import ControlLoopService
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.regulation.context import ControlContext
from controlel.domain.value_objects.temperature import Temperature


def test_control_loop_creates_decision_event():
    context = ControlContext(
        current_temperature=Temperature(19),
        target_temperature=Temperature(22),
    )

    service = ControlLoopService()

    event = service.process(context)

    assert isinstance(event, DecisionCreatedEvent)
    assert event.decision.action == "enable_heating"
