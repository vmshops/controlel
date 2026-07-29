from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from controlel.application.state.temperature_hysteresis_state import (
    HysteresisDemandState,
    TemperatureHysteresisState,
)


class TemperatureHysteresisReason(StrEnum):
    LEGACY_EXACT_THRESHOLD = "legacy_exact_threshold"
    BELOW_ENABLE_THRESHOLD = "below_enable_threshold"
    ABOVE_DISABLE_THRESHOLD = "above_disable_threshold"
    INSIDE_HYSTERESIS_DEADBAND = "inside_hysteresis_deadband"
    PRESERVED_PREVIOUS_DEMAND = "preserved_previous_demand"
    STARTUP_FROM_RAW_DEMAND = "startup_from_raw_demand"


@dataclass(frozen=True)
class TemperatureHysteresisAssessment:
    state: TemperatureHysteresisState
    raw_requires_heat: bool
    enable_threshold: float
    disable_threshold: float
    reason: TemperatureHysteresisReason
    preserved_previous_demand: bool

    def __post_init__(self) -> None:
        if not isinstance(self.state, TemperatureHysteresisState):
            raise TypeError("state must be a TemperatureHysteresisState")
        if not isinstance(self.raw_requires_heat, bool):
            raise TypeError("raw_requires_heat must be a bool")
        if not isinstance(self.reason, TemperatureHysteresisReason):
            raise TypeError("reason must be a TemperatureHysteresisReason")
        if not isinstance(self.preserved_previous_demand, bool):
            raise TypeError("preserved_previous_demand must be a bool")
        if not isfinite(self.enable_threshold) or not isfinite(self.disable_threshold):
            raise ValueError("hysteresis thresholds must be finite")
        if self.enable_threshold > self.disable_threshold:
            raise ValueError("enable threshold must not exceed disable threshold")


class TemperatureHysteresisPolicy:
    def __init__(
        self,
        *,
        turn_on_differential: float,
        turn_off_differential: float,
    ) -> None:
        self.turn_on_differential = _finite_non_negative(
            turn_on_differential,
            "turn_on_differential",
        )
        self.turn_off_differential = _finite_non_negative(
            turn_off_differential,
            "turn_off_differential",
        )

    def evaluate(
        self,
        *,
        current_temperature: float,
        target_temperature: float,
        raw_requires_heat: bool,
        current_state: TemperatureHysteresisState | None,
    ) -> TemperatureHysteresisAssessment:
        current = _finite(current_temperature, "current_temperature")
        target = _finite(target_temperature, "target_temperature")
        if not isinstance(raw_requires_heat, bool):
            raise TypeError("raw_requires_heat must be a bool")
        if current_state is not None and not isinstance(
            current_state,
            TemperatureHysteresisState,
        ):
            raise TypeError("current_state must be a TemperatureHysteresisState or None")

        enable_threshold = target - self.turn_on_differential
        disable_threshold = target + self.turn_off_differential
        if not isfinite(enable_threshold) or not isfinite(disable_threshold):
            raise ValueError("calculated hysteresis thresholds must be finite")
        if enable_threshold > disable_threshold:
            raise ValueError("enable threshold must not exceed disable threshold")

        if self.turn_on_differential == 0 and self.turn_off_differential == 0:
            return self._assessment(
                demand=_demand(raw_requires_heat),
                raw_requires_heat=raw_requires_heat,
                enable_threshold=enable_threshold,
                disable_threshold=disable_threshold,
                reason=TemperatureHysteresisReason.LEGACY_EXACT_THRESHOLD,
            )

        if current_state is None:
            return self._assessment(
                demand=_demand(raw_requires_heat),
                raw_requires_heat=raw_requires_heat,
                enable_threshold=enable_threshold,
                disable_threshold=disable_threshold,
                reason=TemperatureHysteresisReason.STARTUP_FROM_RAW_DEMAND,
            )

        if current_state.demand is HysteresisDemandState.HEAT_REQUIRED:
            if current >= disable_threshold:
                return self._assessment(
                    demand=HysteresisDemandState.NO_HEAT_REQUIRED,
                    raw_requires_heat=raw_requires_heat,
                    enable_threshold=enable_threshold,
                    disable_threshold=disable_threshold,
                    reason=TemperatureHysteresisReason.ABOVE_DISABLE_THRESHOLD,
                )
            if current <= enable_threshold:
                return self._assessment(
                    demand=HysteresisDemandState.HEAT_REQUIRED,
                    raw_requires_heat=raw_requires_heat,
                    enable_threshold=enable_threshold,
                    disable_threshold=disable_threshold,
                    reason=TemperatureHysteresisReason.BELOW_ENABLE_THRESHOLD,
                )
        else:
            if current <= enable_threshold:
                return self._assessment(
                    demand=HysteresisDemandState.HEAT_REQUIRED,
                    raw_requires_heat=raw_requires_heat,
                    enable_threshold=enable_threshold,
                    disable_threshold=disable_threshold,
                    reason=TemperatureHysteresisReason.BELOW_ENABLE_THRESHOLD,
                )
            if current >= disable_threshold:
                return self._assessment(
                    demand=HysteresisDemandState.NO_HEAT_REQUIRED,
                    raw_requires_heat=raw_requires_heat,
                    enable_threshold=enable_threshold,
                    disable_threshold=disable_threshold,
                    reason=TemperatureHysteresisReason.ABOVE_DISABLE_THRESHOLD,
                )

        return self._assessment(
            demand=current_state.demand,
            raw_requires_heat=raw_requires_heat,
            enable_threshold=enable_threshold,
            disable_threshold=disable_threshold,
            reason=TemperatureHysteresisReason.PRESERVED_PREVIOUS_DEMAND,
            preserved_previous_demand=True,
        )

    @staticmethod
    def _assessment(
        *,
        demand: HysteresisDemandState,
        raw_requires_heat: bool,
        enable_threshold: float,
        disable_threshold: float,
        reason: TemperatureHysteresisReason,
        preserved_previous_demand: bool = False,
    ) -> TemperatureHysteresisAssessment:
        return TemperatureHysteresisAssessment(
            state=TemperatureHysteresisState(demand=demand),
            raw_requires_heat=raw_requires_heat,
            enable_threshold=enable_threshold,
            disable_threshold=disable_threshold,
            reason=reason,
            preserved_previous_demand=preserved_previous_demand,
        )


def _demand(requires_heat: bool) -> HysteresisDemandState:
    return HysteresisDemandState.HEAT_REQUIRED if requires_heat else HysteresisDemandState.NO_HEAT_REQUIRED


def _finite_non_negative(value: float, label: str) -> float:
    result = _finite(value, label)
    if result < 0:
        raise ValueError(f"{label} must not be negative")
    return result


def _finite(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{label} must be a number")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result
