from controlel.domain.commands.command import Command
from controlel.domain.decisions.decision import Decision


def test_command_created_from_decision():
    decision = Decision(
        action="enable_heating",
        reason="temperature_below_target",
    )

    command = Command.from_decision(decision)

    assert command.action == "enable_heating"
