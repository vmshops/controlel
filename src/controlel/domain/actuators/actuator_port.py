from abc import ABC, abstractmethod

from controlel.domain.commands.command import Command


class ActuatorPort(ABC):
    """
    Interface for actuator execution.
    """

    @abstractmethod
    def execute(self, command: Command) -> None:
        pass
