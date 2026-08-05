from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)


class ZoneHeatDemandConfirmationPhase(StrEnum):
    NO_HEAT_REQUIRED = "no_heat_required"
    CONFIRMATION_PENDING = "confirmation_pending"
    HEAT_REQUIRED_CONFIRMED = "heat_required_confirmed"
    INDETERMINATE = "indeterminate"
    STOPPED = "stopped"
    FATAL_ERROR = "fatal_error"


class ZoneHeatDemandConfirmationReason(StrEnum):
    STARTED = "heat_demand_confirmation_started"
    COMPLETED = "heat_demand_confirmation_completed"
    CANCELLED_DEMAND_CLEARED = "heat_demand_confirmation_cancelled_demand_cleared"
    CANCELLED_MEASUREMENT_INDETERMINATE = "heat_demand_confirmation_cancelled_measurement_indeterminate"
    CANCELLED_RELOAD = "heat_demand_confirmation_cancelled_reload"
    EXPIRED_BUT_DEMAND_CHANGED = "heat_demand_confirmation_expired_but_demand_changed"
    BYPASSED_ZERO_DURATION = "heat_demand_confirmation_bypassed_zero_duration"
    CONFIRMED_DEMAND_PRESERVED = "heat_demand_confirmation_confirmed_demand_preserved"
    NO_HEAT_REQUIRED = "heat_demand_confirmation_no_heat_required"
    STOPPED = "heat_demand_confirmation_stopped"
    FATAL_ERROR = "heat_demand_confirmation_fatal_error"


@dataclass(frozen=True)
class ZoneHeatDemandConfirmationState:
    phase: ZoneHeatDemandConfirmationPhase
    hysteresis_demand: BuildingHeatDemandStatus
    confirmed_demand: BuildingHeatDemandStatus
    confirmation_duration: timedelta
    confirmation_started_at: datetime | None
    confirmation_deadline: datetime | None
    last_reason: ZoneHeatDemandConfirmationReason
    last_evaluated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.phase, ZoneHeatDemandConfirmationPhase):
            raise TypeError("phase must be a ZoneHeatDemandConfirmationPhase")
        if not isinstance(self.hysteresis_demand, BuildingHeatDemandStatus):
            raise TypeError("hysteresis_demand must be a BuildingHeatDemandStatus")
        if not isinstance(self.confirmed_demand, BuildingHeatDemandStatus):
            raise TypeError("confirmed_demand must be a BuildingHeatDemandStatus")
        if not isinstance(self.last_reason, ZoneHeatDemandConfirmationReason):
            raise TypeError("last_reason must be a ZoneHeatDemandConfirmationReason")
        if self.confirmation_duration < timedelta(0):
            raise ValueError("confirmation_duration must not be negative")
        for label, value in (
            ("confirmation_started_at", self.confirmation_started_at),
            ("confirmation_deadline", self.confirmation_deadline),
            ("last_evaluated_at", self.last_evaluated_at),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{label} must be timezone-aware")
        if (self.confirmation_started_at is None) != (self.confirmation_deadline is None):
            raise ValueError("confirmation timestamps must coexist")
        if (self.phase is ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING) != (
            self.confirmation_deadline is not None
        ):
            raise ValueError("only pending confirmation may have a deadline")
        if (
            self.confirmation_deadline is not None
            and self.confirmation_started_at is not None
            and self.confirmation_deadline != self.confirmation_started_at + self.confirmation_duration
        ):
            raise ValueError("confirmation deadline must match start plus duration")

    def remaining_at(self, now: datetime) -> timedelta | None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if self.confirmation_deadline is None:
            return None
        return max(timedelta(0), self.confirmation_deadline - now)
