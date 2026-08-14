"""Tests for immutable, presentation-neutral user activity contracts."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from controlel.domain.user_activities import (
    UserActivity,
    UserActivityLevel,
    UserActivityParameter,
    UserActivityStatus,
    UserActivityType,
    user_activity_id,
)

NOW = datetime(2026, 8, 14, tzinfo=UTC)


def test_user_activity_is_immutable_truthful_and_deterministically_identified() -> None:
    activity = UserActivity(
        activity_id=user_activity_id(UserActivityType.HEATING_STARTED, "heating-episode:00000001"),
        activity_type=UserActivityType.HEATING_STARTED,
        status=UserActivityStatus.COMPLETED,
        level=UserActivityLevel.DETAILED,
        started_at=NOW,
        updated_at=NOW,
        completed_at=NOW,
        source_event_ids=("event:00000001",),
        correlation_id="heating-episode:00000001",
        zone_ids=("living_room",),
        requested_action="enable_heating",
        command_outcome="dispatched",
        reported_state=None,
        parameters=(UserActivityParameter("duration_seconds", None),),
    )

    assert activity.activity_id == "heating-episode:00000001/heating_started"
    assert activity.reported_state is None
    assert activity.parameters[0].value is None
    with pytest.raises(FrozenInstanceError):
        activity.status = UserActivityStatus.OPEN  # type: ignore[misc]


def test_parameters_reject_nested_or_non_finite_values() -> None:
    with pytest.raises(TypeError, match="JSON-safe scalar"):
        UserActivityParameter("nested", {"secret": "value"})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        UserActivityParameter("temperature", float("nan"))


def test_activity_requires_sorted_bounded_identity_and_completed_timestamps() -> None:
    with pytest.raises(ValueError, match="sorted"):
        UserActivity(
            "activity:1",
            UserActivityType.MEASUREMENT_DEGRADED,
            UserActivityStatus.OPEN,
            UserActivityLevel.OPERATIONAL,
            NOW,
            NOW,
            None,
            ("event:2", "event:1"),
            "measurement-incident:1",
        )
    with pytest.raises(ValueError, match="completed_at"):
        UserActivity(
            "activity:1",
            UserActivityType.MEASUREMENT_RECOVERED,
            UserActivityStatus.RECOVERED,
            UserActivityLevel.OPERATIONAL,
            NOW,
            NOW,
            None,
            ("event:1",),
            "measurement-incident:1",
        )
