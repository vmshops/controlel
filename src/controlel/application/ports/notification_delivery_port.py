"""Application port for isolated notification transports."""

from typing import Protocol

from controlel.domain.notifications import NotificationDeliveryResult, NotificationIntent


class NotificationDeliveryPort(Protocol):
    """Deliver one semantic intent without participating in control decisions."""

    async def deliver(self, intent: NotificationIntent) -> NotificationDeliveryResult:
        """Attempt transport and return one normalized result without raising."""
