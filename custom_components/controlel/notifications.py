"""Event-driven Home Assistant transport for semantic notification intents."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from controlel.application.services.notification_processor import NotificationProcessor
from controlel.application.services.operational_event_stream import OperationalEventStreamSnapshot
from controlel.domain.notifications import (
    NotificationDeliveryResult,
    NotificationDeliveryStatus,
    NotificationIntent,
    NotificationPolicy,
)

from .const import NOTIFICATION_TRANSPORT_HOME_ASSISTANT


class HomeAssistantNotificationTransport:
    """Resolve configured logical recipients into HA notify service calls."""

    def __init__(self, hass: object, policy: NotificationPolicy) -> None:
        self._hass = hass
        self._recipients = {recipient.recipient_id: recipient for recipient in policy.recipients}

    async def deliver(self, intent: NotificationIntent) -> NotificationDeliveryResult:
        """Deliver one intent and normalize all transport failures."""

        recipient = self._recipients.get(intent.recipient_id)
        if recipient is None or recipient.transport != NOTIFICATION_TRANSPORT_HOME_ASSISTANT:
            return _result(intent, NotificationDeliveryStatus.NO_RECIPIENT)
        _, service = recipient.target.split(".", 1)
        try:
            await self._hass.services.async_call(
                "notify",
                service,
                {
                    "title": intent.title_code,
                    "message": intent.message_code,
                    "data": {
                        "notification_id": intent.notification_id,
                        "level": intent.level.value,
                        "category": intent.category.value,
                        "source_event_id": intent.source_event_id,
                        "correlation_id": intent.correlation_id,
                        "zone_id": intent.zone_id,
                        "source_id": intent.source_id,
                        "parameters": {parameter.key: parameter.value for parameter in intent.parameters},
                    },
                },
                blocking=True,
            )
        except Exception:
            return _result(
                intent,
                NotificationDeliveryStatus.FAILED,
                failure_code="home_assistant_notify_service_failed",
            )
        return _result(intent, NotificationDeliveryStatus.DELIVERED)


class HomeAssistantNotificationCoordinator:
    """Thin HA lifecycle boundary over the application notification processor."""

    def __init__(
        self,
        policy: NotificationPolicy,
        snapshot_provider: Callable[[], OperationalEventStreamSnapshot],
        transport: HomeAssistantNotificationTransport,
        logger: logging.Logger,
    ) -> None:
        self.processor = NotificationProcessor(policy, snapshot_provider, transport, logger)

    async def async_process_new_events(self) -> None:
        """Plan and deliver each new retained event once, outside control execution."""

        await self.processor.process_available()

    def close(self) -> None:
        """Invalidate queued event delivery during unload."""

        self.processor.close()

    def diagnostics(self) -> dict[str, object]:
        """Return bounded target-redacted notification state."""

        return self.processor.diagnostics()


def _result(
    intent: NotificationIntent,
    status: NotificationDeliveryStatus,
    *,
    failure_code: str | None = None,
) -> NotificationDeliveryResult:
    return NotificationDeliveryResult(
        occurred_at=datetime.now(UTC),
        status=status,
        source_event_id=intent.source_event_id,
        recipient_id=intent.recipient_id,
        notification_id=intent.notification_id,
        failure_code=failure_code,
    )
