from datetime import UTC, datetime, timedelta

from controlel.application.services.source_control_policy import (
    ActiveLockoutType,
    SourceControlOutcome,
    SourceControlPolicy,
)
from controlel.application.state.source_control_state import (
    DetailedSourceControlPhase,
    SourceControlPhase,
)
from controlel.domain.commands.heating_action import HeatingAction

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def policy() -> SourceControlPolicy:
    return SourceControlPolicy(
        minimum_on_time=timedelta(minutes=10),
        minimum_off_time=timedelta(minutes=5),
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


def test_minimum_off_legacy_projection_and_precise_state_are_independent() -> None:
    configured = policy()
    disabled = dispatch(configured, HeatingAction.DISABLE_HEATING)

    duplicate = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=1),
        current_state=disabled,
    )
    blocked = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW + timedelta(minutes=2),
        current_state=duplicate.state,
    )
    cleared = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=3),
        current_state=blocked.state,
    )

    boundary = NOW + timedelta(minutes=5)
    assert disabled.phase is SourceControlPhase.HEATING_NOT_REQUESTED
    assert disabled.minimum_off_deadline == boundary
    assert disabled.earliest_next_enable_time == boundary
    assert disabled.active_lockout_type is None
    assert disabled.active_lockout_deadline is None

    assert duplicate.active_lockout is ActiveLockoutType.MINIMUM_OFF
    assert duplicate.lockout_deadline == boundary
    assert duplicate.state.active_lockout_type is None
    assert duplicate.state.deferred_command is None

    assert blocked.state.phase is SourceControlPhase.DEFERRED_ENABLE
    assert blocked.state.detailed_phase is DetailedSourceControlPhase.HEATING_REQUESTED_WAITING_MINIMUM_OFF
    assert blocked.active_lockout is ActiveLockoutType.MINIMUM_OFF
    assert blocked.lockout_deadline == boundary
    assert blocked.state.active_lockout_type is ActiveLockoutType.MINIMUM_OFF
    assert blocked.state.active_lockout_deadline == boundary
    assert blocked.state.deferred_command is HeatingAction.ENABLE_HEATING

    assert cleared.state.phase is SourceControlPhase.HEATING_NOT_REQUESTED
    assert cleared.active_lockout is ActiveLockoutType.MINIMUM_OFF
    assert cleared.lockout_deadline == boundary
    assert cleared.state.minimum_off_deadline == boundary
    assert cleared.state.earliest_next_enable_time == boundary
    assert cleared.state.active_lockout_type is None
    assert cleared.state.active_lockout_deadline is None
    assert cleared.state.deferred_command is None


def test_minimum_on_legacy_projection_and_precise_state_are_independent() -> None:
    configured = policy()
    enabled = dispatch(configured, HeatingAction.ENABLE_HEATING)

    duplicate = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW + timedelta(minutes=1),
        current_state=enabled,
    )
    blocked = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=2),
        current_state=duplicate.state,
    )
    returned = configured.evaluate(
        desired_command=HeatingAction.ENABLE_HEATING,
        now=NOW + timedelta(minutes=3),
        current_state=blocked.state,
    )

    boundary = NOW + timedelta(minutes=10)
    assert enabled.phase is SourceControlPhase.HEATING_REQUESTED
    assert enabled.minimum_on_deadline == boundary
    assert enabled.earliest_next_disable_time == boundary
    assert enabled.active_lockout_type is None
    assert enabled.active_lockout_deadline is None

    assert duplicate.active_lockout is ActiveLockoutType.MINIMUM_ON
    assert duplicate.lockout_deadline == boundary
    assert duplicate.state.active_lockout_type is None

    assert blocked.state.phase is SourceControlPhase.DEFERRED_DISABLE
    assert blocked.state.detailed_phase is DetailedSourceControlPhase.HEATING_NOT_REQUESTED_WAITING_MINIMUM_ON
    assert blocked.state.active_lockout_type is ActiveLockoutType.MINIMUM_ON
    assert blocked.state.active_lockout_deadline == boundary
    assert blocked.state.deferred_command is HeatingAction.DISABLE_HEATING

    assert returned.state.phase is SourceControlPhase.HEATING_REQUESTED
    assert returned.active_lockout is ActiveLockoutType.MINIMUM_ON
    assert returned.lockout_deadline == boundary
    assert returned.state.minimum_on_deadline == boundary
    assert returned.state.active_lockout_type is None
    assert returned.state.deferred_command is None


def test_startup_safety_fatal_and_restart_keep_legacy_projection() -> None:
    configured = policy()
    initial = configured.initial_state(NOW)

    assert initial.phase is SourceControlPhase.IDLE
    assert initial.detailed_phase is DetailedSourceControlPhase.INDETERMINATE
    assert initial.last_dispatch_timestamp is None
    assert initial.minimum_on_deadline is None
    assert initial.minimum_off_deadline is None

    enabled = dispatch(configured, HeatingAction.ENABLE_HEATING, state=initial)
    safety = configured.evaluate(
        desired_command=HeatingAction.DISABLE_HEATING,
        now=NOW + timedelta(minutes=1),
        current_state=enabled,
        safety_command=True,
    )
    disabled = configured.record_dispatched(
        safety,
        dispatched_at=NOW + timedelta(minutes=1),
        safety_command=True,
    )

    assert safety.state.phase is SourceControlPhase.HEATING_REQUESTED
    assert safety.state.detailed_phase is DetailedSourceControlPhase.SAFETY_OVERRIDE
    assert safety.active_lockout is ActiveLockoutType.MINIMUM_ON
    assert safety.lockout_deadline == NOW + timedelta(minutes=10)
    assert safety.state.active_lockout_type is None
    assert disabled.phase is SourceControlPhase.HEATING_NOT_REQUESTED
    assert disabled.detailed_phase is DetailedSourceControlPhase.SAFETY_OVERRIDE
    assert disabled.safety_bypassed_lockout is True
    assert disabled.last_dispatch_timestamp == NOW + timedelta(minutes=1)

    fatal = configured.fatal_state(disabled, now=NOW + timedelta(minutes=2))
    restarted = configured.initial_state(NOW + timedelta(minutes=3))

    assert fatal.phase is SourceControlPhase.FATAL_ERROR
    assert fatal.detailed_phase is DetailedSourceControlPhase.FATAL_ERROR
    assert fatal.minimum_on_deadline is None
    assert fatal.minimum_off_deadline is None
    assert fatal.deferred_command is None
    assert restarted.phase is SourceControlPhase.IDLE
    assert restarted.detailed_phase is DetailedSourceControlPhase.INDETERMINATE
    assert restarted.last_dispatched_command is None
    assert restarted.last_dispatch_timestamp is None
