from controlel.domain.commands.command import Command
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.events.decision_event import DecisionCreatedEvent

_COMMAND_ACTION_BY_DECISION_ACTION: dict[DecisionAction, HeatingAction | None] = {
    DecisionAction.ENABLE_HEATING: HeatingAction.ENABLE_HEATING,
    DecisionAction.DISABLE_HEATING: HeatingAction.DISABLE_HEATING,
    DecisionAction.OBSERVE_ONLY: None,
}


class DecisionEventHandler:
    """
    Converts decision events into executable commands.
    """

    def handle(self, event: DecisionCreatedEvent) -> Command | None:
        command_action = _COMMAND_ACTION_BY_DECISION_ACTION[event.decision.action]
        if command_action is None:
            return None

        return Command(
            zone_id=event.decision.zone_id,
            command_type=CommandFamily.HEATING,
            action=command_action,
        )
