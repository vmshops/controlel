from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from controlel.domain.commands.heating_action import HeatingAction


class SourceControlPhase(StrEnum):
    IDLE = "idle"
    HEATING_REQUESTED = "heating_requested"
    HEATING_NOT_REQUESTED = "heating_not_requested"
    DEFERRED_ENABLE = "deferred_enable"
    DEFERRED_DISABLE = "deferred_disable"
    STOPPED = "stopped"
    FATAL_ERROR = "fatal_error"


class SourceControlReason(StrEnum):
    NORMAL_DEMAND = "normal_demand"
    DUPLICATE_COMMAND = "duplicate_command"
    MINIMUM_ON_TIME_ACTIVE = "minimum_on_time_active"
    MINIMUM_OFF_TIME_ACTIVE = "minimum_off_time_active"
    DEFERRED_COMMAND_CANCELLED = "deferred_command_cancelled"
    LOCKOUT_EXPIRED_REEVALUATION = "lockout_expired_reevaluation"
    SAFETY_DISABLE_BYPASSED_LOCKOUT = "safety_disable_bypassed_lockout"


@dataclass(frozen=True)
class SourceControlState:
    phase: SourceControlPhase
    logical_demand: HeatingAction | None
    last_dispatched_command: HeatingAction | None
    last_dispatch_timestamp: datetime | None
    minimum_on_deadline: datetime | None
    minimum_off_deadline: datetime | None
    deferred_command: HeatingAction | None
    deferred_reason: SourceControlReason | None
    next_reevaluation_deadline: datetime | None
    last_normal_command_dispatch: datetime | None
    safety_bypassed_lockout: bool
    last_evaluated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.phase, SourceControlPhase):
            raise TypeError("phase must be a SourceControlPhase")
        for label, value in (
            ("logical_demand", self.logical_demand),
            ("last_dispatched_command", self.last_dispatched_command),
            ("deferred_command", self.deferred_command),
        ):
            if value is not None and not isinstance(value, HeatingAction):
                raise TypeError(f"{label} must be a HeatingAction or None")
        if self.deferred_reason is not None and not isinstance(
            self.deferred_reason,
            SourceControlReason,
        ):
            raise TypeError("deferred_reason must be a SourceControlReason or None")
        for label, value in (
            ("last_dispatch_timestamp", self.last_dispatch_timestamp),
            ("minimum_on_deadline", self.minimum_on_deadline),
            ("minimum_off_deadline", self.minimum_off_deadline),
            ("next_reevaluation_deadline", self.next_reevaluation_deadline),
            ("last_normal_command_dispatch", self.last_normal_command_dispatch),
            ("last_evaluated_at", self.last_evaluated_at),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{label} must be timezone-aware")
        if self.last_dispatched_command is None and (
            self.last_dispatch_timestamp is not None
            or self.minimum_on_deadline is not None
            or self.minimum_off_deadline is not None
        ):
            raise ValueError("dispatch timestamps and deadlines require a dispatched command")
        if (self.deferred_command is None) != (self.next_reevaluation_deadline is None):
            raise ValueError("deferred command and next reevaluation deadline must coexist")
        if self.deferred_command is None and self.deferred_reason is not None:
            raise ValueError("deferred_reason requires a deferred command")
