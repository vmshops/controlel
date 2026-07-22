from controlel.domain.states.control_state import ControlState
from controlel.domain.value_objects.zone_id import ZoneId


class StateRepository:
    """
    Stores the latest applied control state for each zone.
    """

    def __init__(self):
        self._states: dict[ZoneId, ControlState] = {}

    def get(self, zone_id: ZoneId) -> ControlState | None:
        return self._states.get(zone_id)

    def save(self, state: ControlState) -> None:
        self._states[state.zone_id] = state
