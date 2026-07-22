import pytest

from controlel.application.services.command_dispatcher import CommandDispatcher
from controlel.domain.actuators.actuator_port import ActuatorPort
from controlel.domain.commands.command import Command


class RecordingActuator(ActuatorPort):
    def __init__(self):
        self.executed_commands = []

    def execute(self, command: Command) -> None:
        self.executed_commands.append(command)


class ActuatorFailure(Exception):
    pass


class FailingActuator(ActuatorPort):
    def __init__(self, error: Exception):
        self.error = error

    def execute(self, command: Command) -> None:
        raise self.error


def test_dispatcher_executes_exact_command_once_through_actuator_port():
    actuator = RecordingActuator()
    dispatcher = CommandDispatcher(actuator=actuator)
    command = Command(
        command_type="heating",
        action="enable_heating",
    )

    dispatcher.dispatch(command)

    assert actuator.executed_commands == [command]


def test_actuator_exception_propagates_unchanged():
    error = ActuatorFailure("execution failed")
    dispatcher = CommandDispatcher(actuator=FailingActuator(error))
    command = Command(
        command_type="heating",
        action="enable_heating",
    )

    with pytest.raises(ActuatorFailure) as raised:
        dispatcher.dispatch(command)

    assert raised.value is error
