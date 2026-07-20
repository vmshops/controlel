from controlel.domain.commands.command import Command


class CommandDispatcher:
    """
    Dispatches commands to actuators.
    """

    def __init__(self, actuator):
        self.actuator = actuator

    def dispatch(self, command: Command):
        self.actuator.execute(command)
