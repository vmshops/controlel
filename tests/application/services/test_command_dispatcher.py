from controlel.application.services.command_dispatcher import CommandDispatcher
from controlel.domain.commands.command import Command


class FakeActuator:
    def __init__(self):
        self.executed_command = None

    def execute(self, command):
        self.executed_command = command


def test_dispatcher_executes_command():
    actuator = FakeActuator()

    dispatcher = CommandDispatcher(
        actuator=actuator,
    )

    command = Command(
        command_type="heating",
        action="enable_heating",
    )

    dispatcher.dispatch(command)

    assert actuator.executed_command == command
