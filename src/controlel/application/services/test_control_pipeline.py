from controlel.application.events.event_bus import EventBus
from controlel.application.services.control_loop_service import ControlLoopService
from controlel.domain.commands.command import Command
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.regulation.context import ControlContext
from controlel.domain.value_objects.temperature import Temperature


def test_complete_control_pipeline():
    context = ControlContext(
        current_temperature=Temperature(19),
        target_temperature=Temperature(22),
    )

    bus = EventBus()

    service = ControlLoopService(event_bus=bus)

    event = service.process(context)

    assert isinstance(event, DecisionCreatedEvent)

    command = bus.dispatch(event)

    assert isinstance(command, Command)

    assert command.action == "enable_heating"
