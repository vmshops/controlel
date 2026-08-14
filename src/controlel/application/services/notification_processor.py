"""Application-owned processing of retained user activities into notifications."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from controlel.application.ports.notification_delivery_port import NotificationDeliveryPort
from controlel.application.services.notification_planner import NotificationPlanner
from controlel.application.state.notification_state import NotificationState, notification_state_to_dict
from controlel.domain.notifications import NotificationDeliveryStatus, NotificationPolicy
from controlel.domain.user_activities import UserActivitySnapshot


class NotificationProcessor:
    """Own the truthful activity-revision cursor and best-effort pipeline."""

    def __init__(
        self,
        policy: NotificationPolicy,
        snapshot_provider: Callable[[], UserActivitySnapshot],
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
        """Process retained activity revisions in their exact publication order."""

        async with self._lock:
            if self._closed:
                return True
            snapshot = self._snapshot_provider()
            total = snapshot.total_activity_revisions_emitted
            self._source_total_observed = max(self._source_total_observed, total)
            revisions = sorted(zip(snapshot.activity_sequences, snapshot.activities, strict=True))
            gap_seen = False
            for sequence, activity in revisions:
                if sequence <= self._source_last_processed_sequence:
                    continue
                expected = self._source_last_processed_sequence + 1
                if sequence > expected:
                    self._source_events_missed += sequence - expected
                    gap_seen = True
                    self._source_last_processed_sequence = sequence - 1
                if self._closed:
                    return True
                try:
                    plan = self.planner.plan(activity)
                    for intent in plan.intents:
                        if self._closed:
                            return True
                        try:
                            result = await self._delivery.deliver(intent)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            self.planner.record_delivery(
                                intent,
                                NotificationDeliveryStatus.FAILED,
                                datetime.now(UTC),
                                failure_code="notification_delivery_port_failed",
                            )
                        else:
                            self.planner.record_delivery(
                                intent, result.status, result.occurred_at, failure_code=result.failure_code
                            )
                    self._source_last_processed_sequence = sequence
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._logger.exception("Controlel notification processing failed at activity revision %s", sequence)
                    if gap_seen:
                        self._source_overflow_occurrences += 1
                    return False
            if self._source_last_processed_sequence < total:
                self._source_events_missed += total - self._source_last_processed_sequence
                self._source_last_processed_sequence = total
                gap_seen = True
            if gap_seen:
                self._source_overflow_occurrences += 1
            return self._source_last_processed_sequence >= total

    def close(self) -> None:
        self._closed = True

    def state(self) -> NotificationState:
        return replace(
            self.planner.state(),
            source_total_observed=self._source_total_observed,
            source_last_processed_sequence=self._source_last_processed_sequence,
            source_events_missed=self._source_events_missed,
            source_overflow_occurrences=self._source_overflow_occurrences,
        )

    def diagnostics(self) -> dict[str, object]:
        return notification_state_to_dict(self.state())
