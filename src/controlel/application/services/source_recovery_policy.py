"""Deterministic readiness/deadline policy for runtime reconstruction."""

from dataclasses import replace
from datetime import datetime, timedelta

from controlel.application.state.source_recovery_state import (
    SourceRecoveryAssessment,
    SourceRecoveryReason,
    SourceRecoveryState,
    SourceRecoveryStatus,
)

DEFAULT_RECOVERY_WINDOW = timedelta(seconds=30)


class SourceRecoveryPolicy:
    """Block source transitions until evidence is ready or a bounded deadline."""

    def __init__(self, *, recovery_window: timedelta = DEFAULT_RECOVERY_WINDOW) -> None:
        if not isinstance(recovery_window, timedelta):
            raise TypeError("recovery_window must be a timedelta")
        if recovery_window <= timedelta(0):
            raise ValueError("recovery_window must be positive")
        self.recovery_window = recovery_window

    def begin(self, *, now: datetime) -> SourceRecoveryState:
        _aware(now, "now")
        return SourceRecoveryState(
            status=SourceRecoveryStatus.WAITING,
            reason=SourceRecoveryReason.RECOVERY_STARTED,
            started_at=now,
            deadline=now + self.recovery_window,
            demand_known=False,
            reported_source_known=False,
            completed_at=None,
            last_evaluated_at=now,
        )

    def evaluate(
        self,
        *,
        current_state: SourceRecoveryState,
        demand_known: bool,
        reported_source_known: bool,
        now: datetime,
    ) -> SourceRecoveryAssessment:
        _aware(now, "now")
        if now < current_state.last_evaluated_at:
            raise ValueError("recovery evaluation time must not regress")
        if current_state.status is SourceRecoveryStatus.COMPLETE:
            return SourceRecoveryAssessment(
                state=current_state,
                status=current_state.status,
                reason=current_state.reason,
                blocks_source_commands=False,
                deadline=None,
            )
        if demand_known and reported_source_known:
            reason = SourceRecoveryReason.EVIDENCE_READY
        elif now >= current_state.deadline:
            reason = SourceRecoveryReason.DEADLINE_ELAPSED_WITH_INCOMPLETE_EVIDENCE
        else:
            reason = (
                SourceRecoveryReason.WAITING_FOR_DEMAND_AND_REPORTED_SOURCE
                if not demand_known and not reported_source_known
                else SourceRecoveryReason.WAITING_FOR_DEMAND
                if not demand_known
                else SourceRecoveryReason.WAITING_FOR_REPORTED_SOURCE
            )
            state = replace(
                current_state,
                reason=reason,
                demand_known=demand_known,
                reported_source_known=reported_source_known,
                last_evaluated_at=now,
            )
            return SourceRecoveryAssessment(
                state=state,
                status=state.status,
                reason=state.reason,
                blocks_source_commands=True,
                deadline=state.deadline,
            )

        state = replace(
            current_state,
            status=SourceRecoveryStatus.COMPLETE,
            reason=reason,
            demand_known=demand_known,
            reported_source_known=reported_source_known,
            completed_at=now,
            last_evaluated_at=now,
        )
        return SourceRecoveryAssessment(
            state=state,
            status=state.status,
            reason=state.reason,
            blocks_source_commands=False,
            deadline=None,
        )


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
