"""Bounded operational-event stream tests."""

import json
from datetime import UTC, datetime, timedelta

from controlel.application.services.operational_event_stream import (
    OperationalEventStream,
    operational_event_stream_to_dict,
)
from controlel.domain.operational_events import (
    OperationalEventCategory,
    OperationalEventCode,
    OperationalEventSeverity,
)

NOW = datetime(2026, 8, 13, tzinfo=UTC)


def test_stream_order_retention_drop_metadata_and_json_projection_are_deterministic() -> None:
    stream = OperationalEventStream(capacity=2)
    for offset, code in enumerate(
        (
            OperationalEventCode.RUNTIME_STARTED,
            OperationalEventCode.SAFETY_GRACE_STARTED,
            OperationalEventCode.RUNTIME_STOPPED,
        )
    ):
        stream.emit(
            timestamp=NOW + timedelta(seconds=offset),
            category=OperationalEventCategory.RUNTIME,
            severity=OperationalEventSeverity.INFO,
            event_code=code,
            details=(("offset", offset),),
        )

    snapshot = stream.snapshot()
    assert [event.event_id for event in snapshot.events] == ["event:00000002", "event:00000003"]
    assert [event.event_code for event in snapshot.events] == [
        OperationalEventCode.SAFETY_GRACE_STARTED,
        OperationalEventCode.RUNTIME_STOPPED,
    ]
    assert snapshot.total_emitted == 3
    assert snapshot.dropped_count == 1
    assert snapshot.latest_event_timestamp == NOW + timedelta(seconds=2)
    payload = operational_event_stream_to_dict(snapshot)
    assert json.loads(json.dumps(payload)) == payload
    assert payload["events"][0]["details"] == {"offset": 1}


def test_snapshot_is_an_immutable_copy_not_a_mutable_stream_view() -> None:
    stream = OperationalEventStream(capacity=2)
    before = stream.snapshot()
    stream.emit(
        timestamp=NOW,
        category=OperationalEventCategory.RUNTIME,
        severity=OperationalEventSeverity.INFO,
        event_code=OperationalEventCode.RUNTIME_STARTED,
    )

    assert before.events == ()
    assert len(stream.snapshot().events) == 1
