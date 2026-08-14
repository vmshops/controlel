"""Tests for exact activity-revision notification processing."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from controlel.application.services.notification_processor import NotificationProcessor
from controlel.application.services.user_activity_stream import UserActivityStream
from controlel.domain.notifications import (
    NotificationDeliveryResult,
    NotificationDeliveryStatus,
    NotificationLevel,
    NotificationPolicy,
    NotificationRecipient,
)
from controlel.domain.user_activities import UserActivity, UserActivityLevel, UserActivityStatus, UserActivityType

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _activity(activity_id: str, status: UserActivityStatus = UserActivityStatus.OPEN) -> UserActivity:
    return UserActivity(
        activity_id,
        UserActivityType.MEASUREMENT_DEGRADED,
        status,
        UserActivityLevel.OPERATIONAL,
        NOW,
        NOW,
        None if status is UserActivityStatus.OPEN else NOW,
        (f"event:{activity_id}",),
        activity_id,
    )


class Delivery:
    def __init__(self, raises: bool = False) -> None:
        self.raises = raises
        self.activity_ids: list[str] = []

    async def deliver(self, intent):
        self.activity_ids.append(intent.source_activity_id)
        if self.raises:
            raise RuntimeError("private transport error")
        return NotificationDeliveryResult(
            NOW,
            NotificationDeliveryStatus.DELIVERED,
            intent.source_activity_id,
            intent.recipient_id,
            intent.notification_id,
        )


def _processor(stream: UserActivityStream, delivery: Delivery | None = None) -> NotificationProcessor:
    policy = NotificationPolicy(
        enabled=True,
        recipients=(NotificationRecipient("phone", "test", "target", minimum_level=NotificationLevel.DEBUG),),
        maximum_per_window=100,
    )
    return NotificationProcessor(policy, stream.snapshot, delivery or Delivery())


def test_repeated_unchanged_snapshot_is_not_reprocessed() -> None:
    async def scenario():
        stream, delivery = UserActivityStream(), Delivery()
        stream.publish(_activity("one"))
        processor = _processor(stream, delivery)
        await processor.process_available()
        await processor.process_available()
        return delivery.activity_ids, processor.state()

    delivered, state = asyncio.run(scenario())
    assert delivered == ["one"]
    assert state.source_last_processed_sequence == 1


def test_activity_revision_is_observed_and_suppression_advances_cursor() -> None:
    async def scenario():
        stream = UserActivityStream()
        stream.publish(_activity("one"))
        processor = _processor(stream)
        await processor.process_available()
        stream.publish(replace(_activity("one"), status=UserActivityStatus.RECOVERED, completed_at=NOW))
        await processor.process_available()
        return processor.state()

    state = asyncio.run(scenario())
    assert state.source_last_processed_sequence == 2
    assert dict(state.counters)[NotificationDeliveryStatus.SUPPRESSED_POLICY.value] == 1


def test_processing_failure_does_not_advance_failed_revision() -> None:
    async def scenario():
        stream = UserActivityStream()
        stream.publish(_activity("one"))
        processor = _processor(stream)
        original = processor.planner.plan
        processor.planner.plan = lambda activity: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]
        caught_up = await processor.process_available()
        failed = processor.state()
        processor.planner.plan = original  # type: ignore[method-assign]
        await processor.process_available()
        return caught_up, failed, processor.state()

    caught_up, failed, recovered = asyncio.run(scenario())
    assert caught_up is False
    assert failed.source_last_processed_sequence == 0
    assert recovered.source_last_processed_sequence == 1


def test_delivery_failure_advances_once_without_leaking_exception() -> None:
    async def scenario():
        stream = UserActivityStream()
        stream.publish(_activity("one"))
        processor = _processor(stream, Delivery(raises=True))
        await processor.process_available()
        await processor.process_available()
        return processor.state()

    state = asyncio.run(scenario())
    assert state.source_last_processed_sequence == 1
    assert dict(state.counters)[NotificationDeliveryStatus.FAILED.value] == 1
    assert "private transport error" not in str(state)


def test_one_recipient_failure_does_not_block_another_recipient() -> None:
    class RecipientDelivery(Delivery):
        async def deliver(self, intent):
            if intent.recipient_id == "phone":
                raise RuntimeError("private failure")
            return NotificationDeliveryResult(
                NOW,
                NotificationDeliveryStatus.DELIVERED,
                intent.source_activity_id,
                intent.recipient_id,
                intent.notification_id,
            )

    async def scenario():
        stream = UserActivityStream()
        stream.publish(_activity("one"))
        policy = NotificationPolicy(
            enabled=True,
            recipients=(
                NotificationRecipient("phone", "test", "phone-target", minimum_level=NotificationLevel.DEBUG),
                NotificationRecipient("tablet", "test", "tablet-target", minimum_level=NotificationLevel.DEBUG),
            ),
        )
        processor = NotificationProcessor(policy, stream.snapshot, RecipientDelivery())
        await processor.process_available()
        return processor.state()

    state = asyncio.run(scenario())
    assert dict(state.counters)[NotificationDeliveryStatus.FAILED.value] == 1
    assert dict(state.counters)[NotificationDeliveryStatus.DELIVERED.value] == 1
    assert state.source_last_processed_sequence == 1


def test_retention_gap_is_counted_exactly() -> None:
    async def scenario():
        stream = UserActivityStream(capacity=2)
        for value in ("one", "two", "three"):
            stream.publish(_activity(value))
        processor = _processor(stream)
        await processor.process_available()
        return processor.state()

    state = asyncio.run(scenario())
    assert state.source_events_missed == 1
    assert state.source_overflow_occurrences == 1
    assert state.source_last_processed_sequence == 3
