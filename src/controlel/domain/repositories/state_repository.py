from controlel.domain.states.control_state import ControlState


class StateRepository:
    """
    Stores current control state.
    """

    def __init__(self):
        self._state: ControlState | None = None

    def get(self) -> ControlState | None:
        return self._state

    def save(self, state: ControlState) -> None:
        self._state = state
