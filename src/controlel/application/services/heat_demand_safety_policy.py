from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from controlel.application.state.heat_demand_safety_state import (
    HeatDemandSafetyState,
)
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand import BuildingHeatDemand
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)


class HeatDemandSafetyPhase(StrEnum):
    DETERMINATE = "determinate"
    INDETERMINATE_GRACE = "indeterminate_grace"
    INDETERMINATE_TIMED_OUT = "indeterminate_timed_out"


class HeatDemandClockRegressionError(ValueError):
    def __init__(
        self,
        previous_evaluated_at: datetime,
        current_evaluated_at: datetime,
    ) -> None:
        self.previous_evaluated_at = previous_evaluated_at
        self.current_evaluated_at = current_evaluated_at
        super().__init__(
            "Heat-demand evaluation time regressed from "
            f"{previous_evaluated_at.isoformat()} to {current_evaluated_at.isoformat()}"
        )


@dataclass(frozen=True)
class HeatDemandSafetyAssessment:
    state: HeatDemandSafetyState
    phase: HeatDemandSafetyPhase
    timeout_at: datetime | None
    action: HeatingAction | None

    def __post_init__(self) -> None:
        if not isinstance(self.state, HeatDemandSafetyState):
            raise TypeError("state must be a HeatDemandSafetyState")
        if not isinstance(self.phase, HeatDemandSafetyPhase):
            raise TypeError("phase must be a HeatDemandSafetyPhase")
        if self.timeout_at is not None and (self.timeout_at.tzinfo is None or self.timeout_at.utcoffset() is None):
            raise ValueError("timeout_at must be timezone-aware")
        if self.action is not None and not isinstance(self.action, HeatingAction):
            raise TypeError("action must be a HeatingAction or None")

        if self.phase is HeatDemandSafetyPhase.DETERMINATE:
            if self.state.indeterminate_since is not None or self.timeout_at is not None or self.action is not None:
                raise ValueError("DETERMINATE requires no indeterminate period, timeout, or action")
            return

        if self.phase is HeatDemandSafetyPhase.INDETERMINATE_GRACE:
            if self.state.indeterminate_since is None or self.timeout_at is None or self.action is not None:
                raise ValueError("INDETERMINATE_GRACE requires a period and timeout without an action")
            return

        if self.phase is HeatDemandSafetyPhase.INDETERMINATE_TIMED_OUT:
            if self.state.indeterminate_since is None or self.timeout_at is None or self.action is None:
                raise ValueError("INDETERMINATE_TIMED_OUT requires a period, timeout, and action")
            return

        raise ValueError(f"Unhandled HeatDemandSafetyPhase: {self.phase!r}")


class HeatDemandSafetyPolicy:
    def __init__(
        self,
        grace_period: timedelta,
        timeout_action: HeatingAction,
    ) -> None:
        if not isinstance(grace_period, timedelta):
            raise TypeError("grace_period must be a timedelta")
        if grace_period < timedelta(0):
            raise ValueError("grace_period must not be negative")
        if not isinstance(timeout_action, HeatingAction):
            raise TypeError("timeout_action must be a HeatingAction")

        self.grace_period = grace_period
        self.timeout_action = timeout_action

    def evaluate(
        self,
        demand: BuildingHeatDemand,
        current_state: HeatDemandSafetyState | None,
        indeterminate_start_hint: datetime | None = None,
    ) -> HeatDemandSafetyAssessment:
        evaluated_at = demand.evaluated_at
        if current_state is not None and evaluated_at < current_state.last_evaluated_at:
            raise HeatDemandClockRegressionError(
                previous_evaluated_at=current_state.last_evaluated_at,
                current_evaluated_at=evaluated_at,
            )

        if demand.status is not BuildingHeatDemandStatus.INDETERMINATE:
            state = HeatDemandSafetyState(
                last_determinate_status=demand.status,
                last_evaluated_at=evaluated_at,
            )
            return HeatDemandSafetyAssessment(
                state=state,
                phase=HeatDemandSafetyPhase.DETERMINATE,
                timeout_at=None,
                action=None,
            )

        if current_state is not None and current_state.indeterminate_since is not None:
            indeterminate_since = current_state.indeterminate_since
        else:
            if indeterminate_start_hint is not None:
                if indeterminate_start_hint.tzinfo is None or indeterminate_start_hint.utcoffset() is None:
                    raise ValueError("indeterminate_start_hint must be timezone-aware")
                if indeterminate_start_hint > evaluated_at:
                    raise ValueError("indeterminate_start_hint must not be later than demand.evaluated_at")
            indeterminate_since = indeterminate_start_hint or evaluated_at

        state = HeatDemandSafetyState(
            indeterminate_since=indeterminate_since,
            last_determinate_status=(current_state.last_determinate_status if current_state is not None else None),
            last_evaluated_at=evaluated_at,
        )
        timeout_at = indeterminate_since + self.grace_period
        if evaluated_at < timeout_at:
            return HeatDemandSafetyAssessment(
                state=state,
                phase=HeatDemandSafetyPhase.INDETERMINATE_GRACE,
                timeout_at=timeout_at,
                action=None,
            )

        return HeatDemandSafetyAssessment(
            state=state,
            phase=HeatDemandSafetyPhase.INDETERMINATE_TIMED_OUT,
            timeout_at=timeout_at,
            action=self.timeout_action,
        )
