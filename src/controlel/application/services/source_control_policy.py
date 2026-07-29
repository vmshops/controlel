from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from controlel.application.state.source_control_state import (
    SourceControlPhase,
    SourceControlReason,
    SourceControlState,
)
from controlel.domain.commands.heating_action import HeatingAction


class SourceControlOutcome(StrEnum):
    DISPATCH = "dispatch"
    SUPPRESS_DUPLICATE = "suppress_duplicate"
    DEFER = "defer"


class ActiveLockoutType(StrEnum):
    MINIMUM_ON = "minimum_on"
    MINIMUM_OFF = "minimum_off"


@dataclass(frozen=True)
class SourceControlAssessment:
    state: SourceControlState
    outcome: SourceControlOutcome
    reason: SourceControlReason
    active_lockout: ActiveLockoutType | None
    lockout_deadline: datetime | None
    safety_bypassed_lockout: bool


class SourceControlPolicy:
    def __init__(
        self,
        *,
        minimum_on_time: timedelta,
        minimum_off_time: timedelta,
    ) -> None:
        self.minimum_on_time = _non_negative_duration(
            minimum_on_time,
            "minimum_on_time",
        )
        self.minimum_off_time = _non_negative_duration(
            minimum_off_time,
            "minimum_off_time",
        )

    def initial_state(self, now: datetime) -> SourceControlState:
        _aware(now, "now")
        return SourceControlState(
            phase=SourceControlPhase.IDLE,
            logical_demand=None,
            last_dispatched_command=None,
            last_dispatch_timestamp=None,
            minimum_on_deadline=None,
            minimum_off_deadline=None,
            deferred_command=None,
            deferred_reason=None,
            next_reevaluation_deadline=None,
            last_normal_command_dispatch=None,
            safety_bypassed_lockout=False,
            last_evaluated_at=now,
        )

    def evaluate(
        self,
        *,
        desired_command: HeatingAction,
        now: datetime,
        current_state: SourceControlState | None,
        safety_command: bool = False,
        lockout_expiry_reevaluation: bool = False,
    ) -> SourceControlAssessment:
        if not isinstance(desired_command, HeatingAction):
            raise TypeError("desired_command must be a HeatingAction")
        _aware(now, "now")
        state = current_state or self.initial_state(now)
        if now < state.last_evaluated_at:
            raise ValueError("source-control evaluation time must not regress")

        active_lockout, deadline = self._active_lockout(state, now)
        bypass = (
            safety_command
            and desired_command is HeatingAction.DISABLE_HEATING
            and state.last_dispatched_command is HeatingAction.ENABLE_HEATING
            and active_lockout is ActiveLockoutType.MINIMUM_ON
        )
        if bypass:
            updated = replace(
                state,
                logical_demand=desired_command,
                deferred_command=None,
                deferred_reason=None,
                next_reevaluation_deadline=None,
                safety_bypassed_lockout=True,
                last_evaluated_at=now,
            )
            return SourceControlAssessment(
                state=updated,
                outcome=SourceControlOutcome.DISPATCH,
                reason=SourceControlReason.SAFETY_DISABLE_BYPASSED_LOCKOUT,
                active_lockout=active_lockout,
                lockout_deadline=deadline,
                safety_bypassed_lockout=True,
            )

        if state.last_dispatched_command is desired_command:
            cancelled = state.deferred_command is not None
            updated = replace(
                state,
                phase=_settled_phase(desired_command),
                logical_demand=desired_command,
                deferred_command=None,
                deferred_reason=None,
                next_reevaluation_deadline=None,
                safety_bypassed_lockout=False,
                last_evaluated_at=now,
            )
            return SourceControlAssessment(
                state=updated,
                outcome=SourceControlOutcome.SUPPRESS_DUPLICATE,
                reason=(
                    SourceControlReason.DEFERRED_COMMAND_CANCELLED
                    if cancelled
                    else SourceControlReason.DUPLICATE_COMMAND
                ),
                active_lockout=active_lockout,
                lockout_deadline=deadline,
                safety_bypassed_lockout=False,
            )

        blocking_lockout, blocking_deadline = self._blocking_lockout(
            state,
            desired_command,
            now,
        )
        if blocking_lockout is not None and blocking_deadline is not None:
            reason = (
                SourceControlReason.MINIMUM_ON_TIME_ACTIVE
                if blocking_lockout is ActiveLockoutType.MINIMUM_ON
                else SourceControlReason.MINIMUM_OFF_TIME_ACTIVE
            )
            updated = replace(
                state,
                phase=(
                    SourceControlPhase.DEFERRED_DISABLE
                    if desired_command is HeatingAction.DISABLE_HEATING
                    else SourceControlPhase.DEFERRED_ENABLE
                ),
                logical_demand=desired_command,
                deferred_command=desired_command,
                deferred_reason=reason,
                next_reevaluation_deadline=blocking_deadline,
                safety_bypassed_lockout=False,
                last_evaluated_at=now,
            )
            return SourceControlAssessment(
                state=updated,
                outcome=SourceControlOutcome.DEFER,
                reason=reason,
                active_lockout=blocking_lockout,
                lockout_deadline=blocking_deadline,
                safety_bypassed_lockout=False,
            )

        reason = (
            SourceControlReason.LOCKOUT_EXPIRED_REEVALUATION
            if lockout_expiry_reevaluation or state.deferred_command is desired_command
            else SourceControlReason.NORMAL_DEMAND
        )
        updated = replace(
            state,
            logical_demand=desired_command,
            deferred_command=None,
            deferred_reason=None,
            next_reevaluation_deadline=None,
            safety_bypassed_lockout=False,
            last_evaluated_at=now,
        )
        return SourceControlAssessment(
            state=updated,
            outcome=SourceControlOutcome.DISPATCH,
            reason=reason,
            active_lockout=active_lockout,
            lockout_deadline=deadline,
            safety_bypassed_lockout=False,
        )

    def record_dispatched(
        self,
        assessment: SourceControlAssessment,
        *,
        dispatched_at: datetime,
        safety_command: bool,
    ) -> SourceControlState:
        _aware(dispatched_at, "dispatched_at")
        action = assessment.state.logical_demand
        if action is None:
            raise ValueError("dispatch assessment requires logical demand")
        if assessment.outcome is not SourceControlOutcome.DISPATCH:
            raise ValueError("only a dispatch assessment can be recorded")
        minimum_on_deadline = (
            dispatched_at + self.minimum_on_time
            if action is HeatingAction.ENABLE_HEATING and self.minimum_on_time > timedelta(0)
            else None
        )
        minimum_off_deadline = (
            dispatched_at + self.minimum_off_time
            if action is HeatingAction.DISABLE_HEATING and self.minimum_off_time > timedelta(0)
            else None
        )
        return replace(
            assessment.state,
            phase=_settled_phase(action),
            last_dispatched_command=action,
            last_dispatch_timestamp=dispatched_at,
            minimum_on_deadline=minimum_on_deadline,
            minimum_off_deadline=minimum_off_deadline,
            deferred_command=None,
            deferred_reason=None,
            next_reevaluation_deadline=None,
            last_normal_command_dispatch=(
                assessment.state.last_normal_command_dispatch if safety_command else dispatched_at
            ),
            safety_bypassed_lockout=assessment.safety_bypassed_lockout,
            last_evaluated_at=dispatched_at,
        )

    @staticmethod
    def stopped_state(
        current_state: SourceControlState | None,
        *,
        now: datetime,
    ) -> SourceControlState:
        _aware(now, "now")
        state = current_state or SourceControlPolicy(
            minimum_on_time=timedelta(0),
            minimum_off_time=timedelta(0),
        ).initial_state(now)
        return replace(
            state,
            phase=SourceControlPhase.STOPPED,
            deferred_command=None,
            deferred_reason=None,
            next_reevaluation_deadline=None,
            last_evaluated_at=now,
        )

    @staticmethod
    def fatal_state(
        current_state: SourceControlState | None,
        *,
        now: datetime,
    ) -> SourceControlState:
        _aware(now, "now")
        state = current_state or SourceControlPolicy(
            minimum_on_time=timedelta(0),
            minimum_off_time=timedelta(0),
        ).initial_state(now)
        return replace(
            state,
            phase=SourceControlPhase.FATAL_ERROR,
            minimum_on_deadline=None,
            minimum_off_deadline=None,
            deferred_command=None,
            deferred_reason=None,
            next_reevaluation_deadline=None,
            safety_bypassed_lockout=True,
            last_evaluated_at=now,
        )

    @staticmethod
    def _active_lockout(
        state: SourceControlState,
        now: datetime,
    ) -> tuple[ActiveLockoutType | None, datetime | None]:
        if (
            state.last_dispatched_command is HeatingAction.ENABLE_HEATING
            and state.minimum_on_deadline is not None
            and now < state.minimum_on_deadline
        ):
            return ActiveLockoutType.MINIMUM_ON, state.minimum_on_deadline
        if (
            state.last_dispatched_command is HeatingAction.DISABLE_HEATING
            and state.minimum_off_deadline is not None
            and now < state.minimum_off_deadline
        ):
            return ActiveLockoutType.MINIMUM_OFF, state.minimum_off_deadline
        return None, None

    def _blocking_lockout(
        self,
        state: SourceControlState,
        desired_command: HeatingAction,
        now: datetime,
    ) -> tuple[ActiveLockoutType | None, datetime | None]:
        active, deadline = self._active_lockout(state, now)
        if active is ActiveLockoutType.MINIMUM_ON and desired_command is HeatingAction.DISABLE_HEATING:
            return active, deadline
        if active is ActiveLockoutType.MINIMUM_OFF and desired_command is HeatingAction.ENABLE_HEATING:
            return active, deadline
        return None, None


def _settled_phase(action: HeatingAction) -> SourceControlPhase:
    return (
        SourceControlPhase.HEATING_REQUESTED
        if action is HeatingAction.ENABLE_HEATING
        else SourceControlPhase.HEATING_NOT_REQUESTED
    )


def _non_negative_duration(value: timedelta, label: str) -> timedelta:
    if not isinstance(value, timedelta):
        raise TypeError(f"{label} must be a timedelta")
    if value < timedelta(0):
        raise ValueError(f"{label} must not be negative")
    return value


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
