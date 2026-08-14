"""Thread-safe bounded retention and JSON projection for user activities."""

from dataclasses import replace
from threading import Lock
from typing import Any

from controlel.domain.user_activities import UserActivity, UserActivitySnapshot

DEFAULT_USER_ACTIVITY_CAPACITY = 200


class UserActivityStream:
    """Retain the latest immutable revision of each bounded activity."""

    def __init__(self, capacity: int = DEFAULT_USER_ACTIVITY_CAPACITY) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self._capacity = capacity
        self._activities: list[UserActivity] = []
        self._total_emitted = 0
        self._lock = Lock()

    def publish(self, activity: UserActivity) -> None:
        """Append a new activity or replace its retained immutable revision."""

        with self._lock:
            for index, retained in enumerate(self._activities):
                if retained.activity_id == activity.activity_id:
                    self._activities[index] = activity
                    return
            self._total_emitted += 1
            if len(self._activities) == self._capacity:
                self._activities.pop(0)
            self._activities.append(activity)

    def discard(self, activity_ids: set[str]) -> None:
        """Discard incomplete retained revisions when source evidence was lost."""

        with self._lock:
            self._activities = [item for item in self._activities if item.activity_id not in activity_ids]

    def discard_correlations(self, correlation_ids: set[str]) -> None:
        """Discard retained revisions belonging to incomplete lost lifecycles."""

        with self._lock:
            self._activities = [item for item in self._activities if item.correlation_id not in correlation_ids]

    def snapshot(self, *, open_activity_count: int = 0) -> UserActivitySnapshot:
        """Return an immutable copy with source progress initially unset."""

        with self._lock:
            activities = tuple(self._activities)
            return UserActivitySnapshot(
                schema_version=1,
                capacity=self._capacity,
                activities=activities,
                total_activities_emitted=self._total_emitted,
                dropped_count=max(0, self._total_emitted - len(activities)),
                source_total_observed=0,
                source_last_processed_sequence=0,
                source_events_missed=0,
                source_overflow_occurrences=0,
                open_activity_count=open_activity_count,
                latest_activity_timestamp=max((item.updated_at for item in activities), default=None),
            )


def user_activity_snapshot_with_source(
    snapshot: UserActivitySnapshot,
    *,
    source_total_observed: int,
    source_last_processed_sequence: int,
    source_events_missed: int,
    source_overflow_occurrences: int,
) -> UserActivitySnapshot:
    """Bind application-owned source progress to a stream snapshot."""

    return replace(
        snapshot,
        source_total_observed=source_total_observed,
        source_last_processed_sequence=source_last_processed_sequence,
        source_events_missed=source_events_missed,
        source_overflow_occurrences=source_overflow_occurrences,
    )


def user_activity_snapshot_to_dict(snapshot: UserActivitySnapshot) -> dict[str, Any]:
    """Project bounded activity state into localization-neutral JSON primitives."""

    return {
        "schema_version": snapshot.schema_version,
        "capacity": snapshot.capacity,
        "total_activities_emitted": snapshot.total_activities_emitted,
        "retained_count": len(snapshot.activities),
        "dropped_count": snapshot.dropped_count,
        "source_total_observed": snapshot.source_total_observed,
        "source_last_processed_sequence": snapshot.source_last_processed_sequence,
        "source_events_missed": snapshot.source_events_missed,
        "source_overflow_occurrences": snapshot.source_overflow_occurrences,
        "open_activity_count": snapshot.open_activity_count,
        "latest_activity_timestamp": (
            snapshot.latest_activity_timestamp.isoformat() if snapshot.latest_activity_timestamp is not None else None
        ),
        "activities": [user_activity_to_dict(activity) for activity in snapshot.activities],
    }


def user_activity_to_dict(activity: UserActivity) -> dict[str, Any]:
    """Project one activity without prose or inferred physical state."""

    return {
        "activity_id": activity.activity_id,
        "activity_type": activity.activity_type.value,
        "status": activity.status.value,
        "level": activity.level.value,
        "started_at": activity.started_at.isoformat(),
        "updated_at": activity.updated_at.isoformat(),
        "completed_at": activity.completed_at.isoformat() if activity.completed_at is not None else None,
        "source_event_ids": list(activity.source_event_ids),
        "correlation_id": activity.correlation_id,
        "parent_activity_id": activity.parent_activity_id,
        "zone_ids": list(activity.zone_ids),
        "source_ids": list(activity.source_ids),
        "requested_action": activity.requested_action,
        "command_outcome": activity.command_outcome,
        "reported_state": activity.reported_state,
        "reason_code": activity.reason_code,
        "completion_outcome": activity.completion_outcome,
        "parameters": {parameter.key: parameter.value for parameter in activity.parameters},
    }
