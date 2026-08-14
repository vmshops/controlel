"""Tests for bounded immutable user-activity retention."""

from datetime import UTC, datetime, timedelta

from controlel.application.services.user_activity_stream import (
    UserActivityStream,
    user_activity_snapshot_to_dict,
)
from controlel.domain.user_activities import (
    UserActivity,
    UserActivityLevel,
    UserActivityStatus,
    UserActivityType,
)

NOW = datetime(2026, 8, 14, tzinfo=UTC)


def _activity(
    sequence: int,
    *,
    status: UserActivityStatus = UserActivityStatus.COMPLETED,
    correlation_id: str | None = None,
) -> UserActivity:
    timestamp = NOW + timedelta(seconds=sequence)
    return UserActivity(
        f"activity:{sequence}",
        UserActivityType.HEATING_STARTED,
        status,
        UserActivityLevel.DETAILED,
        timestamp,
        timestamp,
        None if status is UserActivityStatus.OPEN else timestamp,
        (f"event:{sequence:08d}",),
        correlation_id or f"heating-episode:{sequence}",
    )


def test_stream_is_bounded_and_updates_one_activity_without_duplicate_history() -> None:
    stream = UserActivityStream(capacity=2)
    stream.publish(_activity(1, status=UserActivityStatus.OPEN))
    stream.publish(_activity(1))
    stream.publish(_activity(2))
    stream.publish(_activity(3))

    snapshot = stream.snapshot(open_activity_count=0)
    payload = user_activity_snapshot_to_dict(snapshot)

    assert [activity.activity_id for activity in snapshot.activities] == ["activity:2", "activity:3"]
    assert snapshot.total_activities_emitted == 3
    assert snapshot.dropped_count == 1
    assert payload["retained_count"] == 2
    assert payload["activities"][0]["reported_state"] is None


def test_stream_discards_all_revisions_for_lost_lifecycle() -> None:
    stream = UserActivityStream()
    stream.publish(_activity(1, correlation_id="incident"))
    stream.publish(_activity(2, correlation_id="incident"))
    stream.publish(_activity(3, correlation_id="other"))

    stream.discard_correlations({"incident"})

    assert [activity.correlation_id for activity in stream.snapshot().activities] == ["other"]
