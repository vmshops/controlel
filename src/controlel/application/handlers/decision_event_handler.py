from controlel.domain.commands.command import Command
from controlel.domain.events.decision_event import DecisionCreatedEvent


class DecisionEventHandler:
    """
    Converts decision events into executable commands.
    """

    def handle(self, event: DecisionCreatedEvent) -> Command:
        return Command.from_decision(event.decision)
