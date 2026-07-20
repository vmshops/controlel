from controlel.application.handlers.decision_event_handler import DecisionEventHandler
from controlel.domain.commands.command import Command
from controlel.domain.decisions.decision import Decision
from controlel.domain.events.decision_event import DecisionCreatedEvent


def test_decision_event_creates_command():
    event = DecisionCreatedEvent(
        decision=Decision(
            action="enable_heating",
            reason="temperature_below_target",
        )
    )

    handler = DecisionEventHandler()

    command = handler.handle(event)

    assert isinstance(command, Command)
    assert command.action == "enable_heating"
