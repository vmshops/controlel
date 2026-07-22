from controlel.application.services.zone_actuator_router import ZoneActuatorRouter
from controlel.domain.commands.command import Command
from controlel.domain.repositories.state_repository import StateRepository
from controlel.domain.states.control_state import ControlState


class CommandDispatcher:
    """
    Dispatches commands to actuators.
    """

    def __init__(
        self,
        actuator_router: ZoneActuatorRouter,
        state_repository: StateRepository,
    ) -> None:
        self.actuator_router = actuator_router
        self.state_repository = state_repository

    def dispatch(self, command: Command) -> bool:
        actuator = self.actuator_router.resolve(command.zone_id)
        current_state = self.state_repository.get(command.zone_id)
        if current_state is not None and current_state.applied_action == command.action:
            return False

        actuator.execute(command)
        self.state_repository.save(
            ControlState(
                zone_id=command.zone_id,
                applied_action=command.action,
                command_id=command.id,
            )
        )
        return True
