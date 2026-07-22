from controlel.domain.states.heat_source_control_state import HeatSourceControlState


class HeatSourceStateStore:
    def __init__(self) -> None:
        self._state: HeatSourceControlState | None = None

    def get(self) -> HeatSourceControlState | None:
        return self._state

    def save(self, state: HeatSourceControlState) -> None:
        self._state = state
