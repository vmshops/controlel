from datetime import UTC, datetime, timedelta

from controlel.application.services.source_reconciliation_policy import (
    SourceReconciliationPolicy,
)
from controlel.application.state.source_reconciliation_state import (
    SourceReconciliationReason,
    SourceReconciliationStatus,
)
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.source_control import (
    ReportedSourceEvidence,
    ReportedSourceState,
    SourceOwnership,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
HOLD = timedelta(minutes=5)
RETRY = timedelta(seconds=30)


def _policy() -> SourceReconciliationPolicy:
    return SourceReconciliationPolicy(
        unknown_transition_hold=HOLD,
        correction_retry_interval=RETRY,
    )


def _reported(state: ReportedSourceState, *, transition_at: datetime | None = None) -> ReportedSourceEvidence:
    return ReportedSourceEvidence(
        state=state,
        observed_at=NOW,
        transition_at=transition_at,
    )


def test_unknown_transition_age_holds_then_requires_corrective_off() -> None:
    policy = _policy()
    first = policy.evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.DISABLE_HEATING,
        last_successful_command=HeatingAction.DISABLE_HEATING,
        reported=_reported(ReportedSourceState.ENABLED),
        current_state=None,
        now=NOW,
    )

    assert first.status is SourceReconciliationStatus.DRIFT_HOLDING
    assert first.reason is SourceReconciliationReason.UNKNOWN_TRANSITION_AGE_HOLD
    assert first.corrective_command is None
    assert first.next_reevaluation_at == NOW + HOLD

    due = policy.evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.DISABLE_HEATING,
        last_successful_command=HeatingAction.DISABLE_HEATING,
        reported=_reported(ReportedSourceState.ENABLED),
        current_state=first.state,
        now=NOW + HOLD,
    )

    assert due.status is SourceReconciliationStatus.CORRECTION_REQUIRED
    assert due.reason is SourceReconciliationReason.CONSERVATIVE_HOLD_EXPIRED
    assert due.corrective_command is HeatingAction.DISABLE_HEATING
    assert due.next_reevaluation_at is None


def test_known_transition_drift_is_immediately_delegated_to_source_policy() -> None:
    assessment = _policy().evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.DISABLE_HEATING,
        last_successful_command=None,
        reported=_reported(ReportedSourceState.ENABLED, transition_at=NOW - timedelta(minutes=1)),
        current_state=None,
        now=NOW,
    )

    assert assessment.status is SourceReconciliationStatus.CORRECTION_REQUIRED
    assert assessment.reason is SourceReconciliationReason.KNOWN_TRANSITION_DRIFT
    assert assessment.corrective_command is HeatingAction.DISABLE_HEATING


def test_external_ownership_observes_but_never_corrects() -> None:
    assessment = _policy().evaluate(
        ownership=SourceOwnership.EXTERNAL,
        desired_command=HeatingAction.DISABLE_HEATING,
        last_successful_command=HeatingAction.DISABLE_HEATING,
        reported=_reported(ReportedSourceState.ENABLED),
        current_state=None,
        now=NOW,
    )

    assert assessment.status is SourceReconciliationStatus.OBSERVED_EXTERNAL
    assert assessment.reason is SourceReconciliationReason.EXTERNAL_OWNERSHIP
    assert assessment.corrective_command is None
    assert assessment.next_reevaluation_at is None


def test_successful_correction_waits_for_report_and_repeated_events_do_not_storm() -> None:
    policy = _policy()
    required = policy.evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.DISABLE_HEATING,
        last_successful_command=None,
        reported=_reported(ReportedSourceState.ENABLED, transition_at=NOW - HOLD),
        current_state=None,
        now=NOW,
    )
    pending = policy.record_dispatched(required, dispatched_at=NOW)

    repeated = policy.evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.DISABLE_HEATING,
        last_successful_command=HeatingAction.DISABLE_HEATING,
        reported=_reported(ReportedSourceState.ENABLED, transition_at=NOW - HOLD),
        current_state=pending,
        now=NOW + timedelta(seconds=1),
    )

    assert repeated.status is SourceReconciliationStatus.CORRECTION_PENDING
    assert repeated.corrective_command is None
    assert repeated.next_reevaluation_at == NOW + RETRY

    agreed = policy.evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.DISABLE_HEATING,
        last_successful_command=HeatingAction.DISABLE_HEATING,
        reported=ReportedSourceEvidence(
            state=ReportedSourceState.DISABLED,
            observed_at=NOW + timedelta(seconds=2),
        ),
        current_state=repeated.state,
        now=NOW + timedelta(seconds=2),
    )
    assert agreed.status is SourceReconciliationStatus.AGREED
    assert agreed.state.drift_detected_at is None


def test_failed_correction_remains_retryable_after_bounded_delay() -> None:
    policy = _policy()
    required = policy.evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.ENABLE_HEATING,
        last_successful_command=HeatingAction.ENABLE_HEATING,
        reported=_reported(ReportedSourceState.DISABLED, transition_at=NOW - HOLD),
        current_state=None,
        now=NOW,
    )
    failed = policy.record_failed(required, failed_at=NOW)

    waiting = policy.evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.ENABLE_HEATING,
        last_successful_command=HeatingAction.ENABLE_HEATING,
        reported=_reported(ReportedSourceState.DISABLED, transition_at=NOW - HOLD),
        current_state=failed,
        now=NOW + timedelta(seconds=1),
    )
    retry = policy.evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.ENABLE_HEATING,
        last_successful_command=HeatingAction.ENABLE_HEATING,
        reported=_reported(ReportedSourceState.DISABLED, transition_at=NOW - HOLD),
        current_state=waiting.state,
        now=NOW + RETRY,
    )

    assert waiting.corrective_command is None
    assert waiting.reason is SourceReconciliationReason.CORRECTIVE_COMMAND_FAILED_RETRY_WAIT
    assert retry.corrective_command is HeatingAction.ENABLE_HEATING
    assert retry.reason is SourceReconciliationReason.CORRECTIVE_RETRY_DUE


def test_unknown_expected_and_unavailable_report_remain_explicit() -> None:
    policy = _policy()
    unknown_expected = policy.evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=None,
        last_successful_command=None,
        reported=_reported(ReportedSourceState.ENABLED),
        current_state=None,
        now=NOW,
    )
    unavailable = policy.evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.DISABLE_HEATING,
        last_successful_command=None,
        reported=_reported(ReportedSourceState.UNAVAILABLE),
        current_state=unknown_expected.state,
        now=NOW,
    )

    assert unknown_expected.status is SourceReconciliationStatus.EXPECTED_UNKNOWN
    assert unavailable.status is SourceReconciliationStatus.REPORTED_INDETERMINATE
