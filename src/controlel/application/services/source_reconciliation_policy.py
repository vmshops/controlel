"""Pure assessment of desired and reported source-controller state."""

from dataclasses import replace
from datetime import datetime, timedelta

from controlel.application.state.source_reconciliation_state import (
    SourceReconciliationAssessment,
    SourceReconciliationReason,
    SourceReconciliationState,
    SourceReconciliationStatus,
)
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.source_control import (
    ReportedSourceEvidence,
    ReportedSourceState,
    SourceOwnership,
    TransitionHistoryKnowledge,
)

DEFAULT_UNKNOWN_TRANSITION_HOLD = timedelta(minutes=5)
DEFAULT_CORRECTION_RETRY_INTERVAL = timedelta(seconds=30)


class SourceReconciliationPolicy:
    """Classify drift and produce bounded corrective intent without dispatching."""

    def __init__(
        self,
        *,
        unknown_transition_hold: timedelta = DEFAULT_UNKNOWN_TRANSITION_HOLD,
        correction_retry_interval: timedelta = DEFAULT_CORRECTION_RETRY_INTERVAL,
    ) -> None:
        self.unknown_transition_hold = _non_negative(unknown_transition_hold, "unknown_transition_hold")
        self.correction_retry_interval = _positive(
            correction_retry_interval,
            "correction_retry_interval",
        )

    def evaluate(
        self,
        *,
        ownership: SourceOwnership,
        desired_command: HeatingAction | None,
        last_successful_command: HeatingAction | None,
        reported: ReportedSourceEvidence | None,
        current_state: SourceReconciliationState | None,
        now: datetime,
    ) -> SourceReconciliationAssessment:
        _aware(now, "now")
        if current_state is not None and now < current_state.last_evaluated_at:
            raise ValueError("reconciliation evaluation time must not regress")
        if not isinstance(ownership, SourceOwnership):
            raise TypeError("ownership must be a SourceOwnership")

        if ownership is SourceOwnership.EXTERNAL:
            return self._assessment(
                ownership,
                desired_command,
                last_successful_command,
                reported,
                SourceReconciliationStatus.OBSERVED_EXTERNAL,
                SourceReconciliationReason.EXTERNAL_OWNERSHIP,
                now,
            )
        if desired_command is None:
            return self._assessment(
                ownership,
                None,
                last_successful_command,
                reported,
                SourceReconciliationStatus.EXPECTED_UNKNOWN,
                SourceReconciliationReason.EXPECTED_STATE_UNKNOWN,
                now,
            )
        if reported is None or reported.state in {
            ReportedSourceState.UNKNOWN,
            ReportedSourceState.UNAVAILABLE,
        }:
            reason = (
                SourceReconciliationReason.REPORTED_STATE_UNAVAILABLE
                if reported is not None and reported.state is ReportedSourceState.UNAVAILABLE
                else SourceReconciliationReason.REPORTED_STATE_UNKNOWN
            )
            return self._assessment(
                ownership,
                desired_command,
                last_successful_command,
                reported,
                SourceReconciliationStatus.REPORTED_INDETERMINATE,
                reason,
                now,
            )

        reported_command = _command_for_report(reported.state)
        if reported_command is desired_command:
            return self._assessment(
                ownership,
                desired_command,
                last_successful_command,
                reported,
                SourceReconciliationStatus.AGREED,
                SourceReconciliationReason.REPORTED_STATE_AGREES,
                now,
            )

        same_drift = (
            current_state is not None
            and current_state.drift_detected_at is not None
            and current_state.desired_command is desired_command
            and current_state.reported is not None
            and current_state.reported.state is reported.state
        )
        same_reported_evidence = same_drift and current_state.reported == reported
        # A successful correction waits for new reported evidence; unrelated
        # evaluations must not turn unchanged mismatch into a periodic retry.
        if same_reported_evidence and current_state.status is SourceReconciliationStatus.CORRECTION_PENDING:
            return self._assessment(
                ownership,
                desired_command,
                last_successful_command,
                reported,
                SourceReconciliationStatus.CORRECTION_PENDING,
                SourceReconciliationReason.AWAITING_REPORTED_AGREEMENT,
                now,
                drift_detected_at=current_state.drift_detected_at,
                conservative_hold_deadline=current_state.conservative_hold_deadline,
                corrective_intent=current_state.corrective_intent,
            )
        if same_drift and current_state.next_reevaluation_at is not None and now < current_state.next_reevaluation_at:
            return self._assessment(
                ownership,
                desired_command,
                last_successful_command,
                reported,
                current_state.status,
                current_state.reason,
                now,
                drift_detected_at=current_state.drift_detected_at,
                conservative_hold_deadline=current_state.conservative_hold_deadline,
                corrective_intent=current_state.corrective_intent,
                next_reevaluation_at=current_state.next_reevaluation_at,
            )

        if same_drift and current_state.status is SourceReconciliationStatus.CORRECTION_PENDING:
            reason = SourceReconciliationReason.CORRECTIVE_RETRY_DUE
        elif same_drift and current_state.reason is SourceReconciliationReason.CORRECTIVE_COMMAND_FAILED_RETRY_WAIT:
            reason = SourceReconciliationReason.CORRECTIVE_RETRY_DUE
        elif same_drift and current_state.conservative_hold_deadline is not None:
            reason = SourceReconciliationReason.CONSERVATIVE_HOLD_EXPIRED
        elif reported.transition_history is TransitionHistoryKnowledge.KNOWN:
            reason = SourceReconciliationReason.KNOWN_TRANSITION_DRIFT
        elif self.unknown_transition_hold > timedelta(0):
            deadline = now + self.unknown_transition_hold
            return self._assessment(
                ownership,
                desired_command,
                last_successful_command,
                reported,
                SourceReconciliationStatus.DRIFT_HOLDING,
                SourceReconciliationReason.UNKNOWN_TRANSITION_AGE_HOLD,
                now,
                drift_detected_at=now,
                conservative_hold_deadline=deadline,
                next_reevaluation_at=deadline,
            )
        else:
            reason = SourceReconciliationReason.CONSERVATIVE_HOLD_EXPIRED

        return self._assessment(
            ownership,
            desired_command,
            last_successful_command,
            reported,
            SourceReconciliationStatus.CORRECTION_REQUIRED,
            reason,
            now,
            drift_detected_at=(current_state.drift_detected_at if same_drift else now),
            conservative_hold_deadline=(current_state.conservative_hold_deadline if same_drift else None),
            corrective_intent=desired_command,
        )

    def record_dispatched(
        self,
        assessment: SourceReconciliationAssessment,
        *,
        dispatched_at: datetime,
        corrective_command: HeatingAction | None = None,
    ) -> SourceReconciliationState:
        _aware(dispatched_at, "dispatched_at")
        command = corrective_command or assessment.corrective_command
        if command is None:
            raise ValueError("a corrective command is required before recording dispatch")
        return replace(
            assessment.state,
            status=SourceReconciliationStatus.CORRECTION_PENDING,
            reason=SourceReconciliationReason.AWAITING_REPORTED_AGREEMENT,
            corrective_intent=command,
            next_reevaluation_at=None,
            last_evaluated_at=dispatched_at,
        )

    def record_failed(
        self,
        assessment: SourceReconciliationAssessment,
        *,
        failed_at: datetime,
        corrective_command: HeatingAction | None = None,
    ) -> SourceReconciliationState:
        _aware(failed_at, "failed_at")
        command = corrective_command or assessment.corrective_command
        if command is None:
            raise ValueError("a corrective command is required before recording failure")
        return replace(
            assessment.state,
            status=SourceReconciliationStatus.DRIFT_HOLDING,
            reason=SourceReconciliationReason.CORRECTIVE_COMMAND_FAILED_RETRY_WAIT,
            corrective_intent=command,
            next_reevaluation_at=failed_at + self.correction_retry_interval,
            last_evaluated_at=failed_at,
        )

    @staticmethod
    def _assessment(
        ownership: SourceOwnership,
        desired_command: HeatingAction | None,
        last_successful_command: HeatingAction | None,
        reported: ReportedSourceEvidence | None,
        status: SourceReconciliationStatus,
        reason: SourceReconciliationReason,
        now: datetime,
        *,
        drift_detected_at: datetime | None = None,
        conservative_hold_deadline: datetime | None = None,
        corrective_intent: HeatingAction | None = None,
        next_reevaluation_at: datetime | None = None,
    ) -> SourceReconciliationAssessment:
        state = SourceReconciliationState(
            ownership=ownership,
            desired_command=desired_command,
            last_successful_command=last_successful_command,
            reported=reported,
            status=status,
            reason=reason,
            drift_detected_at=drift_detected_at,
            conservative_hold_deadline=conservative_hold_deadline,
            corrective_intent=corrective_intent,
            next_reevaluation_at=next_reevaluation_at,
            last_evaluated_at=now,
        )
        return SourceReconciliationAssessment(
            state=state,
            status=status,
            reason=reason,
            corrective_command=(
                corrective_intent if status is SourceReconciliationStatus.CORRECTION_REQUIRED else None
            ),
            next_reevaluation_at=next_reevaluation_at,
        )


def _command_for_report(state: ReportedSourceState) -> HeatingAction:
    return HeatingAction.ENABLE_HEATING if state is ReportedSourceState.ENABLED else HeatingAction.DISABLE_HEATING


def _non_negative(value: timedelta, label: str) -> timedelta:
    if not isinstance(value, timedelta):
        raise TypeError(f"{label} must be a timedelta")
    if value < timedelta(0):
        raise ValueError(f"{label} must not be negative")
    return value


def _positive(value: timedelta, label: str) -> timedelta:
    value = _non_negative(value, label)
    if value == timedelta(0):
        raise ValueError(f"{label} must be positive")
    return value


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
