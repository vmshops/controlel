from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.services.source_control_policy import (
    ActiveLockoutType,
    SourceControlOutcome,
    SourceControlPolicy,
)
from controlel.application.state.source_control_state import (
    SourceCommandOutcome,
    SourceControlReason,
)
from controlel.domain.commands.heating_action import HeatingAction

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def policy(
    *,
    minimum_on: timedelta = timedelta(minutes=10),
    minimum_off: timedelta = timedelta(minutes=5),
) -> SourceControlPolicy:
    return SourceControlPolicy(
        minimum_on_time=minimum_on,
        minimum_off_time=minimum_off,
    )


def dispatch(
    configured: SourceControlPolicy,
    action: HeatingAction,
    *,
    state=None,
    now: datetime = NOW,
    safety: bool = False,
):
    assessment = configured.evaluate(
        desired_command=action,
        now=now,
        current_state=state,
        safety_command=safety,
    )
    assert assessment.outcome is SourceControlOutcome.DISPATCH
    return configured.record_dispatched(
        assessment,
        dispatched_at=now,
        safety_command=safety,
    )


def test_minimum_on_blocks_disable_until_exact_deadline() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.ENABLE_HEATING)

    blocked = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=9),
        current_state=state,
    )
    boundary = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=10),
        current_state=blocked.state,
        lockout_expiry_reevaluation=True,
    )

    assert blocked.outcome is SourceControlOutcome.DEFER
    assert blocked.active_lockout is ActiveLockoutType.MINIMUM_ON
    assert blocked.state.next_reevaluation_deadline == NOW + timedelta(minutes=10)
    assert boundary.outcome is SourceControlOutcome.DISPATCH
    assert boundary.reason is SourceControlReason.LOCKOUT_EXPIRED_REEVALUATION


def test_minimum_off_blocks_enable_and_safety_enable_does_not_bypass() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.DISABLE_HEATING)

    normal = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW + timedelta(minutes=1),
        current_state=state,
    )
    safety = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW + timedelta(minutes=2),
        current_state=normal.state,
        safety_command=True,
    )

    assert normal.outcome is SourceControlOutcome.DEFER
    assert safety.outcome is SourceControlOutcome.DEFER
    assert safety.active_lockout is ActiveLockoutType.MINIMUM_OFF


def test_safety_disable_bypasses_minimum_on() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.ENABLE_HEATING)

    assessment = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=1),
        current_state=state,
        safety_command=True,
    )

    assert assessment.outcome is SourceControlOutcome.DISPATCH
    assert assessment.safety_bypassed_lockout is True
    assert assessment.reason is SourceControlReason.SAFETY_DISABLE_BYPASSED_LOCKOUT


def test_changed_demand_cancels_deferred_command_and_timer() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.ENABLE_HEATING)
    deferred = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=1),
        current_state=state,
    )

    cancelled = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW + timedelta(minutes=2),
        current_state=deferred.state,
    )

    assert cancelled.outcome is SourceControlOutcome.SUPPRESS_DUPLICATE
    assert cancelled.reason is SourceControlReason.DEFERRED_COMMAND_CANCELLED
    assert cancelled.state.deferred_command is None
    assert cancelled.state.next_reevaluation_deadline is None


def test_duplicate_inputs_do_not_create_deadlines() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.DISABLE_HEATING)

    duplicate = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(seconds=1),
        current_state=state,
    )

    assert duplicate.outcome is SourceControlOutcome.SUPPRESS_DUPLICATE
    assert duplicate.reason is SourceControlReason.DUPLICATE_COMMAND
    assert duplicate.state.next_reevaluation_deadline is None
    assert duplicate.state.last_dispatch_timestamp == NOW
    assert duplicate.state.minimum_off_deadline == NOW + timedelta(minutes=5)


def test_only_successfully_recorded_dispatch_starts_minimum_timer() -> None:
    configured = policy()
    assessment = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW,
        current_state=None,
    )

    assert assessment.outcome is SourceControlOutcome.DISPATCH
    assert assessment.state.last_dispatch_timestamp is None
    assert assessment.state.minimum_on_deadline is None

    recorded = configured.record_dispatched(
        assessment,
        dispatched_at=NOW,
        safety_command=False,
    )

    assert recorded.last_dispatch_timestamp == NOW
    assert recorded.minimum_on_deadline == NOW + timedelta(minutes=10)
    assert recorded.minimum_off_deadline is None


def test_zero_minimum_times_preserve_immediate_legacy_switching() -> None:
    configured = policy(minimum_on=timedelta(0), minimum_off=timedelta(0))
    state = dispatch(configured, HeatingAction.ENABLE_HEATING)

    assessment = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW,
        current_state=state,
    )

    assert assessment.outcome is SourceControlOutcome.DISPATCH
    assert assessment.active_lockout is None


def test_stop_clears_deferred_deadline_and_stale_state_is_inert() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.ENABLE_HEATING)
    deferred = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=1),
        current_state=state,
    )

    stopped = configured.stopped_state(
        deferred.state,
        now=NOW + timedelta(minutes=2),
    )

    assert stopped.phase.value == "stopped"
    assert stopped.deferred_command is None
    assert stopped.next_reevaluation_deadline is None


def test_timestamps_must_be_aware_and_monotonic() -> None:
    configured = policy()
    with pytest.raises(ValueError, match="timezone-aware"):
        configured.initial_state(NOW.replace(tzinfo=None))

    state = dispatch(configured, HeatingAction.ENABLE_HEATING)
    with pytest.raises(ValueError, match="must not regress"):
        configured.evaluate(
            desired_command=HeatingAction.DISABLE_HEATING,
            now=NOW - timedelta(seconds=1),
            current_state=state,
        )


def test_passive_enable_boundary_is_not_an_active_lockout_or_deferred_command() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.DISABLE_HEATING)

    assert state.earliest_next_enable_time == NOW + timedelta(minutes=5)
    assert state.active_lockout_type is None
    assert state.active_lockout_deadline is None
    assert state.deferred_command is None
    assert state.deferred_deadline is None


def test_enable_before_passive_boundary_creates_truthful_lockout_and_deferred_snapshot() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.DISABLE_HEATING)
    blocked_at = NOW + timedelta(minutes=1)

    blocked = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=blocked_at,
        current_state=state,
    )

    assert blocked.state.phase.value == "heating_requested_waiting_minimum_off"
    assert blocked.state.active_lockout_type is ActiveLockoutType.MINIMUM_OFF
    assert blocked.state.active_lockout_deadline == NOW + timedelta(minutes=5)
    assert blocked.state.deferred_command is HeatingAction.ENABLE_HEATING
    assert blocked.state.deferred_since == blocked_at
    assert blocked.state.deferred_deadline == NOW + timedelta(minutes=5)


def test_cleared_demand_cancels_enable_but_retains_passive_boundary() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.DISABLE_HEATING)
    blocked = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW + timedelta(minutes=1),
        current_state=state,
    )

    cleared = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=2),
        current_state=blocked.state,
    )

    assert cleared.state.active_lockout_type is None
    assert cleared.state.deferred_command is None
    assert cleared.state.earliest_next_enable_time == NOW + timedelta(minutes=5)


def test_deadline_reevaluation_dispatches_current_enable_once_and_clears_deferred_state() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.DISABLE_HEATING)
    blocked = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW + timedelta(minutes=1),
        current_state=state,
    )
    deadline = NOW + timedelta(minutes=5)

    allowed = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=deadline,
        current_state=blocked.state,
        lockout_expiry_reevaluation=True,
    )
    recorded = configured.record_dispatched(
        allowed,
        dispatched_at=deadline,
        safety_command=False,
    )
    duplicate = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=deadline,
        current_state=recorded,
    )

    assert allowed.outcome is SourceControlOutcome.DISPATCH
    assert recorded.last_successful_enable_dispatch == deadline
    assert recorded.active_lockout_type is None
    assert recorded.deferred_command is None
    assert duplicate.outcome is SourceControlOutcome.SUPPRESS_DUPLICATE


def test_passive_disable_boundary_is_not_active_until_disable_is_requested() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.ENABLE_HEATING)

    assert state.earliest_next_disable_time == NOW + timedelta(minutes=10)
    assert state.active_lockout_type is None
    assert state.deferred_command is None

    blocked = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=1),
        current_state=state,
    )
    assert blocked.state.phase.value == "heating_not_requested_waiting_minimum_on"
    assert blocked.state.active_lockout_type is ActiveLockoutType.MINIMUM_ON
    assert blocked.state.deferred_command is HeatingAction.DISABLE_HEATING


def test_returning_demand_cancels_deferred_disable_without_changing_successful_enable() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.ENABLE_HEATING)
    blocked = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=1),
        current_state=state,
    )

    returned = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW + timedelta(minutes=2),
        current_state=blocked.state,
    )

    assert returned.state.deferred_command is None
    assert returned.state.active_lockout_type is None
    assert returned.state.last_successful_enable_dispatch == NOW
    assert returned.state.earliest_next_disable_time == NOW + timedelta(minutes=10)


def test_safety_disable_bypass_clears_false_lockout_claim_after_success() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.ENABLE_HEATING)
    safety = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=1),
        current_state=state,
        safety_command=True,
    )
    recorded = configured.record_dispatched(
        safety,
        dispatched_at=NOW + timedelta(minutes=1),
        safety_command=True,
    )

    assert safety.active_lockout is None
    assert recorded.phase.value == "safety_override"
    assert recorded.safety_bypass_active is True
    assert recorded.active_lockout_type is None
    assert recorded.deferred_command is None
    assert recorded.last_successful_disable_dispatch == NOW + timedelta(minutes=1)


def test_duplicate_or_unrecorded_dispatch_never_fabricates_success_timestamps() -> None:
    configured = policy()
    state = dispatch(configured, HeatingAction.DISABLE_HEATING)
    duplicate = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(seconds=1),
        current_state=state,
    )
    fresh = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW + timedelta(minutes=5),
        current_state=duplicate.state,
    )

    assert duplicate.state.last_successful_disable_dispatch == NOW
    assert duplicate.state.last_successful_enable_dispatch is None
    assert fresh.state.last_successful_disable_dispatch == NOW
    assert fresh.state.last_successful_enable_dispatch is None

    failed = configured.record_failed(fresh, failed_at=NOW + timedelta(minutes=5))
    assert failed.last_command_outcome is SourceCommandOutcome.FAILED
    assert failed.last_successful_disable_dispatch == NOW
    assert failed.last_successful_enable_dispatch is None


def test_restart_initial_state_has_no_inferred_dispatch_or_protection_history() -> None:
    state = policy().initial_state(NOW)

    assert state.phase.value == "indeterminate"
    assert state.last_dispatched_command is None
    assert state.last_successful_enable_dispatch is None
    assert state.last_successful_disable_dispatch is None
    assert state.earliest_next_enable_time is None
    assert state.earliest_next_disable_time is None
