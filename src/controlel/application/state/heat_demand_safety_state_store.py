from controlel.application.state.heat_demand_safety_state import (
    HeatDemandSafetyState,
)


class HeatDemandSafetyStateStore:
    def __init__(self) -> None:
        self._state: HeatDemandSafetyState | None = None

    def get(self) -> HeatDemandSafetyState | None:
        return self._state

    def save(self, state: HeatDemandSafetyState) -> None:
        self._state = state
