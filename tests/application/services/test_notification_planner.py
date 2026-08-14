"""Tests for deterministic activity-driven notification planning."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from controlel.application.services.notification_planner import NotificationPlanner
from controlel.domain.notifications import (
    NotificationDeliveryStatus,
    NotificationLevel,
    NotificationPolicy,
    NotificationRecipient,
)
from controlel.domain.operational_events import OperationalEventCategory
from controlel.domain.user_activities import (
    UserActivity,
    UserActivityLevel,
    UserActivityParameter,
    UserActivityStatus,
    UserActivityType,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _activity(
    activity_id: str = "activity:1",
    *,
    activity_type: UserActivityType = UserActivityType.MEASUREMENT_DEGRADED,
    status: UserActivityStatus = UserActivityStatus.OPEN,
    level: UserActivityLevel = UserActivityLevel.OPERATIONAL,
    outcome: str | None = None,
) -> UserActivity:
    return UserActivity(
        activity_id,
        activity_type,
        status,
        level,
        NOW,
        NOW,
        None if status is UserActivityStatus.OPEN else NOW,
        ("event:1",),
        "lifecycle:1",
        zone_ids=("zone:1",),
        source_ids=("source:1",),
        requested_action="enable",
        command_outcome="dispatched",
        reported_state=None,
        reason_code="reason",
        completion_outcome=outcome,
        parameters=(UserActivityParameter("duration_seconds", 4),),
    )


def _planner(*, minimum: NotificationLevel = NotificationLevel.DEBUG, maximum: int = 10) -> NotificationPlanner:
    return NotificationPlanner(
        NotificationPolicy(
            enabled=True,
            recipients=(NotificationRecipient("phone", "test", "target", minimum_level=minimum),),
            maximum_per_window=maximum,
            rate_window=timedelta(minutes=5),
        )
    )


def test_intent_is_bound_to_activity_and_safe_truthful_evidence() -> None:
    intent = _planner().plan(_activity()).intents[0]
    assert intent.source_activity_id == "activity:1"
    assert intent.activity_type is UserActivityType.MEASUREMENT_DEGRADED
    assert intent.zone_ids == ("zone:1",)
    assert intent.source_ids == ("source:1",)
    assert intent.title_code == "notification_title_measurement_degraded"
    assert {item.key: item.value for item in intent.parameters}["reported_state"] is None
    assert {item.key: item.value for item in intent.parameters}["activity_parameter_duration_seconds"] == 4


def test_user_activity_level_is_primary_recipient_filter() -> None:
    plan = _planner(minimum=NotificationLevel.CRITICAL).plan(_activity(level=UserActivityLevel.OPERATIONAL))
    assert not plan.intents
    assert plan.outcomes[0].status is NotificationDeliveryStatus.SUPPRESSED_POLICY


def test_disabled_and_no_recipient_policies_remain_explicit() -> None:
    disabled = NotificationPlanner(NotificationPolicy(recipients=(_planner().policy.recipients))).plan(_activity())
    empty = NotificationPlanner(NotificationPolicy(enabled=True)).plan(_activity())

    assert disabled.outcomes[0].status is NotificationDeliveryStatus.SUPPRESSED_POLICY
    assert empty.outcomes[0].status is NotificationDeliveryStatus.NO_RECIPIENT


def test_non_notifiable_revision_and_technical_noise_do_not_produce_intents() -> None:
    recovered_revision = replace(_activity(), status=UserActivityStatus.RECOVERED, completed_at=NOW)
    plan = _planner().plan(recovered_revision)
    assert not plan.intents
    assert plan.outcomes[0].status is NotificationDeliveryStatus.SUPPRESSED_POLICY


def test_dedupe_is_per_recipient_activity_and_material_stage() -> None:
    planner = _planner()
    first = planner.plan(_activity())
    duplicate = planner.plan(replace(_activity(), updated_at=NOW + timedelta(seconds=1)))
    unrelated = planner.plan(_activity("activity:2"))
    assert len(first.intents) == len(unrelated.intents) == 1
    assert duplicate.outcomes[0].status is NotificationDeliveryStatus.SUPPRESSED_DUPLICATE


def test_rate_limit_and_critical_emergency_ceiling_remain_independent() -> None:
    planner = _planner(maximum=1)
    first = planner.plan(_activity("activity:1"))
    limited = planner.plan(_activity("activity:2"))
    critical = planner.plan(
        _activity(
            "activity:3",
            activity_type=UserActivityType.RUNTIME_RESTART_EXHAUSTED,
            status=UserActivityStatus.FAILED,
            level=UserActivityLevel.CRITICAL,
        )
    )
    assert len(first.intents) == 1
    assert limited.outcomes[0].status is NotificationDeliveryStatus.RATE_LIMITED
    assert len(critical.intents) == 1


def test_critical_emergency_ceiling_is_bounded() -> None:
    planner = NotificationPlanner(
        NotificationPolicy(
            enabled=True,
            recipients=(_planner().policy.recipients),
            critical_maximum_per_window=1,
            critical_rate_window=timedelta(minutes=5),
        )
    )
    first = planner.plan(
        _activity(
            "fatal:1",
            activity_type=UserActivityType.RUNTIME_RESTART_EXHAUSTED,
            status=UserActivityStatus.FAILED,
            level=UserActivityLevel.CRITICAL,
        )
    )
    limited = planner.plan(
        _activity(
            "fatal:2",
            activity_type=UserActivityType.RUNTIME_RESTART_EXHAUSTED,
            status=UserActivityStatus.FAILED,
            level=UserActivityLevel.CRITICAL,
        )
    )
    assert len(first.intents) == 1
    assert limited.outcomes[0].status is NotificationDeliveryStatus.RATE_LIMITED


def test_category_filter_uses_activity_policy_category() -> None:
    recipient = NotificationRecipient(
        "phone", "test", "target", minimum_level=NotificationLevel.DEBUG, categories=(OperationalEventCategory.RUNTIME,)
    )
    plan = NotificationPlanner(NotificationPolicy(enabled=True, recipients=(recipient,))).plan(_activity())
    assert not plan.intents


def test_history_remains_bounded_and_redacts_transport_targets() -> None:
    recipient = NotificationRecipient("phone", "test", "private-endpoint", minimum_level=NotificationLevel.DEBUG)
    planner = NotificationPlanner(NotificationPolicy(enabled=True, recipients=(recipient,), history_capacity=2))
    intent = planner.plan(_activity("one")).intents[0]
    planner.record_delivery(intent, NotificationDeliveryStatus.DELIVERED, NOW)
    planner.plan(_activity("two"))
    diagnostics = planner.diagnostics()

    assert len(diagnostics["recent_history"]) == 2
    assert diagnostics["recipients"][0]["target_configured"] is True
    assert "private-endpoint" not in str(diagnostics)
