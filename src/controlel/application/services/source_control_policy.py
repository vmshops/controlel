from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from controlel.application.state.source_control_state import (
    ActiveLockoutType,
    DetailedSourceControlPhase,
    SourceCommandOutcome,
    SourceControlPhase,
    SourceControlReason,
    SourceControlState,
)
from controlel.domain.commands.heating_action import HeatingAction


class SourceControlOutcome(StrEnum):
    DISPATCH = "dispatch"
    SUPPRESS_DUPLICATE = "suppress_duplicate"
    DEFER = "defer"


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
        self.minimum_on_time = _non_negative_duration(minimum_on_time, "minimum_on_time")
        self.minimum_off_time = _non_negative_duration(minimum_off_time, "minimum_off_time")

    def initial_state(self, now: datetime) -> SourceControlState:
        _aware(now, "now")
        return SourceControlState(
            phase=SourceControlPhase.IDLE,
            detailed_phase=DetailedSourceControlPhase.INDETERMINATE,
            aggregate_demand=None,
            last_dispatched_command=None,
            last_successful_enable_dispatch=None,
            last_successful_disable_dispatch=None,
            earliest_next_enable_time=None,
            earliest_next_disable_time=None,
            active_lockout_type=None,
            active_lockout_deadline=None,
            deferred_command=None,
            deferred_reason=None,
            deferred_since=None,
            deferred_deadline=None,
            last_normal_command_dispatch=None,
            safety_bypass_active=False,
            last_requested_command=None,
            last_command_outcome=SourceCommandOutcome.NONE,
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

        active_lockout, lockout_deadline = self._protection_boundary(state, now)
        blocking_lockout, blocking_deadline = self._blocking_lockout(state, desired_command, now)
        bypass = (
            safety_command
            and desired_command is HeatingAction.DISABLE_HEATING
            and state.last_dispatched_command is HeatingAction.ENABLE_HEATING
            and blocking_lockout is ActiveLockoutType.MINIMUM_ON
        )
        if bypass:
            updated = _clear_deferred(
                state,
                detailed_phase=DetailedSourceControlPhase.SAFETY_OVERRIDE,
                aggregate_demand=desired_command,
                safety_bypass_active=True,
                last_requested_command=desired_command,
                last_command_outcome=SourceCommandOutcome.REQUESTED,
                last_evaluated_at=now,
            )
            return SourceControlAssessment(
                state=updated,
                outcome=SourceControlOutcome.DISPATCH,
                reason=SourceControlReason.SAFETY_DISABLE_BYPASSED_LOCKOUT,
                active_lockout=active_lockout,
                lockout_deadline=lockout_deadline,
                safety_bypassed_lockout=True,
            )

        if state.last_dispatched_command is desired_command:
            cancelled = state.deferred_command is not None
            updated = _clear_deferred(
                state,
                phase=_settled_phase(desired_command),
                detailed_phase=_detailed_settled_phase(desired_command),
                aggregate_demand=desired_command,
                safety_bypass_active=False,
                last_requested_command=desired_command,
                last_command_outcome=SourceCommandOutcome.SUPPRESSED_DUPLICATE,
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
                lockout_deadline=lockout_deadline,
                safety_bypassed_lockout=False,
            )

        if blocking_lockout is not None and blocking_deadline is not None:
            reason = (
                SourceControlReason.MINIMUM_ON_TIME_ACTIVE
                if blocking_lockout is ActiveLockoutType.MINIMUM_ON
                else SourceControlReason.MINIMUM_OFF_TIME_ACTIVE
            )
            deferred_since = (
                state.deferred_since
                if state.deferred_command is desired_command and state.deferred_since is not None
                else now
            )
            updated = replace(
                state,
                phase=(
                    SourceControlPhase.DEFERRED_DISABLE
                    if desired_command is HeatingAction.DISABLE_HEATING
                    else SourceControlPhase.DEFERRED_ENABLE
                ),
                detailed_phase=(
                    DetailedSourceControlPhase.HEATING_NOT_REQUESTED_WAITING_MINIMUM_ON
                    if desired_command is HeatingAction.DISABLE_HEATING
                    else DetailedSourceControlPhase.HEATING_REQUESTED_WAITING_MINIMUM_OFF
                ),
                aggregate_demand=desired_command,
                active_lockout_type=blocking_lockout,
                active_lockout_deadline=blocking_deadline,
                deferred_command=desired_command,
                deferred_reason=reason,
                deferred_since=deferred_since,
                deferred_deadline=blocking_deadline,
                safety_bypass_active=False,
                last_requested_command=desired_command,
                last_command_outcome=SourceCommandOutcome.DEFERRED,
                last_evaluated_at=now,
            )
            return SourceControlAssessment(
                state=updated,
                outcome=SourceControlOutcome.DEFER,
                reason=reason,
                active_lockout=active_lockout,
                lockout_deadline=lockout_deadline,
                safety_bypassed_lockout=False,
            )

        reason = (
            SourceControlReason.LOCKOUT_EXPIRED_REEVALUATION
            if lockout_expiry_reevaluation or state.deferred_command is desired_command
            else SourceControlReason.NORMAL_DEMAND
        )
        updated = _clear_deferred(
            state,
            detailed_phase=_detailed_allowed_phase(desired_command),
            aggregate_demand=desired_command,
            safety_bypass_active=False,
            last_requested_command=desired_command,
            last_command_outcome=SourceCommandOutcome.REQUESTED,
            last_evaluated_at=now,
        )
        return SourceControlAssessment(
            state=updated,
            outcome=SourceControlOutcome.DISPATCH,
            reason=reason,
            active_lockout=active_lockout,
            lockout_deadline=lockout_deadline,
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
        action = assessment.state.aggregate_demand
        if action is None:
            raise ValueError("dispatch assessment requires aggregate demand")
        if assessment.outcome is not SourceControlOutcome.DISPATCH:
            raise ValueError("only a dispatch assessment can be recorded")
        enable_dispatch = (
            dispatched_at
            if action is HeatingAction.ENABLE_HEATING
            else assessment.state.last_successful_enable_dispatch
        )
        disable_dispatch = (
            dispatched_at
            if action is HeatingAction.DISABLE_HEATING
            else assessment.state.last_successful_disable_dispatch
        )
        return _clear_deferred(
            assessment.state,
            phase=_settled_phase(action),
            detailed_phase=(
                DetailedSourceControlPhase.SAFETY_OVERRIDE
                if assessment.safety_bypassed_lockout
                else _detailed_settled_phase(action)
            ),
            last_dispatched_command=action,
            last_successful_enable_dispatch=enable_dispatch,
            last_successful_disable_dispatch=disable_dispatch,
            earliest_next_enable_time=(
                dispatched_at + self.minimum_off_time
                if action is HeatingAction.DISABLE_HEATING and self.minimum_off_time > timedelta(0)
                else None
            ),
            earliest_next_disable_time=(
                dispatched_at + self.minimum_on_time
                if action is HeatingAction.ENABLE_HEATING and self.minimum_on_time > timedelta(0)
                else None
            ),
            last_normal_command_dispatch=(
                assessment.state.last_normal_command_dispatch if safety_command else dispatched_at
            ),
            safety_bypass_active=assessment.safety_bypassed_lockout,
            last_requested_command=action,
            last_command_outcome=SourceCommandOutcome.DISPATCHED,
            last_evaluated_at=dispatched_at,
        )

    @staticmethod
    def record_failed(
        assessment: SourceControlAssessment,
        *,
        failed_at: datetime,
    ) -> SourceControlState:
        """Record a failed requested dispatch without fabricating success evidence."""

        _aware(failed_at, "failed_at")
        if assessment.outcome is not SourceControlOutcome.DISPATCH:
            raise ValueError("only a dispatch assessment can fail")
        return replace(
            assessment.state,
            last_command_outcome=SourceCommandOutcome.FAILED,
            last_evaluated_at=failed_at,
        )

    @staticmethod
    def record_suppressed_duplicate(
        assessment: SourceControlAssessment,
        *,
        evaluated_at: datetime,
    ) -> SourceControlState:
        """Record dispatcher-level duplicate suppression without starting protection."""

        _aware(evaluated_at, "evaluated_at")
        return replace(
            assessment.state,
            last_command_outcome=SourceCommandOutcome.SUPPRESSED_DUPLICATE,
            last_evaluated_at=evaluated_at,
        )

    @staticmethod
    def stopped_state(current_state: SourceControlState | None, *, now: datetime) -> SourceControlState:
        _aware(now, "now")
        state = current_state or SourceControlPolicy(
            minimum_on_time=timedelta(0),
            minimum_off_time=timedelta(0),
        ).initial_state(now)
        return _clear_deferred(
            state,
            phase=SourceControlPhase.STOPPED,
            detailed_phase=DetailedSourceControlPhase.STOPPED,
            safety_bypass_active=False,
            last_evaluated_at=now,
        )

    @staticmethod
    def fatal_state(current_state: SourceControlState | None, *, now: datetime) -> SourceControlState:
        _aware(now, "now")
        state = current_state or SourceControlPolicy(
            minimum_on_time=timedelta(0),
            minimum_off_time=timedelta(0),
        ).initial_state(now)
        return _clear_deferred(
            state,
            phase=SourceControlPhase.FATAL_ERROR,
            detailed_phase=DetailedSourceControlPhase.FATAL_ERROR,
            earliest_next_enable_time=None,
            earliest_next_disable_time=None,
            safety_bypass_active=True,
            last_evaluated_at=now,
        )

    @staticmethod
    def _protection_boundary(
        state: SourceControlState,
        now: datetime,
    ) -> tuple[ActiveLockoutType | None, datetime | None]:
        if (
            state.last_dispatched_command is HeatingAction.ENABLE_HEATING
            and state.earliest_next_disable_time is not None
            and now < state.earliest_next_disable_time
        ):
            return ActiveLockoutType.MINIMUM_ON, state.earliest_next_disable_time
        if (
            state.last_dispatched_command is HeatingAction.DISABLE_HEATING
            and state.earliest_next_enable_time is not None
            and now < state.earliest_next_enable_time
        ):
            return ActiveLockoutType.MINIMUM_OFF, state.earliest_next_enable_time
        return None, None

    def _blocking_lockout(
        self,
        state: SourceControlState,
        desired_command: HeatingAction,
        now: datetime,
    ) -> tuple[ActiveLockoutType | None, datetime | None]:
        boundary, deadline = self._protection_boundary(state, now)
        if boundary is ActiveLockoutType.MINIMUM_ON and desired_command is HeatingAction.DISABLE_HEATING:
            return boundary, deadline
        if boundary is ActiveLockoutType.MINIMUM_OFF and desired_command is HeatingAction.ENABLE_HEATING:
            return boundary, deadline
        return None, None


def _clear_deferred(state: SourceControlState, **changes: object) -> SourceControlState:
    return replace(
        state,
        active_lockout_type=None,
        active_lockout_deadline=None,
        deferred_command=None,
        deferred_reason=None,
        deferred_since=None,
        deferred_deadline=None,
        **changes,
    )


def _detailed_allowed_phase(action: HeatingAction) -> DetailedSourceControlPhase:
    return (
        DetailedSourceControlPhase.HEATING_REQUESTED_AND_ALLOWED
        if action is HeatingAction.ENABLE_HEATING
        else DetailedSourceControlPhase.HEATING_NOT_REQUESTED
    )


def _settled_phase(action: HeatingAction) -> SourceControlPhase:
    return (
        SourceControlPhase.HEATING_REQUESTED
        if action is HeatingAction.ENABLE_HEATING
        else SourceControlPhase.HEATING_NOT_REQUESTED
    )


def _detailed_settled_phase(action: HeatingAction) -> DetailedSourceControlPhase:
    return (
        DetailedSourceControlPhase.HEATING_ACTIVE_REQUEST
        if action is HeatingAction.ENABLE_HEATING
        else DetailedSourceControlPhase.HEATING_NOT_REQUESTED
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
