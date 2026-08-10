from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from controlel.domain.commands.heating_action import HeatingAction


class SourceControlPhase(StrEnum):
    """Logical source-control state; never a claim about physical source state."""

    INDETERMINATE = "indeterminate"
    HEATING_NOT_REQUESTED = "heating_not_requested"
    HEATING_REQUESTED_AND_ALLOWED = "heating_requested_and_allowed"
    HEATING_REQUESTED_WAITING_MINIMUM_OFF = "heating_requested_waiting_minimum_off"
    HEATING_ACTIVE_REQUEST = "heating_active_request"
    HEATING_NOT_REQUESTED_WAITING_MINIMUM_ON = "heating_not_requested_waiting_minimum_on"
    SAFETY_OVERRIDE = "safety_override"
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


class ActiveLockoutType(StrEnum):
    MINIMUM_ON = "minimum_on"
    MINIMUM_OFF = "minimum_off"


class SourceCommandOutcome(StrEnum):
    NONE = "none"
    REQUESTED = "requested"
    DISPATCHED = "dispatched"
    SUPPRESSED_DUPLICATE = "suppressed_duplicate"
    DEFERRED = "deferred"
    FAILED = "failed"


@dataclass(frozen=True)
class SourceControlState:
    """Immutable normalized source-control snapshot.

    Protection boundaries describe when a future transition is allowed. Active
    lockout and deferred fields exist only while the currently requested
    transition is blocked. Nothing in this snapshot represents physical source
    feedback.
    """

    phase: SourceControlPhase
    aggregate_demand: HeatingAction | None
    last_dispatched_command: HeatingAction | None
    last_successful_enable_dispatch: datetime | None
    last_successful_disable_dispatch: datetime | None
    earliest_next_enable_time: datetime | None
    earliest_next_disable_time: datetime | None
    active_lockout_type: ActiveLockoutType | None
    active_lockout_deadline: datetime | None
    deferred_command: HeatingAction | None
    deferred_reason: SourceControlReason | None
    deferred_since: datetime | None
    deferred_deadline: datetime | None
    last_normal_command_dispatch: datetime | None
    safety_bypass_active: bool
    last_requested_command: HeatingAction | None
    last_command_outcome: SourceCommandOutcome
    last_evaluated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.phase, SourceControlPhase):
            raise TypeError("phase must be a SourceControlPhase")
        for label, value in (
            ("aggregate_demand", self.aggregate_demand),
            ("last_dispatched_command", self.last_dispatched_command),
            ("deferred_command", self.deferred_command),
            ("last_requested_command", self.last_requested_command),
        ):
            if value is not None and not isinstance(value, HeatingAction):
                raise TypeError(f"{label} must be a HeatingAction or None")
        if self.active_lockout_type is not None and not isinstance(
            self.active_lockout_type,
            ActiveLockoutType,
        ):
            raise TypeError("active_lockout_type must be an ActiveLockoutType or None")
        if self.deferred_reason is not None and not isinstance(
            self.deferred_reason,
            SourceControlReason,
        ):
            raise TypeError("deferred_reason must be a SourceControlReason or None")
        if not isinstance(self.last_command_outcome, SourceCommandOutcome):
            raise TypeError("last_command_outcome must be a SourceCommandOutcome")
        for label, value in (
            ("last_successful_enable_dispatch", self.last_successful_enable_dispatch),
            ("last_successful_disable_dispatch", self.last_successful_disable_dispatch),
            ("earliest_next_enable_time", self.earliest_next_enable_time),
            ("earliest_next_disable_time", self.earliest_next_disable_time),
            ("active_lockout_deadline", self.active_lockout_deadline),
            ("deferred_since", self.deferred_since),
            ("deferred_deadline", self.deferred_deadline),
            ("last_normal_command_dispatch", self.last_normal_command_dispatch),
            ("last_evaluated_at", self.last_evaluated_at),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{label} must be timezone-aware")
        lockout_values = (self.active_lockout_type, self.active_lockout_deadline)
        if any(value is None for value in lockout_values) != all(value is None for value in lockout_values):
            raise ValueError("active lockout type and deadline must coexist")
        deferred_values = (
            self.deferred_command,
            self.deferred_reason,
            self.deferred_since,
            self.deferred_deadline,
        )
        if any(value is None for value in deferred_values) != all(value is None for value in deferred_values):
            raise ValueError("deferred command fields must coexist")
        if self.deferred_command is None and self.active_lockout_type is not None:
            raise ValueError("an active lockout requires a deferred command")
        if self.deferred_command is not None:
            if self.deferred_command is not self.aggregate_demand:
                raise ValueError("deferred command must equal aggregate demand")
            if self.deferred_deadline != self.active_lockout_deadline:
                raise ValueError("deferred and active-lockout deadlines must match")
            expected_lockout = (
                ActiveLockoutType.MINIMUM_OFF
                if self.deferred_command is HeatingAction.ENABLE_HEATING
                else ActiveLockoutType.MINIMUM_ON
            )
            if self.active_lockout_type is not expected_lockout:
                raise ValueError("deferred command and active lockout must correspond")
        if self.safety_bypass_active and self.active_lockout_type is not None:
            raise ValueError("safety bypass cannot coexist with an active lockout")

    @property
    def logical_demand(self) -> HeatingAction | None:
        """Compatibility alias for aggregate_demand."""

        return self.aggregate_demand

    @property
    def last_dispatch_timestamp(self) -> datetime | None:
        """Compatibility view of the latest successful dispatch timestamp."""

        if self.last_dispatched_command is HeatingAction.ENABLE_HEATING:
            return self.last_successful_enable_dispatch
        if self.last_dispatched_command is HeatingAction.DISABLE_HEATING:
            return self.last_successful_disable_dispatch
        return None

    @property
    def minimum_on_deadline(self) -> datetime | None:
        """Compatibility alias for earliest_next_disable_time."""

        return self.earliest_next_disable_time

    @property
    def minimum_off_deadline(self) -> datetime | None:
        """Compatibility alias for earliest_next_enable_time."""

        return self.earliest_next_enable_time

    @property
    def next_reevaluation_deadline(self) -> datetime | None:
        """Compatibility alias for the current deferred deadline."""

        return self.deferred_deadline

    @property
    def safety_bypassed_lockout(self) -> bool:
        """Compatibility alias for safety_bypass_active."""

        return self.safety_bypass_active
