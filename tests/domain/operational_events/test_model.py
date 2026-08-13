"""Immutable operational-event contract tests."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from controlel.domain.operational_events import (
    OperationalEvent,
    OperationalEventCategory,
    OperationalEventCode,
    OperationalEventDetail,
    OperationalEventSeverity,
)

NOW = datetime(2026, 8, 13, tzinfo=UTC)


def test_operational_event_is_immutable_and_uses_stable_enum_values() -> None:
    event = OperationalEvent(
        event_id="event:00000001",
        timestamp=NOW,
        category=OperationalEventCategory.SOURCE_CONTROL,
        severity=OperationalEventSeverity.NOTICE,
        event_code=OperationalEventCode.SOURCE_COMMAND_DISPATCHED,
        reason_code="normal_demand",
        summary_code="source_command_dispatched",
        requested_command="enable_heating",
        command_outcome="dispatched",
        details=(OperationalEventDetail("physical_state", None),),
    )

    assert event.category.value == "source_control"
    assert event.severity.value == "notice"
    assert event.event_code.value == "source_command_dispatched"
    assert event.details[0].value is None
    with pytest.raises(FrozenInstanceError):
        event.event_id = "changed"


def test_event_rejects_naive_time_and_non_json_detail() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        OperationalEvent(
            "event:00000001",
            datetime(2026, 8, 13),
            OperationalEventCategory.RUNTIME,
            OperationalEventSeverity.INFO,
            OperationalEventCode.RUNTIME_STARTED,
            None,
            "runtime_started",
        )
    with pytest.raises(TypeError, match="JSON-safe scalar"):
        OperationalEventDetail("unsafe", object())
