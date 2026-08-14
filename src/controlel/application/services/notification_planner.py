"""Bounded activity-driven notification planning and rate control."""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any

from controlel.application.services.notification_policy import notification_rule_for_activity
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
from controlel.domain.user_activities import UserActivity

_RANK = {level: rank for rank, level in enumerate(reversed(tuple(NotificationLevel)))}


@dataclass(frozen=True, slots=True)
class NotificationPlan:
    """Intents ready for transport plus immediate policy outcomes."""

    intents: tuple[NotificationIntent, ...]
    outcomes: tuple[NotificationDeliveryResult, ...]


class NotificationPlanner:
    """Plan bounded notifications from human-meaningful activities only."""

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

    def plan(self, activity: UserActivity) -> NotificationPlan:
        """Evaluate one immutable activity revision."""

        with self._lock:
            return self._plan_locked(activity)

    def _plan_locked(self, activity: UserActivity) -> NotificationPlan:
        rule = notification_rule_for_activity(activity.activity_type)
        level = NotificationLevel(activity.level.value)
        if activity.status not in rule.notifiable_statuses:
            return NotificationPlan((), (self._outcome(activity, NotificationDeliveryStatus.SUPPRESSED_POLICY),))
        enabled = tuple(recipient for recipient in self.policy.recipients if recipient.enabled)
        if not self.policy.enabled or not enabled:
            status = (
                NotificationDeliveryStatus.SUPPRESSED_POLICY
                if not self.policy.enabled
                else NotificationDeliveryStatus.NO_RECIPIENT
            )
            return NotificationPlan((), (self._outcome(activity, status),))

        intents: list[NotificationIntent] = []
        outcomes: list[NotificationDeliveryResult] = []
        for recipient in enabled:
            if _RANK[level] < _RANK[recipient.minimum_level] or (
                recipient.categories and rule.category not in recipient.categories
            ):
                outcomes.append(
                    self._outcome(activity, NotificationDeliveryStatus.SUPPRESSED_POLICY, recipient.recipient_id)
                )
                continue
            semantic_key = _deduplication_key(recipient.recipient_id, activity)
            if semantic_key in self._seen_set:
                outcomes.append(
                    self._outcome(activity, NotificationDeliveryStatus.SUPPRESSED_DUPLICATE, recipient.recipient_id)
                )
                continue
            if self._rate_limited(recipient.recipient_id, rule.category.value, level, activity.updated_at):
                outcomes.append(
                    self._outcome(activity, NotificationDeliveryStatus.RATE_LIMITED, recipient.recipient_id)
                )
                continue
            self._remember(semantic_key)
            self._sequence += 1
            values = {
                "activity_type": activity.activity_type.value,
                "status": activity.status.value,
                "requested_action": activity.requested_action,
                "command_outcome": activity.command_outcome,
                "reported_state": activity.reported_state,
                "reason_code": activity.reason_code,
                "completion_outcome": activity.completion_outcome,
            }
            values.update({f"activity_parameter_{item.key}": item.value for item in activity.parameters})
            intent = NotificationIntent(
                notification_id=f"notification:{self._sequence:08d}",
                created_at=activity.updated_at,
                level=level,
                category=rule.category,
                title_code=f"notification_title_{activity.activity_type.value}",
                message_code=f"notification_message_{activity.activity_type.value}",
                source_activity_id=activity.activity_id,
                activity_type=activity.activity_type,
                recipient_id=recipient.recipient_id,
                correlation_id=activity.correlation_id,
                zone_ids=activity.zone_ids,
                source_ids=activity.source_ids,
                parameters=tuple(NotificationParameter(key, value) for key, value in sorted(values.items())),
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
            occurred_at, status, intent.source_activity_id, intent.recipient_id, intent.notification_id, failure_code
        )
        with self._lock:
            self._record(result)
            self._latest_delivery = result
        return result

    def state(self) -> NotificationState:
        """Return an immutable bounded read model."""

        with self._lock:
            return NotificationState(
                schema_version=2,
                enabled=self.policy.enabled,
                recipients=tuple(
                    NotificationRecipientSummary(
                        r.recipient_id,
                        r.transport,
                        bool(r.target),
                        r.enabled,
                        r.minimum_level,
                        tuple(c.value for c in r.categories),
                    )
                    for r in self.policy.recipients
                ),
                source_total_observed=0,
                source_last_processed_sequence=0,
                source_events_missed=0,
                source_overflow_occurrences=0,
                total_intents_produced=self._total_intents,
                counters=tuple(sorted(self._counters.items())),
                latest_intent_timestamp=self._latest_intent_at,
                latest_delivery_result=_history_record(self._latest_delivery) if self._latest_delivery else None,
                recent_history=tuple(_history_record(item) for item in self._history),
            )

    def diagnostics(self) -> dict[str, Any]:
        return notification_state_to_dict(self.state())

    def _outcome(
        self, activity: UserActivity, status: NotificationDeliveryStatus, recipient_id: str | None = None
    ) -> NotificationDeliveryResult:
        result = NotificationDeliveryResult(activity.updated_at, status, activity.activity_id, recipient_id)
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

    def _rate_limited(self, recipient_id: str, category: str, level: NotificationLevel, now: datetime) -> bool:
        if level is NotificationLevel.CRITICAL:
            bucket, window, maximum = (
                self._critical_rate[recipient_id],
                self.policy.critical_rate_window,
                self.policy.critical_maximum_per_window,
            )
        else:
            bucket, window, maximum = (
                self._rate[(recipient_id, category)],
                self.policy.rate_window,
                self.policy.maximum_per_window,
            )
        boundary = now - window
        while bucket and bucket[0] <= boundary:
            bucket.popleft()
        if len(bucket) >= maximum:
            return True
        bucket.append(now)
        return False


def _deduplication_key(recipient_id: str, activity: UserActivity) -> str:
    outcome = activity.completion_outcome or ""
    return f"{recipient_id}|{activity.activity_id}|{activity.activity_type.value}|{activity.status.value}|{outcome}"


def _history_record(item: NotificationIntent | NotificationDeliveryResult) -> NotificationHistoryRecord:
    if isinstance(item, NotificationIntent):
        return NotificationHistoryRecord(
            "intent",
            item.created_at,
            item.source_activity_id,
            item.activity_type.value,
            item.recipient_id,
            item.notification_id,
            item.level,
            item.category.value,
            item.title_code,
            item.message_code,
        )
    return NotificationHistoryRecord(
        "result",
        item.occurred_at,
        item.source_activity_id,
        None,
        item.recipient_id,
        item.notification_id,
        status=item.status,
        failure_code=item.failure_code,
    )
