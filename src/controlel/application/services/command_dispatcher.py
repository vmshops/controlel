from controlel.domain.actuators.actuator_port import ActuatorPort
from controlel.domain.commands.command import Command
from controlel.domain.repositories.state_repository import StateRepository
from controlel.domain.states.control_state import ControlState


class CommandDispatcher:
    """
    Dispatches commands to actuators.
    """

    def __init__(
        self,
        actuator: ActuatorPort,
        state_repository: StateRepository,
    ):
        self.actuator = actuator
        self.state_repository = state_repository

    def dispatch(self, command: Command) -> bool:
        current_state = self.state_repository.get(command.zone_id)
        if current_state is not None and current_state.applied_action == command.action:
            return False

        self.actuator.execute(command)
        self.state_repository.save(
            ControlState(
                zone_id=command.zone_id,
                applied_action=command.action,
                command_id=command.id,
            )
        )
        return True
