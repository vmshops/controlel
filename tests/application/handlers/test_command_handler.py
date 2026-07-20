from controlel.application.handlers.command_handler import CommandHandler
from controlel.domain.commands.command import Command


class FakeActuator:
    def __init__(self):
        self.executed = False

    def execute(self, command):
        self.executed = True


def test_command_handler_executes_command():
    actuator = FakeActuator()

    handler = CommandHandler(
        actuator=actuator,
    )

    command = Command(
        command_type="enable_heating",
    )

    handler.handle(command)

    assert actuator.executed is True
