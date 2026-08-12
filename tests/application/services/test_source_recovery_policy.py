from datetime import UTC, datetime, timedelta

from controlel.application.services.source_recovery_policy import (
    DEFAULT_RECOVERY_WINDOW,
    SourceRecoveryPolicy,
)
from controlel.application.state.source_recovery_state import (
    SourceRecoveryReason,
    SourceRecoveryStatus,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def test_recovery_waits_for_demand_and_reported_source_readiness() -> None:
    policy = SourceRecoveryPolicy(recovery_window=timedelta(seconds=30))
    started = policy.begin(now=NOW)

    waiting = policy.evaluate(
        current_state=started,
        demand_known=True,
        reported_source_known=False,
        now=NOW + timedelta(seconds=1),
    )

    assert waiting.status is SourceRecoveryStatus.WAITING
    assert waiting.reason is SourceRecoveryReason.WAITING_FOR_REPORTED_SOURCE
    assert waiting.blocks_source_commands is True
    assert waiting.deadline == NOW + timedelta(seconds=30)


def test_recovery_completes_immediately_when_required_evidence_is_ready() -> None:
    policy = SourceRecoveryPolicy()
    assessment = policy.evaluate(
        current_state=policy.begin(now=NOW),
        demand_known=True,
        reported_source_known=True,
        now=NOW + timedelta(seconds=1),
    )

    assert assessment.status is SourceRecoveryStatus.COMPLETE
    assert assessment.reason is SourceRecoveryReason.EVIDENCE_READY
    assert assessment.blocks_source_commands is False
    assert assessment.state.completed_at == NOW + timedelta(seconds=1)


def test_recovery_is_bounded_when_evidence_remains_unknown() -> None:
    policy = SourceRecoveryPolicy()
    started = policy.begin(now=NOW)
    assessment = policy.evaluate(
        current_state=started,
        demand_known=False,
        reported_source_known=False,
        now=NOW + DEFAULT_RECOVERY_WINDOW,
    )

    assert assessment.status is SourceRecoveryStatus.COMPLETE
    assert assessment.reason is SourceRecoveryReason.DEADLINE_ELAPSED_WITH_INCOMPLETE_EVIDENCE
    assert assessment.blocks_source_commands is False
    assert assessment.state.demand_known is False
    assert assessment.state.reported_source_known is False


def test_repeated_completed_recovery_does_not_reenter_waiting() -> None:
    policy = SourceRecoveryPolicy()
    complete = policy.evaluate(
        current_state=policy.begin(now=NOW),
        demand_known=True,
        reported_source_known=True,
        now=NOW + timedelta(seconds=1),
    )
    repeated = policy.evaluate(
        current_state=complete.state,
        demand_known=False,
        reported_source_known=False,
        now=NOW + timedelta(seconds=2),
    )

    assert repeated.state == complete.state
    assert repeated.blocks_source_commands is False
