from dataclasses import dataclass
from enum import StrEnum


class HysteresisDemandState(StrEnum):
    HEAT_REQUIRED = "heat_required"
    NO_HEAT_REQUIRED = "no_heat_required"


@dataclass(frozen=True)
class TemperatureHysteresisState:
    demand: HysteresisDemandState

    def __post_init__(self) -> None:
        if not isinstance(self.demand, HysteresisDemandState):
            raise TypeError("demand must be a HysteresisDemandState")
