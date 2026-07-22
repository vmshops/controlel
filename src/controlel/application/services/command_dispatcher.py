from controlel.domain.actuators.actuator_port import ActuatorPort
from controlel.domain.commands.command import Command


class CommandDispatcher:
    """
    Dispatches commands to actuators.
    """

    def __init__(self, actuator: ActuatorPort):
        self.actuator = actuator

    def dispatch(self, command: Command) -> None:
        self.actuator.execute(command)
