"""Bounded notification intent planning, de-duplication, and rate control."""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any

from controlel.application.services.notification_policy import notification_level_for_event
from controlel.application.state.notification_state import (
    NotificationHistoryRecord,
    NotificationRecipientSummary,
    NotificationState,
    notification_state_to_dict,
)
from controlel.domain.notifications import (
    NotificationDeliveryResult,
    NotificationDeliveryStatus,
    NotificationIntent,
    NotificationLevel,
    NotificationParameter,
    NotificationPolicy,
)
from controlel.domain.operational_events import OperationalEvent, OperationalEventCode

_RANK = {level: rank for rank, level in enumerate(reversed(tuple(NotificationLevel)))}

ONCE_PER_CORRELATED_LIFECYCLE_CODES = frozenset(
    {
        OperationalEventCode.RUNTIME_FATAL,
        OperationalEventCode.RUNTIME_RECOVERED,
        OperationalEventCode.HEAT_DEMAND_STARTED,
        OperationalEventCode.HEAT_DEMAND_CONFIRMED,
        OperationalEventCode.HEAT_DEMAND_CANCELLED,
        OperationalEventCode.HEAT_DEMAND_SATISFIED,
        OperationalEventCode.SAFETY_GRACE_STARTED,
        OperationalEventCode.SAFETY_GRACE_EXPIRED,
        OperationalEventCode.SOURCE_DRIFT_DETECTED,
        OperationalEventCode.SOURCE_RECONCILIATION_COMPLETED,
        OperationalEventCode.FAILSAFE_ENTERED,
        OperationalEventCode.FAILSAFE_EXITED,
        OperationalEventCode.RESTART_BUDGET_EXHAUSTED,
    }
)
PER_OCCURRENCE_CODES = frozenset(
    {
        OperationalEventCode.RUNTIME_STARTED,
        OperationalEventCode.RUNTIME_STOPPED,
        OperationalEventCode.MEASUREMENT_BECAME_VALID,
        OperationalEventCode.MEASUREMENT_BECAME_STALE,
        OperationalEventCode.MEASUREMENT_BECAME_UNAVAILABLE,
        OperationalEventCode.MEASUREMENT_RECOVERED,
        OperationalEventCode.SAFETY_DISABLE_REQUESTED,
        OperationalEventCode.EMERGENCY_DISABLE_REQUESTED,
        OperationalEventCode.SOURCE_ENABLE_REQUESTED,
        OperationalEventCode.SOURCE_DISABLE_REQUESTED,
        OperationalEventCode.SOURCE_COMMAND_DISPATCHED,
        OperationalEventCode.SOURCE_COMMAND_FAILED,
        OperationalEventCode.SOURCE_COMMAND_DEFERRED_MINIMUM_ON,
        OperationalEventCode.SOURCE_COMMAND_DEFERRED_MINIMUM_OFF,
        OperationalEventCode.REPORTED_SOURCE_STATE_CHANGED,
        OperationalEventCode.SOURCE_RECONCILIATION_STARTED,
        OperationalEventCode.CORRECTIVE_ACTION_HELD,
        OperationalEventCode.CORRECTIVE_ACTION_DISPATCHED,
        OperationalEventCode.RESTART_ATTEMPT_STARTED,
        OperationalEventCode.RESTART_ATTEMPT_FAILED,
        OperationalEventCode.COMMAND_AUTHORITY_CHANGED,
    }
)

if (
    ONCE_PER_CORRELATED_LIFECYCLE_CODES & PER_OCCURRENCE_CODES
    or ONCE_PER_CORRELATED_LIFECYCLE_CODES | PER_OCCURRENCE_CODES != set(OperationalEventCode)
):
    raise RuntimeError("every OperationalEventCode must have an explicit notification deduplication family")


@dataclass(frozen=True, slots=True)
class NotificationPlan:
    """Intents ready for transport plus immediate policy outcomes."""

    intents: tuple[NotificationIntent, ...]
    outcomes: tuple[NotificationDeliveryResult, ...]


class NotificationPlanner:
    """Plan bounded notifications without participating in control execution."""

    def __init__(self, policy: NotificationPolicy) -> None:
        self.policy = policy
        self._sequence = 0
        self._seen: deque[str] = deque(maxlen=policy.history_capacity * 4)
        self._seen_set: set[str] = set()
        self._rate: dict[tuple[str, str], deque[datetime]] = defaultdict(deque)
        self._critical_rate: dict[str, deque[datetime]] = defaultdict(deque)
        self._history: deque[NotificationIntent | NotificationDeliveryResult] = deque(maxlen=policy.history_capacity)
        self._counters = {status.value: 0 for status in NotificationDeliveryStatus}
        self._total_intents = 0
        self._latest_intent_at: datetime | None = None
        self._latest_delivery: NotificationDeliveryResult | None = None
        self._lock = Lock()

    def plan(self, event: OperationalEvent) -> NotificationPlan:
        """Evaluate one immutable event and return transport-neutral work."""

        with self._lock:
            return self._plan_locked(event)

    def _plan_locked(self, event: OperationalEvent) -> NotificationPlan:
        level = notification_level_for_event(event.event_code)
        enabled = tuple(recipient for recipient in self.policy.recipients if recipient.enabled)
        if not self.policy.enabled or not enabled:
            status = (
                NotificationDeliveryStatus.SUPPRESSED_POLICY
                if not self.policy.enabled
                else NotificationDeliveryStatus.NO_RECIPIENT
            )
            return NotificationPlan((), (self._outcome(event, status),))

        intents: list[NotificationIntent] = []
        outcomes: list[NotificationDeliveryResult] = []
        for recipient in enabled:
            if _RANK[level] < _RANK[recipient.minimum_level] or (
                recipient.categories and event.category not in recipient.categories
            ):
                outcomes.append(
                    self._outcome(event, NotificationDeliveryStatus.SUPPRESSED_POLICY, recipient.recipient_id)
                )
                continue
            semantic_key = _deduplication_key(recipient.recipient_id, event)
            if semantic_key in self._seen_set:
                outcomes.append(
                    self._outcome(event, NotificationDeliveryStatus.SUPPRESSED_DUPLICATE, recipient.recipient_id)
                )
                continue
            if self._rate_limited(recipient.recipient_id, event, level, event.timestamp):
                outcomes.append(self._outcome(event, NotificationDeliveryStatus.RATE_LIMITED, recipient.recipient_id))
                continue
            self._remember(semantic_key)
            self._sequence += 1
            parameter_values = {
                "event_code": event.event_code.value,
                "reason_code": event.reason_code,
                "previous_state": event.previous_state,
                "new_state": event.new_state,
                "requested_command": event.requested_command,
                "command_outcome": event.command_outcome,
            }
            parameter_values.update({f"event_detail_{detail.key}": detail.value for detail in event.details})
            parameters = tuple(NotificationParameter(key, value) for key, value in sorted(parameter_values.items()))
            intent = NotificationIntent(
                notification_id=f"notification:{self._sequence:08d}",
                created_at=event.timestamp,
                level=level,
                category=event.category,
                title_code=f"notification_title_{event.event_code.value}",
                message_code=f"notification_message_{event.event_code.value}",
                source_event_id=event.event_id,
                recipient_id=recipient.recipient_id,
                correlation_id=event.correlation_id,
                zone_id=event.zone_id,
                source_id=event.source_id,
                parameters=parameters,
            )
            intents.append(intent)
            self._history.append(intent)
            self._total_intents += 1
            self._latest_intent_at = intent.created_at
        return NotificationPlan(tuple(intents), tuple(outcomes))

    def record_delivery(
        self,
        intent: NotificationIntent,
        status: NotificationDeliveryStatus,
        occurred_at: datetime,
        *,
        failure_code: str | None = None,
    ) -> NotificationDeliveryResult:
        """Record a normalized adapter outcome without raising into control."""

        result = NotificationDeliveryResult(
            occurred_at=occurred_at,
            status=status,
            source_event_id=intent.source_event_id,
            recipient_id=intent.recipient_id,
            notification_id=intent.notification_id,
            failure_code=failure_code,
        )
        with self._lock:
            self._record(result)
            self._latest_delivery = result
        return result

    def state(self) -> NotificationState:
        """Return an immutable bounded read model for UI and diagnostics."""

        with self._lock:
            history = tuple(_history_record(item) for item in self._history)
            return NotificationState(
                schema_version=1,
                enabled=self.policy.enabled,
                recipients=tuple(
                    NotificationRecipientSummary(
                        recipient.recipient_id,
                        recipient.transport,
                        bool(recipient.target),
                        recipient.enabled,
                        recipient.minimum_level,
                        tuple(category.value for category in recipient.categories),
                    )
                    for recipient in self.policy.recipients
                ),
                source_total_observed=0,
                source_last_processed_sequence=0,
                source_events_missed=0,
                source_overflow_occurrences=0,
                total_intents_produced=self._total_intents,
                counters=tuple(sorted(self._counters.items())),
                latest_intent_timestamp=self._latest_intent_at,
                latest_delivery_result=(
                    _history_record(self._latest_delivery) if self._latest_delivery is not None else None
                ),
                recent_history=history,
            )

    def diagnostics(self) -> dict[str, Any]:
        """Return bounded JSON-safe state with transport targets redacted."""

        return notification_state_to_dict(self.state())

    def _outcome(
        self,
        event: OperationalEvent,
        status: NotificationDeliveryStatus,
        recipient_id: str | None = None,
    ) -> NotificationDeliveryResult:
        result = NotificationDeliveryResult(event.timestamp, status, event.event_id, recipient_id)
        self._record(result)
        return result

    def _record(self, result: NotificationDeliveryResult) -> None:
        self._counters[result.status.value] += 1
        self._history.append(result)

    def _remember(self, key: str) -> None:
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(key)
        self._seen_set.add(key)

    def _rate_limited(
        self,
        recipient_id: str,
        event: OperationalEvent,
        level: NotificationLevel,
        now: datetime,
    ) -> bool:
        if level is NotificationLevel.CRITICAL:
            bucket = self._critical_rate[recipient_id]
            window = self.policy.critical_rate_window
            maximum = self.policy.critical_maximum_per_window
        else:
            bucket = self._rate[(recipient_id, event.category.value)]
            window = self.policy.rate_window
            maximum = self.policy.maximum_per_window
        boundary = now - window
        while bucket and bucket[0] <= boundary:
            bucket.popleft()
        if len(bucket) >= maximum:
            return True
        bucket.append(now)
        return False


def _deduplication_key(recipient_id: str, event: OperationalEvent) -> str:
    if event.event_code in ONCE_PER_CORRELATED_LIFECYCLE_CODES and event.correlation_id is not None:
        identity = event.correlation_id
    else:
        identity = event.event_id
    return f"{recipient_id}|{event.event_code.value}|{identity}"


def _history_record(item: NotificationIntent | NotificationDeliveryResult) -> NotificationHistoryRecord:
    if isinstance(item, NotificationIntent):
        return NotificationHistoryRecord(
            kind="intent",
            timestamp=item.created_at,
            source_event_id=item.source_event_id,
            recipient_id=item.recipient_id,
            notification_id=item.notification_id,
            level=item.level,
            category=item.category.value,
            title_code=item.title_code,
            message_code=item.message_code,
        )
    return NotificationHistoryRecord(
        kind="result",
        timestamp=item.occurred_at,
        source_event_id=item.source_event_id,
        recipient_id=item.recipient_id,
        notification_id=item.notification_id,
        status=item.status,
        failure_code=item.failure_code,
    )
