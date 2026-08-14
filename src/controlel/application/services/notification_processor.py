"""Application-owned processing of retained operational events into notifications."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from controlel.application.ports.notification_delivery_port import NotificationDeliveryPort
from controlel.application.services.notification_planner import NotificationPlanner
from controlel.application.services.operational_event_stream import OperationalEventStreamSnapshot
from controlel.application.state.notification_state import (
    NotificationState,
    notification_state_to_dict,
)
from controlel.domain.notifications import (
    NotificationDeliveryStatus,
    NotificationPolicy,
)


class NotificationProcessor:
    """Own the truthful source cursor and best-effort notification pipeline."""

    def __init__(
        self,
        policy: NotificationPolicy,
        snapshot_provider: Callable[[], OperationalEventStreamSnapshot],
        delivery: NotificationDeliveryPort,
        logger: logging.Logger | None = None,
    ) -> None:
        self.planner = NotificationPlanner(policy)
        self._snapshot_provider = snapshot_provider
        self._delivery = delivery
        self._logger = logger or logging.getLogger(__name__)
        self._source_total_observed = 0
        self._source_last_processed_sequence = 0
        self._source_events_missed = 0
        self._source_overflow_occurrences = 0
        self._closed = False
        self._lock = asyncio.Lock()

    async def process_available(self) -> bool:
        """Process one retained snapshot and report whether that snapshot was consumed."""

        async with self._lock:
            if self._closed:
                return True
            snapshot = self._snapshot_provider()
            self._source_total_observed = max(self._source_total_observed, snapshot.total_emitted)
            first_retained_sequence = snapshot.total_emitted - len(snapshot.events) + 1
            next_sequence = self._source_last_processed_sequence + 1
            if snapshot.events and next_sequence < first_retained_sequence:
                self._source_events_missed += first_retained_sequence - next_sequence
                self._source_overflow_occurrences += 1
                self._source_last_processed_sequence = first_retained_sequence - 1

            for offset, event in enumerate(snapshot.events):
                sequence = first_retained_sequence + offset
                if sequence <= self._source_last_processed_sequence:
                    continue
                if self._closed:
                    return True
                try:
                    plan = self.planner.plan(event)
                    for intent in plan.intents:
                        if self._closed:
                            return True
                        try:
                            result = await self._delivery.deliver(intent)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            result = self.planner.record_delivery(
                                intent,
                                NotificationDeliveryStatus.FAILED,
                                datetime.now(UTC),
                                failure_code="notification_delivery_port_failed",
                            )
                        else:
                            self.planner.record_delivery(
                                intent,
                                result.status,
                                result.occurred_at,
                                failure_code=result.failure_code,
                            )
                    self._source_last_processed_sequence = sequence
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._logger.exception(
                        "Controlel notification processing failed at source sequence %s",
                        sequence,
                    )
                    return False
            return self._source_last_processed_sequence >= snapshot.total_emitted

    def close(self) -> None:
        """Prevent future planning and delivery; accepted transport calls cannot be revoked."""

        self._closed = True

    def state(self) -> NotificationState:
        """Return immutable notification state with truthful source progress."""

        return replace(
            self.planner.state(),
            source_total_observed=self._source_total_observed,
            source_last_processed_sequence=self._source_last_processed_sequence,
            source_events_missed=self._source_events_missed,
            source_overflow_occurrences=self._source_overflow_occurrences,
        )

    def diagnostics(self) -> dict[str, object]:
        """Return bounded JSON-safe state with transport targets redacted."""

        return notification_state_to_dict(self.state())
