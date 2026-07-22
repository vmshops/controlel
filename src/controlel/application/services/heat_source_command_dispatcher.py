from controlel.application.ports.heat_source_port import HeatSourcePort
from controlel.application.state.heat_source_state_store import HeatSourceStateStore
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.states.heat_source_control_state import HeatSourceControlState


class HeatSourceCommandDispatcher:
    def __init__(
        self,
        heat_source_port: HeatSourcePort,
        state_store: HeatSourceStateStore,
    ) -> None:
        self.heat_source_port = heat_source_port
        self.state_store = state_store

    def dispatch(self, command: HeatSourceCommand) -> bool:
        current_state = self.state_store.get()
        if current_state is not None and current_state.applied_action == command.action:
            return False

        self.heat_source_port.execute(command)
        self.state_store.save(
            HeatSourceControlState(
                applied_action=command.action,
                command_id=command.id,
            )
        )
        return True
