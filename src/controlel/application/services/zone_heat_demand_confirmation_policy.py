from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from controlel.application.services.heat_demand_safety_policy import (
    HeatDemandClockRegressionError,
)
from controlel.application.state.zone_heat_demand_confirmation_state import (
    ZoneHeatDemandConfirmationPhase,
    ZoneHeatDemandConfirmationReason,
    ZoneHeatDemandConfirmationState,
)
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)


@dataclass(frozen=True)
class ZoneHeatDemandConfirmationAssessment:
    state: ZoneHeatDemandConfirmationState
    output_demand: BuildingHeatDemandStatus

    def __post_init__(self) -> None:
        if not isinstance(self.state, ZoneHeatDemandConfirmationState):
            raise TypeError("state must be a ZoneHeatDemandConfirmationState")
        if not isinstance(self.output_demand, BuildingHeatDemandStatus):
            raise TypeError("output_demand must be a BuildingHeatDemandStatus")


class ZoneHeatDemandConfirmationPolicy:
    """Confirm a continuous zone heat request before source arbitration."""

    def __init__(self, *, confirmation_duration: timedelta) -> None:
        if not isinstance(confirmation_duration, timedelta):
            raise TypeError("confirmation_duration must be a timedelta")
        if confirmation_duration < timedelta(0):
            raise ValueError("confirmation_duration must not be negative")
        self.confirmation_duration = confirmation_duration

    def evaluate(
        self,
        *,
        hysteresis_demand: BuildingHeatDemandStatus,
        now: datetime,
        current_state: ZoneHeatDemandConfirmationState | None,
        deadline_reevaluation: bool = False,
    ) -> ZoneHeatDemandConfirmationAssessment:
        if not isinstance(hysteresis_demand, BuildingHeatDemandStatus):
            raise TypeError("hysteresis_demand must be a BuildingHeatDemandStatus")
        _aware(now)
        if current_state is not None:
            if not isinstance(current_state, ZoneHeatDemandConfirmationState):
                raise TypeError("current_state must be a ZoneHeatDemandConfirmationState or None")
            if now < current_state.last_evaluated_at:
                raise HeatDemandClockRegressionError(
                    current_state.last_evaluated_at,
                    now,
                )

        if hysteresis_demand is BuildingHeatDemandStatus.INDETERMINATE:
            preserved = (
                current_state is not None and current_state.confirmed_demand is BuildingHeatDemandStatus.HEAT_REQUIRED
            )
            reason = (
                ZoneHeatDemandConfirmationReason.CANCELLED_MEASUREMENT_INDETERMINATE
                if current_state is not None
                and current_state.phase is ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING
                else ZoneHeatDemandConfirmationReason.CONFIRMED_DEMAND_PRESERVED
                if preserved
                else ZoneHeatDemandConfirmationReason.CANCELLED_MEASUREMENT_INDETERMINATE
            )
            return self._assessment(
                phase=ZoneHeatDemandConfirmationPhase.INDETERMINATE,
                hysteresis_demand=hysteresis_demand,
                confirmed_demand=(
                    BuildingHeatDemandStatus.HEAT_REQUIRED if preserved else BuildingHeatDemandStatus.NO_HEAT_REQUIRED
                ),
                output_demand=BuildingHeatDemandStatus.INDETERMINATE,
                reason=reason,
                now=now,
            )

        if hysteresis_demand is BuildingHeatDemandStatus.NO_HEAT_REQUIRED:
            reason = (
                ZoneHeatDemandConfirmationReason.EXPIRED_BUT_DEMAND_CHANGED
                if deadline_reevaluation
                and current_state is not None
                and current_state.phase is ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING
                else ZoneHeatDemandConfirmationReason.CANCELLED_DEMAND_CLEARED
                if current_state is not None
                and current_state.phase is ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING
                else ZoneHeatDemandConfirmationReason.NO_HEAT_REQUIRED
            )
            return self._assessment(
                phase=ZoneHeatDemandConfirmationPhase.NO_HEAT_REQUIRED,
                hysteresis_demand=hysteresis_demand,
                confirmed_demand=BuildingHeatDemandStatus.NO_HEAT_REQUIRED,
                output_demand=BuildingHeatDemandStatus.NO_HEAT_REQUIRED,
                reason=reason,
                now=now,
            )

        if self.confirmation_duration == timedelta(0):
            return self._assessment(
                phase=ZoneHeatDemandConfirmationPhase.HEAT_REQUIRED_CONFIRMED,
                hysteresis_demand=hysteresis_demand,
                confirmed_demand=BuildingHeatDemandStatus.HEAT_REQUIRED,
                output_demand=BuildingHeatDemandStatus.HEAT_REQUIRED,
                reason=ZoneHeatDemandConfirmationReason.BYPASSED_ZERO_DURATION,
                now=now,
            )

        if (
            current_state is not None
            and current_state.confirmed_demand is BuildingHeatDemandStatus.HEAT_REQUIRED
            and current_state.phase is not ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING
        ):
            return self._assessment(
                phase=ZoneHeatDemandConfirmationPhase.HEAT_REQUIRED_CONFIRMED,
                hysteresis_demand=hysteresis_demand,
                confirmed_demand=BuildingHeatDemandStatus.HEAT_REQUIRED,
                output_demand=BuildingHeatDemandStatus.HEAT_REQUIRED,
                reason=ZoneHeatDemandConfirmationReason.CONFIRMED_DEMAND_PRESERVED,
                now=now,
            )

        if current_state is not None and current_state.phase is ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING:
            deadline = current_state.confirmation_deadline
            if deadline is None:
                raise RuntimeError("pending confirmation requires a deadline")
            if now < deadline:
                state = replace(
                    current_state,
                    hysteresis_demand=hysteresis_demand,
                    last_evaluated_at=now,
                )
                return ZoneHeatDemandConfirmationAssessment(
                    state=state,
                    output_demand=BuildingHeatDemandStatus.NO_HEAT_REQUIRED,
                )
            return self._assessment(
                phase=ZoneHeatDemandConfirmationPhase.HEAT_REQUIRED_CONFIRMED,
                hysteresis_demand=hysteresis_demand,
                confirmed_demand=BuildingHeatDemandStatus.HEAT_REQUIRED,
                output_demand=BuildingHeatDemandStatus.HEAT_REQUIRED,
                reason=ZoneHeatDemandConfirmationReason.COMPLETED,
                now=now,
            )

        return self._assessment(
            phase=ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING,
            hysteresis_demand=hysteresis_demand,
            confirmed_demand=BuildingHeatDemandStatus.NO_HEAT_REQUIRED,
            output_demand=BuildingHeatDemandStatus.NO_HEAT_REQUIRED,
            reason=ZoneHeatDemandConfirmationReason.STARTED,
            now=now,
            started_at=now,
        )

    def stopped_state(
        self,
        current_state: ZoneHeatDemandConfirmationState | None,
        *,
        now: datetime,
    ) -> ZoneHeatDemandConfirmationState:
        return self._terminal_state(
            current_state,
            now=now,
            phase=ZoneHeatDemandConfirmationPhase.STOPPED,
            reason=ZoneHeatDemandConfirmationReason.STOPPED,
        )

    def fatal_state(
        self,
        current_state: ZoneHeatDemandConfirmationState | None,
        *,
        now: datetime,
    ) -> ZoneHeatDemandConfirmationState:
        return self._terminal_state(
            current_state,
            now=now,
            phase=ZoneHeatDemandConfirmationPhase.FATAL_ERROR,
            reason=ZoneHeatDemandConfirmationReason.FATAL_ERROR,
        )

    def _terminal_state(
        self,
        current_state: ZoneHeatDemandConfirmationState | None,
        *,
        now: datetime,
        phase: ZoneHeatDemandConfirmationPhase,
        reason: ZoneHeatDemandConfirmationReason,
    ) -> ZoneHeatDemandConfirmationState:
        _aware(now)
        return ZoneHeatDemandConfirmationState(
            phase=phase,
            hysteresis_demand=(
                current_state.hysteresis_demand if current_state is not None else BuildingHeatDemandStatus.INDETERMINATE
            ),
            confirmed_demand=(
                current_state.confirmed_demand
                if current_state is not None
                else BuildingHeatDemandStatus.NO_HEAT_REQUIRED
            ),
            confirmation_duration=self.confirmation_duration,
            confirmation_started_at=None,
            confirmation_deadline=None,
            last_reason=reason,
            last_evaluated_at=now,
        )

    def _assessment(
        self,
        *,
        phase: ZoneHeatDemandConfirmationPhase,
        hysteresis_demand: BuildingHeatDemandStatus,
        confirmed_demand: BuildingHeatDemandStatus,
        output_demand: BuildingHeatDemandStatus,
        reason: ZoneHeatDemandConfirmationReason,
        now: datetime,
        started_at: datetime | None = None,
    ) -> ZoneHeatDemandConfirmationAssessment:
        return ZoneHeatDemandConfirmationAssessment(
            state=ZoneHeatDemandConfirmationState(
                phase=phase,
                hysteresis_demand=hysteresis_demand,
                confirmed_demand=confirmed_demand,
                confirmation_duration=self.confirmation_duration,
                confirmation_started_at=started_at,
                confirmation_deadline=(started_at + self.confirmation_duration if started_at is not None else None),
                last_reason=reason,
                last_evaluated_at=now,
            ),
            output_demand=output_demand,
        )


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
