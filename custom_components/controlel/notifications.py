"""Event-driven Home Assistant transport for semantic notification intents."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from controlel.application.services.notification_processor import NotificationProcessor
from controlel.application.services.operational_event_stream import OperationalEventStreamSnapshot
from controlel.application.services.user_activity_composer import UserActivityComposer
from controlel.application.services.user_activity_stream import user_activity_snapshot_to_dict
from controlel.domain.notifications import (
    NotificationDeliveryResult,
    NotificationDeliveryStatus,
    NotificationIntent,
    NotificationPolicy,
)

from .const import NOTIFICATION_TRANSPORT_HOME_ASSISTANT
from .notification_renderer import HomeAssistantNotificationRenderer, safe_notification_parameters


class HomeAssistantNotificationTransport:
    """Resolve configured logical recipients into HA notify service calls."""

    def __init__(
        self,
        hass: object,
        policy: NotificationPolicy,
        *,
        renderer: HomeAssistantNotificationRenderer | None = None,
    ) -> None:
        self._hass = hass
        self._recipients = {recipient.recipient_id: recipient for recipient in policy.recipients}
        self._renderer = renderer or HomeAssistantNotificationRenderer(hass)

    async def deliver(self, intent: NotificationIntent) -> NotificationDeliveryResult:
        """Deliver one intent and normalize all transport failures."""

        recipient = self._recipients.get(intent.recipient_id)
        if recipient is None or recipient.transport != NOTIFICATION_TRANSPORT_HOME_ASSISTANT:
            return _result(intent, NotificationDeliveryStatus.NO_RECIPIENT)
        _, service = recipient.target.split(".", 1)
        rendered = await self._renderer.async_render(intent)
        try:
            await self._hass.services.async_call(
                "notify",
                service,
                {
                    "title": rendered.title,
                    "message": rendered.message,
                    "data": {
                        "notification_id": intent.notification_id,
                        "level": intent.level.value,
                        "category": intent.category.value,
                        "source_activity_id": intent.source_activity_id,
                        "activity_type": intent.activity_type.value,
                        "correlation_id": intent.correlation_id,
                        "zone_ids": list(intent.zone_ids),
                        "source_ids": list(intent.source_ids),
                        "parameters": safe_notification_parameters(intent),
                        "renderer_fallback_code": rendered.fallback_code,
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
        self.composer = UserActivityComposer(snapshot_provider, logger=logger)
        self.processor = NotificationProcessor(policy, self.composer.snapshot, transport, logger)
        self._closed = False

    async def async_process_new_events(self) -> None:
        """Compose events before planning each retained activity revision."""

        if self._closed or not self.composer.process_available():
            return
        await self.processor.process_available()

    def close(self) -> None:
        """Invalidate queued event delivery during unload."""

        self._closed = True
        self.processor.close()

    def diagnostics(self) -> dict[str, object]:
        """Return bounded target-redacted notification state."""

        return self.processor.diagnostics()

    def activity_diagnostics(self) -> dict[str, object]:
        """Return bounded JSON-safe activities with allowlisted scalar parameters."""

        payload = user_activity_snapshot_to_dict(self.composer.snapshot())
        activities = payload["activities"]
        if isinstance(activities, list):
            for activity in activities:
                if not isinstance(activity, dict):
                    continue
                parameters = activity.get("parameters")
                if isinstance(parameters, dict):
                    activity["parameters"] = {
                        key: value for key, value in parameters.items() if key in _SAFE_ACTIVITY_PARAMETER_NAMES
                    }
        return payload


def _result(
    intent: NotificationIntent,
    status: NotificationDeliveryStatus,
    *,
    failure_code: str | None = None,
) -> NotificationDeliveryResult:
    return NotificationDeliveryResult(
        occurred_at=datetime.now(UTC),
        status=status,
        source_activity_id=intent.source_activity_id,
        recipient_id=intent.recipient_id,
        notification_id=intent.notification_id,
        failure_code=failure_code,
    )


_SAFE_ACTIVITY_PARAMETER_NAMES = frozenset(
    {
        "attempt",
        "budget",
        "deadline",
        "desired_state",
        "duration_seconds",
        "protection_reason",
        "reported_state",
        "source_events_truncated",
        "transition_history",
    }
)
