"""Immutable bounded notification read boundary for diagnostics and future UI."""

from dataclasses import dataclass
from datetime import datetime

from controlel.domain.notifications import NotificationDeliveryStatus, NotificationLevel


@dataclass(frozen=True, slots=True)
class NotificationRecipientSummary:
    """Redacted effective recipient configuration."""

    recipient_id: str
    transport: str
    target_configured: bool
    enabled: bool
    minimum_level: NotificationLevel
    categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NotificationHistoryRecord:
    """Bounded semantic intent or normalized result projection."""

    kind: str
    timestamp: datetime
    source_activity_id: str
    activity_type: str | None
    recipient_id: str | None
    notification_id: str | None
    level: NotificationLevel | None = None
    category: str | None = None
    title_code: str | None = None
    message_code: str | None = None
    status: NotificationDeliveryStatus | None = None
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class NotificationState:
    """Immutable bounded state independent from operational-event retention."""

    schema_version: int
    enabled: bool
    recipients: tuple[NotificationRecipientSummary, ...]
    source_total_observed: int
    source_last_processed_sequence: int
    source_events_missed: int
    source_overflow_occurrences: int
    total_intents_produced: int
    counters: tuple[tuple[str, int], ...]
    latest_intent_timestamp: datetime | None
    latest_delivery_result: NotificationHistoryRecord | None
    recent_history: tuple[NotificationHistoryRecord, ...]


def notification_state_to_dict(state: NotificationState) -> dict[str, object]:
    """Project notification state into deterministic JSON-safe primitives."""

    def history(item: NotificationHistoryRecord) -> dict[str, object]:
        return {
            "kind": item.kind,
            "timestamp": item.timestamp.isoformat(),
            "source_activity_id": item.source_activity_id,
            "activity_type": item.activity_type,
            "recipient_id": item.recipient_id,
            "notification_id": item.notification_id,
            "level": item.level.value if item.level is not None else None,
            "category": item.category,
            "title_code": item.title_code,
            "message_code": item.message_code,
            "status": item.status.value if item.status is not None else None,
            "failure_code": item.failure_code,
        }

    return {
        "schema_version": state.schema_version,
        "enabled": state.enabled,
        "configured_recipient_count": len(state.recipients),
        "source_total_observed": state.source_total_observed,
        "source_last_processed_sequence": state.source_last_processed_sequence,
        "source_events_missed": state.source_events_missed,
        "source_overflow_occurrences": state.source_overflow_occurrences,
        "recipients": [
            {
                "recipient_id": recipient.recipient_id,
                "transport": recipient.transport,
                "target_configured": recipient.target_configured,
                "enabled": recipient.enabled,
                "minimum_level": recipient.minimum_level.value,
                "categories": list(recipient.categories),
            }
            for recipient in state.recipients
        ],
        "total_intents_produced": state.total_intents_produced,
        "counters": dict(state.counters),
        "latest_intent_timestamp": (
            state.latest_intent_timestamp.isoformat() if state.latest_intent_timestamp is not None else None
        ),
        "latest_delivery_result": history(state.latest_delivery_result) if state.latest_delivery_result else None,
        "recent_history": [history(item) for item in state.recent_history],
    }
