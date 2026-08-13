"""Thread-safe bounded retention and JSON projection for operational events."""

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any

from controlel.domain.operational_events import (
    OperationalEvent,
    OperationalEventCategory,
    OperationalEventCode,
    OperationalEventDetail,
    OperationalEventSeverity,
)
from controlel.domain.operational_events.model import OperationalEventScalar

DEFAULT_OPERATIONAL_EVENT_CAPACITY = 200


@dataclass(frozen=True, slots=True)
class OperationalEventStreamSnapshot:
    """Immutable read boundary for one bounded runtime event stream."""

    schema_version: int
    capacity: int
    events: tuple[OperationalEvent, ...]
    total_emitted: int
    dropped_count: int
    latest_event_timestamp: datetime | None


class OperationalEventStream:
    """Retain semantic events in deterministic emission order."""

    def __init__(self, capacity: int = DEFAULT_OPERATIONAL_EVENT_CAPACITY) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self._capacity = capacity
        self._events: deque[OperationalEvent] = deque(maxlen=capacity)
        self._total_emitted = 0
        self._correlation_sequence = 0
        self._lock = Lock()

    def next_correlation_id(self, scope: str) -> str:
        """Return a deterministic stream-local correlation identifier."""

        with self._lock:
            self._correlation_sequence += 1
            sequence = self._correlation_sequence
        return f"{scope}:{sequence:08d}"

    def emit(
        self,
        *,
        timestamp: datetime,
        category: OperationalEventCategory,
        severity: OperationalEventSeverity,
        event_code: OperationalEventCode,
        reason_code: str | None = None,
        summary_code: str | None = None,
        zone_id: str | None = None,
        source_id: str | None = None,
        correlation_id: str | None = None,
        previous_state: str | None = None,
        new_state: str | None = None,
        requested_command: str | None = None,
        command_outcome: str | None = None,
        details: Iterable[tuple[str, OperationalEventScalar]] = (),
    ) -> OperationalEvent:
        """Append one event and return the exact immutable retained value."""

        normalized_details = tuple(
            OperationalEventDetail(key, value) for key, value in sorted(details, key=lambda item: item[0])
        )
        with self._lock:
            sequence = self._total_emitted + 1
            event = OperationalEvent(
                event_id=f"event:{sequence:08d}",
                timestamp=timestamp,
                category=category,
                severity=severity,
                event_code=event_code,
                reason_code=reason_code,
                summary_code=summary_code or event_code.value,
                zone_id=zone_id,
                source_id=source_id,
                correlation_id=correlation_id,
                previous_state=previous_state,
                new_state=new_state,
                requested_command=requested_command,
                command_outcome=command_outcome,
                details=normalized_details,
            )
            self._events.append(event)
            self._total_emitted = sequence
            return event

    def snapshot(self) -> OperationalEventStreamSnapshot:
        """Return an immutable copy which cannot mutate retained state."""

        with self._lock:
            events = tuple(self._events)
            return OperationalEventStreamSnapshot(
                schema_version=1,
                capacity=self._capacity,
                events=events,
                total_emitted=self._total_emitted,
                dropped_count=self._total_emitted - len(events),
                latest_event_timestamp=events[-1].timestamp if events else None,
            )


def operational_event_stream_to_dict(snapshot: OperationalEventStreamSnapshot) -> dict[str, Any]:
    """Project one stream snapshot into bounded JSON-safe primitives."""

    return {
        "schema_version": snapshot.schema_version,
        "capacity": snapshot.capacity,
        "total_emitted": snapshot.total_emitted,
        "dropped_count": snapshot.dropped_count,
        "retained_count": len(snapshot.events),
        "latest_event_timestamp": (
            snapshot.latest_event_timestamp.isoformat() if snapshot.latest_event_timestamp is not None else None
        ),
        "events": [operational_event_to_dict(event) for event in snapshot.events],
    }


def operational_event_to_dict(event: OperationalEvent) -> dict[str, Any]:
    """Project one immutable event without localization or exception text."""

    return {
        "event_id": event.event_id,
        "timestamp": event.timestamp.isoformat(),
        "category": event.category.value,
        "severity": event.severity.value,
        "event_code": event.event_code.value,
        "reason_code": event.reason_code,
        "summary_code": event.summary_code,
        "zone_id": event.zone_id,
        "source_id": event.source_id,
        "correlation_id": event.correlation_id,
        "previous_state": event.previous_state,
        "new_state": event.new_state,
        "requested_command": event.requested_command,
        "command_outcome": event.command_outcome,
        "details": {detail.key: detail.value for detail in event.details},
    }
