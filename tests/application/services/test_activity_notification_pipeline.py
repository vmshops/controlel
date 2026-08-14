"""End-to-end tests for the canonical M31B.2 in-memory pipeline."""

import asyncio
from datetime import UTC, datetime

from controlel.application.services.notification_processor import NotificationProcessor
from controlel.application.services.operational_event_stream import OperationalEventStream
from controlel.application.services.user_activity_composer import UserActivityComposer
from controlel.domain.notifications import (
    NotificationDeliveryResult,
    NotificationDeliveryStatus,
    NotificationLevel,
    NotificationPolicy,
    NotificationRecipient,
)
from controlel.domain.operational_events import OperationalEventCategory, OperationalEventCode, OperationalEventSeverity
from controlel.domain.user_activities import UserActivityType

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class Delivery:
    def __init__(self) -> None:
        self.activity_types: list[UserActivityType] = []

    async def deliver(self, intent):
        self.activity_types.append(intent.activity_type)
        return NotificationDeliveryResult(
            NOW,
            NotificationDeliveryStatus.DELIVERED,
            intent.source_activity_id,
            intent.recipient_id,
            intent.notification_id,
        )


def test_measurement_incident_and_recovery_flow_only_through_user_activities() -> None:
    async def scenario() -> tuple[list[UserActivityType], int]:
        events = OperationalEventStream()
        composer = UserActivityComposer(events.snapshot)
        delivery = Delivery()
        processor = NotificationProcessor(
            NotificationPolicy(
                enabled=True,
                recipients=(NotificationRecipient("phone", "test", "target", minimum_level=NotificationLevel.DEBUG),),
            ),
            composer.snapshot,
            delivery,
        )
        events.emit(
            timestamp=NOW,
            category=OperationalEventCategory.MEASUREMENT,
            severity=OperationalEventSeverity.WARNING,
            event_code=OperationalEventCode.MEASUREMENT_BECAME_STALE,
            activity_id="measurement:1",
        )
        assert composer.process_available() is True
        assert await processor.process_available() is True
        events.emit(
            timestamp=NOW,
            category=OperationalEventCategory.MEASUREMENT,
            severity=OperationalEventSeverity.INFO,
            event_code=OperationalEventCode.MEASUREMENT_RECOVERED,
            activity_id="measurement:1",
        )
        assert composer.process_available() is True
        assert await processor.process_available() is True
        return delivery.activity_types, processor.state().source_last_processed_sequence

    activity_types, cursor = asyncio.run(scenario())
    assert activity_types == [UserActivityType.MEASUREMENT_DEGRADED, UserActivityType.MEASUREMENT_RECOVERED]
    assert cursor == 3


def test_technical_runtime_event_without_activity_produces_no_notification() -> None:
    async def scenario() -> tuple[list[UserActivityType], int]:
        events = OperationalEventStream()
        composer = UserActivityComposer(events.snapshot)
        delivery = Delivery()
        processor = NotificationProcessor(
            NotificationPolicy(
                enabled=True,
                recipients=(NotificationRecipient("phone", "test", "target", minimum_level=NotificationLevel.DEBUG),),
            ),
            composer.snapshot,
            delivery,
        )
        events.emit(
            timestamp=NOW,
            category=OperationalEventCategory.RUNTIME,
            severity=OperationalEventSeverity.INFO,
            event_code=OperationalEventCode.RUNTIME_STARTED,
        )
        composer.process_available()
        await processor.process_available()
        return delivery.activity_types, processor.state().source_total_observed

    activity_types, observed = asyncio.run(scenario())
    assert activity_types == []
    assert observed == 0
