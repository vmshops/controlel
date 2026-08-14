"""Tests for application-owned notification cursor and delivery processing."""

import asyncio
from datetime import UTC, datetime, timedelta

from controlel.application.services.notification_processor import NotificationProcessor
from controlel.application.services.operational_event_stream import OperationalEventStream
from controlel.domain.notifications import (
    NotificationDeliveryResult,
    NotificationDeliveryStatus,
    NotificationLevel,
    NotificationPolicy,
    NotificationRecipient,
)
from controlel.domain.operational_events import (
    OperationalEventCategory,
    OperationalEventCode,
    OperationalEventSeverity,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class Delivery:
    def __init__(self, *, raises: bool = False, failed: bool = False) -> None:
        self.raises = raises
        self.failed = failed
        self.source_event_ids: list[str] = []

    async def deliver(self, intent):
        self.source_event_ids.append(intent.source_event_id)
        if self.raises:
            raise RuntimeError("secret transport exception")
        status = NotificationDeliveryStatus.FAILED if self.failed else NotificationDeliveryStatus.DELIVERED
        return NotificationDeliveryResult(
            NOW,
            status,
            intent.source_event_id,
            intent.recipient_id,
            intent.notification_id,
            failure_code="stable_transport_failure" if self.failed else None,
        )


def _policy() -> NotificationPolicy:
    return NotificationPolicy(
        enabled=True,
        recipients=(
            NotificationRecipient(
                "phone",
                "test_transport",
                "endpoint:phone",
                minimum_level=NotificationLevel.DEBUG,
            ),
        ),
        maximum_per_window=100,
        critical_maximum_per_window=200,
    )


def _emit(stream: OperationalEventStream, count: int, *, timestamp: datetime = NOW) -> None:
    start = stream.snapshot().total_emitted
    categories = (OperationalEventCategory.RUNTIME, OperationalEventCategory.SOURCE_CONTROL)
    for offset in range(count):
        stream.emit(
            timestamp=timestamp,
            category=categories[(start + offset) % len(categories)],
            severity=OperationalEventSeverity.INFO,
            event_code=OperationalEventCode.RUNTIME_STARTED,
        )


def test_first_drain_after_retention_overflow_counts_exact_missed_gap() -> None:
    async def scenario():
        stream = OperationalEventStream(capacity=200)
        _emit(stream, 205, timestamp=NOW + timedelta(minutes=2))
        processor = NotificationProcessor(_policy(), stream.snapshot, Delivery())
        await processor.process_available()
        return processor.state()

    state = asyncio.run(scenario())
    assert state.source_total_observed == 205
    assert state.source_last_processed_sequence == 205
    assert state.source_events_missed == 5
    assert state.source_overflow_occurrences == 1


def test_multiple_overflows_are_counted_without_fabricating_lost_intents() -> None:
    async def scenario():
        stream = OperationalEventStream(capacity=200)
        _emit(stream, 205)
        processor = NotificationProcessor(_policy(), stream.snapshot, Delivery())
        await processor.process_available()
        first_intents = processor.state().total_intents_produced
        _emit(stream, 205, timestamp=NOW + timedelta(minutes=2))
        await processor.process_available()
        return first_intents, processor.state()

    first_intents, state = asyncio.run(scenario())
    assert first_intents == 200
    assert state.total_intents_produced == 400
    assert state.source_events_missed == 10
    assert state.source_overflow_occurrences == 2
    assert state.source_last_processed_sequence == 410


def test_unexpected_processing_failure_does_not_advance_beyond_failed_event() -> None:
    async def scenario():
        stream = OperationalEventStream()
        _emit(stream, 3)
        processor = NotificationProcessor(_policy(), stream.snapshot, Delivery())
        original_plan = processor.planner.plan

        def fail_second(event):
            if event.event_id == "event:00000002":
                raise RuntimeError("processor failure")
            return original_plan(event)

        processor.planner.plan = fail_second  # type: ignore[method-assign]
        caught_up = await processor.process_available()
        failed_state = processor.state()
        processor.planner.plan = original_plan  # type: ignore[method-assign]
        await processor.process_available()
        return caught_up, failed_state, processor.state()

    caught_up, failed_state, recovered_state = asyncio.run(scenario())
    assert caught_up is False
    assert failed_state.source_last_processed_sequence == 1
    assert recovered_state.source_last_processed_sequence == 3


def test_transport_failure_is_processed_once_and_advances_cursor_truthfully() -> None:
    async def scenario(raises: bool, failed: bool):
        stream = OperationalEventStream()
        _emit(stream, 2)
        processor = NotificationProcessor(_policy(), stream.snapshot, Delivery(raises=raises, failed=failed))
        await processor.process_available()
        await processor.process_available()
        return processor.state()

    for raises, failed in ((True, False), (False, True)):
        state = asyncio.run(scenario(raises, failed))
        assert state.source_last_processed_sequence == 2
        assert dict(state.counters)[NotificationDeliveryStatus.FAILED.value] == 2
        assert state.total_intents_produced == 2
        assert "secret transport exception" not in str(state)


def test_one_recipient_delivery_exception_does_not_prevent_another_recipient() -> None:
    class RecipientDelivery:
        async def deliver(self, intent):
            if intent.recipient_id == "phone":
                raise RuntimeError("private failure")
            return NotificationDeliveryResult(
                NOW,
                NotificationDeliveryStatus.DELIVERED,
                intent.source_event_id,
                intent.recipient_id,
                intent.notification_id,
            )

    async def scenario():
        stream = OperationalEventStream()
        _emit(stream, 1)
        policy = NotificationPolicy(
            enabled=True,
            recipients=(
                NotificationRecipient(
                    "phone",
                    "test_transport",
                    "endpoint:phone",
                    minimum_level=NotificationLevel.DEBUG,
                ),
                NotificationRecipient(
                    "tablet",
                    "test_transport",
                    "endpoint:tablet",
                    minimum_level=NotificationLevel.DEBUG,
                ),
            ),
        )
        processor = NotificationProcessor(policy, stream.snapshot, RecipientDelivery())
        await processor.process_available()
        return processor.state()

    state = asyncio.run(scenario())
    assert state.source_last_processed_sequence == 1
    assert dict(state.counters)[NotificationDeliveryStatus.FAILED.value] == 1
    assert dict(state.counters)[NotificationDeliveryStatus.DELIVERED.value] == 1
