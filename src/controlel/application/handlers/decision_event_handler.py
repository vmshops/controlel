from controlel.domain.commands.command import Command
from controlel.domain.events.decision_event import DecisionCreatedEvent


class DecisionEventHandler:
    """
    Converts decision events into executable commands.
    """

    def handle(self, event: DecisionCreatedEvent) -> Command | None:
        if event.decision.action not in {"enable_heating", "disable_heating"}:
            return None

        return Command(
            command_type="heating",
            action=event.decision.action,
        )
