"""Tests for deterministic bounded notification planning."""

from datetime import UTC, datetime, timedelta

from controlel.application.services.notification_planner import (
    ONCE_PER_CORRELATED_LIFECYCLE_CODES,
    PER_OCCURRENCE_CODES,
    NotificationPlanner,
)
from controlel.domain.notifications import (
    NotificationDeliveryStatus,
    NotificationLevel,
    NotificationPolicy,
    NotificationRecipient,
)
from controlel.domain.operational_events import (
    OperationalEvent,
    OperationalEventCategory,
    OperationalEventCode,
    OperationalEventDetail,
    OperationalEventSeverity,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _event(
    sequence: int,
    code: OperationalEventCode,
    *,
    category: OperationalEventCategory = OperationalEventCategory.RUNTIME,
    correlation_id: str | None = None,
    timestamp: datetime = NOW,
    details: tuple[OperationalEventDetail, ...] = (),
) -> OperationalEvent:
    return OperationalEvent(
        event_id=f"event:{sequence:08d}",
        timestamp=timestamp,
        category=category,
        severity=OperationalEventSeverity.INFO,
        event_code=code,
        reason_code=None,
        summary_code=code.value,
        correlation_id=correlation_id,
        details=details,
    )


def _recipient(
    recipient_id: str = "phone",
    *,
    minimum_level: NotificationLevel = NotificationLevel.DEBUG,
    categories: tuple[OperationalEventCategory, ...] = (),
) -> NotificationRecipient:
    return NotificationRecipient(
        recipient_id,
        "test_transport",
        f"endpoint:{recipient_id}",
        minimum_level=minimum_level,
        categories=categories,
    )


def test_disabled_and_no_recipient_policies_do_not_deliver() -> None:
    event = _event(1, OperationalEventCode.RUNTIME_FATAL)
    disabled = NotificationPlanner(NotificationPolicy(recipients=(_recipient(),))).plan(event)
    empty = NotificationPlanner(NotificationPolicy(enabled=True)).plan(event)

    assert not disabled.intents
    assert disabled.outcomes[0].status is NotificationDeliveryStatus.SUPPRESSED_POLICY
    assert not empty.intents
    assert empty.outcomes[0].status is NotificationDeliveryStatus.NO_RECIPIENT


def test_recipient_level_and_category_filters_are_independent() -> None:
    planner = NotificationPlanner(
        NotificationPolicy(
            enabled=True,
            recipients=(
                _recipient("critical", minimum_level=NotificationLevel.CRITICAL),
                _recipient("runtime", categories=(OperationalEventCategory.RUNTIME,)),
                _recipient("source", categories=(OperationalEventCategory.SOURCE_CONTROL,)),
            ),
        )
    )

    plan = planner.plan(_event(1, OperationalEventCode.RUNTIME_RECOVERED))

    assert [intent.recipient_id for intent in plan.intents] == ["runtime"]
    assert [outcome.recipient_id for outcome in plan.outcomes] == ["critical", "source"]


def test_semantic_lifecycle_is_deduplicated_but_unrelated_events_are_not() -> None:
    planner = NotificationPlanner(NotificationPolicy(enabled=True, recipients=(_recipient(),)))
    first = planner.plan(_event(1, OperationalEventCode.SOURCE_DRIFT_DETECTED, correlation_id="drift:1"))
    duplicate = planner.plan(_event(2, OperationalEventCode.SOURCE_DRIFT_DETECTED, correlation_id="drift:1"))
    unrelated = planner.plan(_event(3, OperationalEventCode.SOURCE_DRIFT_DETECTED, correlation_id="drift:2"))

    assert len(first.intents) == 1
    assert duplicate.outcomes[0].status is NotificationDeliveryStatus.SUPPRESSED_DUPLICATE
    assert len(unrelated.intents) == 1


def test_one_supervision_campaign_is_bounded_by_semantic_event_code() -> None:
    planner = NotificationPlanner(NotificationPolicy(enabled=True, recipients=(_recipient(),)))
    fatal = planner.plan(_event(1, OperationalEventCode.RUNTIME_FATAL, correlation_id="supervision:1"))
    repeated_fatal = planner.plan(_event(2, OperationalEventCode.RUNTIME_FATAL, correlation_id="supervision:1"))
    failsafe = planner.plan(_event(3, OperationalEventCode.FAILSAFE_ENTERED, correlation_id="supervision:1"))
    exhausted = planner.plan(_event(4, OperationalEventCode.RESTART_BUDGET_EXHAUSTED, correlation_id="supervision:1"))

    assert len(fatal.intents) == 1
    assert repeated_fatal.outcomes[0].status is NotificationDeliveryStatus.SUPPRESSED_DUPLICATE
    assert [plan.intents[0].level for plan in (failsafe, exhausted)] == [
        NotificationLevel.OPERATIONAL,
        NotificationLevel.CRITICAL,
    ]


def test_deduplication_families_exhaustively_partition_event_codes() -> None:
    assert ONCE_PER_CORRELATED_LIFECYCLE_CODES.isdisjoint(PER_OCCURRENCE_CODES)
    assert ONCE_PER_CORRELATED_LIFECYCLE_CODES | PER_OCCURRENCE_CODES == set(OperationalEventCode)


def test_restart_attempts_and_authority_transitions_remain_per_occurrence() -> None:
    planner = NotificationPlanner(NotificationPolicy(enabled=True, recipients=(_recipient(),)))
    campaign = "supervision:7"

    started = [
        planner.plan(_event(sequence, OperationalEventCode.RESTART_ATTEMPT_STARTED, correlation_id=campaign))
        for sequence in range(1, 4)
    ]
    failed = [
        planner.plan(_event(sequence, OperationalEventCode.RESTART_ATTEMPT_FAILED, correlation_id=campaign))
        for sequence in range(4, 7)
    ]
    authority = [
        planner.plan(_event(sequence, OperationalEventCode.COMMAND_AUTHORITY_CHANGED, correlation_id=campaign))
        for sequence in range(7, 9)
    ]

    assert all(len(plan.intents) == 1 for plan in (*started, *failed, *authority))


def test_repeated_source_commands_with_one_demand_correlation_remain_per_occurrence() -> None:
    planner = NotificationPlanner(NotificationPolicy(enabled=True, recipients=(_recipient(),)))
    plans = [
        planner.plan(_event(sequence, OperationalEventCode.SOURCE_ENABLE_REQUESTED, correlation_id="demand:1"))
        for sequence in range(1, 4)
    ]

    assert all(len(plan.intents) == 1 for plan in plans)


def test_safe_event_details_are_namespaced_and_preserved() -> None:
    planner = NotificationPlanner(NotificationPolicy(enabled=True, recipients=(_recipient(),)))
    event = _event(
        1,
        OperationalEventCode.RESTART_ATTEMPT_STARTED,
        details=(
            OperationalEventDetail("attempt", 2),
            OperationalEventDetail("budget", 3),
            OperationalEventDetail("deadline", "2026-01-01T00:05:00+00:00"),
        ),
    )

    intent = planner.plan(event).intents[0]

    assert {item.key: item.value for item in intent.parameters}.items() >= {
        "event_detail_attempt": 2,
        "event_detail_budget": 3,
        "event_detail_deadline": "2026-01-01T00:05:00+00:00",
    }.items()


def test_default_recipient_preference_suppresses_debug_refresh_evidence() -> None:
    recipient = NotificationRecipient("phone", "test_transport", "endpoint:phone")
    planner = NotificationPlanner(NotificationPolicy(enabled=True, recipients=(recipient,)))

    plan = planner.plan(_event(1, OperationalEventCode.MEASUREMENT_BECAME_VALID))

    assert not plan.intents
    assert plan.outcomes[0].status is NotificationDeliveryStatus.SUPPRESSED_POLICY


def test_rate_limit_is_per_recipient_and_category_and_critical_bypasses_it() -> None:
    planner = NotificationPlanner(
        NotificationPolicy(
            enabled=True, recipients=(_recipient(),), maximum_per_window=1, rate_window=timedelta(minutes=5)
        )
    )
    first = planner.plan(_event(1, OperationalEventCode.RUNTIME_RECOVERED))
    limited = planner.plan(_event(2, OperationalEventCode.RUNTIME_STOPPED))
    critical = planner.plan(_event(3, OperationalEventCode.RUNTIME_FATAL))

    assert len(first.intents) == 1
    assert limited.outcomes[0].status is NotificationDeliveryStatus.RATE_LIMITED
    assert len(critical.intents) == 1


def test_critical_emergency_budget_is_independent_and_bounded() -> None:
    planner = NotificationPlanner(
        NotificationPolicy(
            enabled=True,
            recipients=(_recipient(),),
            maximum_per_window=1,
            critical_maximum_per_window=2,
            rate_window=timedelta(minutes=5),
            critical_rate_window=timedelta(minutes=5),
        )
    )
    ordinary = planner.plan(_event(1, OperationalEventCode.RUNTIME_RECOVERED))
    ordinary_limited = planner.plan(_event(2, OperationalEventCode.RUNTIME_STOPPED))
    critical_one = planner.plan(_event(3, OperationalEventCode.RUNTIME_FATAL, correlation_id="fatal:1"))
    critical_two = planner.plan(_event(4, OperationalEventCode.RUNTIME_FATAL, correlation_id="fatal:2"))
    critical_limited = planner.plan(_event(5, OperationalEventCode.RUNTIME_FATAL, correlation_id="fatal:3"))

    assert len(ordinary.intents) == 1
    assert ordinary_limited.outcomes[0].status is NotificationDeliveryStatus.RATE_LIMITED
    assert len(critical_one.intents) == len(critical_two.intents) == 1
    assert critical_limited.outcomes[0].status is NotificationDeliveryStatus.RATE_LIMITED
    assert planner.diagnostics()["counters"]["rate_limited"] == 2


def test_ordinary_rate_limit_buckets_are_independent_by_recipient_and_category() -> None:
    planner = NotificationPlanner(
        NotificationPolicy(
            enabled=True,
            recipients=(
                _recipient(
                    "phone",
                    categories=(OperationalEventCategory.RUNTIME, OperationalEventCategory.SOURCE_CONTROL),
                ),
                _recipient("tablet", categories=(OperationalEventCategory.SOURCE_CONTROL,)),
            ),
            maximum_per_window=1,
            rate_window=timedelta(minutes=5),
        )
    )

    runtime = planner.plan(_event(1, OperationalEventCode.RUNTIME_RECOVERED))
    source = planner.plan(
        _event(
            2,
            OperationalEventCode.SOURCE_RECONCILIATION_STARTED,
            category=OperationalEventCategory.SOURCE_CONTROL,
        )
    )
    source_limited = planner.plan(
        _event(
            3,
            OperationalEventCode.CORRECTIVE_ACTION_HELD,
            category=OperationalEventCategory.SOURCE_CONTROL,
        )
    )

    assert [intent.recipient_id for intent in runtime.intents] == ["phone"]
    assert [intent.recipient_id for intent in source.intents] == ["phone", "tablet"]
    assert {outcome.recipient_id for outcome in source_limited.outcomes} == {"phone", "tablet"}


def test_history_is_bounded_and_delivery_failure_is_normalized() -> None:
    planner = NotificationPlanner(NotificationPolicy(enabled=True, recipients=(_recipient(),), history_capacity=2))
    intent = planner.plan(_event(1, OperationalEventCode.RUNTIME_RECOVERED)).intents[0]
    result = planner.record_delivery(intent, NotificationDeliveryStatus.FAILED, NOW, failure_code="service_call_failed")
    planner.plan(_event(2, OperationalEventCode.RUNTIME_STOPPED, timestamp=NOW + timedelta(seconds=1)))
    diagnostics = planner.diagnostics()

    assert result.status is NotificationDeliveryStatus.FAILED
    assert diagnostics["counters"]["failed"] == 1
    assert len(diagnostics["recent_history"]) == 2
    assert diagnostics["recipients"][0]["target_configured"] is True
    assert "endpoint:phone" not in str(diagnostics)
