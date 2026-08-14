"""Deterministic composition tests for M31B.1 user activities."""

from datetime import UTC, datetime, timedelta

from controlel.application.services.operational_event_stream import OperationalEventStream
from controlel.application.services.user_activity_composer import UserActivityComposer
from controlel.domain.operational_events import (
    OperationalEventCategory as Category,
)
from controlel.domain.operational_events import (
    OperationalEventCode as Code,
)
from controlel.domain.operational_events import (
    OperationalEventSeverity as Severity,
)
from controlel.domain.user_activities import UserActivityStatus, UserActivityType

NOW = datetime(2026, 8, 14, tzinfo=UTC)


def _emit(
    stream: OperationalEventStream,
    code: Code,
    sequence: int,
    *,
    activity_id: str | None,
    category: Category = Category.SOURCE_RESILIENCE,
    zone_id: str | None = None,
    requested_command: str | None = None,
    command_outcome: str | None = None,
    previous_state: str | None = None,
    new_state: str | None = None,
    reason_code: str | None = None,
    details=(),
) -> None:
    stream.emit(
        timestamp=NOW + timedelta(seconds=sequence),
        category=category,
        severity=Severity.NOTICE,
        event_code=code,
        activity_id=activity_id,
        zone_id=zone_id,
        requested_command=requested_command,
        command_outcome=command_outcome,
        previous_state=previous_state,
        new_state=new_state,
        reason_code=reason_code,
        details=details,
    )


def test_reconciliation_completes_only_after_reported_agreement() -> None:
    stream = OperationalEventStream()
    lifecycle = "source-reconciliation:00000001"
    _emit(
        stream,
        Code.SOURCE_DRIFT_DETECTED,
        0,
        activity_id=lifecycle,
        details=(("desired_state", "disable_heating"), ("reported_state", "enabled")),
    )
    _emit(
        stream,
        Code.SOURCE_COMMAND_DEFERRED_MINIMUM_ON,
        1,
        activity_id=lifecycle,
        category=Category.SOURCE_CONTROL,
        requested_command="disable_heating",
        command_outcome="deferred",
        reason_code="minimum_on_time_active",
        details=(("deadline", (NOW + timedelta(minutes=5)).isoformat()),),
    )
    _emit(
        stream,
        Code.SOURCE_COMMAND_DISPATCHED,
        2,
        activity_id=lifecycle,
        category=Category.SOURCE_CONTROL,
        requested_command="disable_heating",
        command_outcome="dispatched",
    )
    composer = UserActivityComposer(stream.snapshot)
    assert composer.process_available() is True
    assert composer.snapshot().activities == ()
    assert composer.snapshot().open_activity_count == 1

    _emit(
        stream,
        Code.REPORTED_SOURCE_STATE_CHANGED,
        3,
        activity_id=lifecycle,
        previous_state="enabled",
        new_state="disabled",
    )
    _emit(
        stream,
        Code.SOURCE_RECONCILIATION_COMPLETED,
        4,
        activity_id=lifecycle,
        details=(("completion_outcome", "reported_agreement"),),
    )
    assert composer.process_available() is True

    (activity,) = composer.snapshot().activities
    assert activity.activity_type is UserActivityType.SOURCE_STATE_CORRECTED
    assert activity.status is UserActivityStatus.COMPLETED
    assert activity.requested_action == "disable_heating"
    assert activity.command_outcome == "dispatched"
    assert activity.reported_state == "disabled"
    assert dict((item.key, item.value) for item in activity.parameters)["protection_reason"] == (
        "minimum_on_time_active"
    )
    assert composer.snapshot().open_activity_count == 0


def test_failed_and_unrelated_reconciliation_campaigns_remain_separate() -> None:
    stream = OperationalEventStream()
    for sequence, lifecycle in enumerate(("source-reconciliation:1", "source-reconciliation:2")):
        _emit(stream, Code.SOURCE_DRIFT_DETECTED, sequence, activity_id=lifecycle)
    _emit(
        stream,
        Code.SOURCE_COMMAND_FAILED,
        2,
        activity_id="source-reconciliation:1",
        category=Category.SOURCE_CONTROL,
        requested_command="disable_heating",
        command_outcome="failed",
        reason_code="service_call_failed",
    )
    composer = UserActivityComposer(stream.snapshot)
    composer.process_available()

    snapshot = composer.snapshot()
    assert snapshot.activities[0].activity_type is UserActivityType.SOURCE_CORRECTION_FAILED
    assert snapshot.activities[0].correlation_id == "source-reconciliation:1"
    assert snapshot.open_activity_count == 1


def test_measurement_grace_recovery_and_safety_fallback_are_truthful() -> None:
    stream = OperationalEventStream()
    incident = "measurement-incident:1"
    _emit(
        stream,
        Code.MEASUREMENT_BECAME_UNAVAILABLE,
        0,
        activity_id=incident,
        category=Category.MEASUREMENT,
        zone_id="living_room",
        new_state="unavailable",
    )
    _emit(stream, Code.SAFETY_GRACE_STARTED, 1, activity_id=incident, category=Category.SAFETY)
    _emit(
        stream,
        Code.SAFETY_DISABLE_REQUESTED,
        2,
        activity_id=incident,
        category=Category.SAFETY,
        requested_command="disable_heating",
        command_outcome="requested",
    )
    _emit(
        stream,
        Code.MEASUREMENT_RECOVERED,
        3,
        activity_id=incident,
        category=Category.MEASUREMENT,
        zone_id="living_room",
        new_state="valid",
    )
    composer = UserActivityComposer(stream.snapshot)
    composer.process_available()

    assert [activity.activity_type for activity in composer.snapshot().activities] == [
        UserActivityType.MEASUREMENT_DEGRADED,
        UserActivityType.SAFETY_FALLBACK_APPLIED,
        UserActivityType.MEASUREMENT_RECOVERED,
    ]
    assert composer.snapshot().activities[1].command_outcome == "requested"
    assert composer.snapshot().open_activity_count == 0


def test_safety_grace_alone_does_not_create_activity() -> None:
    stream = OperationalEventStream()
    _emit(stream, Code.SAFETY_GRACE_STARTED, 0, activity_id=None, category=Category.SAFETY)
    composer = UserActivityComposer(stream.snapshot)
    composer.process_available()
    assert composer.snapshot().activities == ()


def test_heating_start_stop_multiple_zones_and_known_duration() -> None:
    stream = OperationalEventStream()
    episode = "heating-episode:1"
    for sequence, zone_id in enumerate(("bedroom", "living_room")):
        _emit(
            stream,
            Code.HEAT_DEMAND_CONFIRMED,
            sequence,
            activity_id=episode,
            category=Category.DEMAND,
            zone_id=zone_id,
            reason_code="heat_required_by_multiple_zones",
        )
    _emit(
        stream,
        Code.SOURCE_COMMAND_DISPATCHED,
        2,
        activity_id=episode,
        category=Category.SOURCE_CONTROL,
        requested_command="enable_heating",
        command_outcome="dispatched",
    )
    _emit(
        stream,
        Code.SOURCE_COMMAND_DISPATCHED,
        12,
        activity_id=episode,
        category=Category.SOURCE_CONTROL,
        requested_command="disable_heating",
        command_outcome="dispatched",
    )
    composer = UserActivityComposer(stream.snapshot)
    composer.process_available()

    started, stopped = composer.snapshot().activities
    assert started.activity_type is UserActivityType.HEATING_STARTED
    assert stopped.activity_type is UserActivityType.HEATING_STOPPED
    assert started.zone_ids == stopped.zone_ids == ("bedroom", "living_room")
    assert dict((item.key, item.value) for item in stopped.parameters)["duration_seconds"] == 10.0
    assert started.reported_state is None


def test_failed_heating_command_never_creates_started_or_stopped_activity() -> None:
    stream = OperationalEventStream()
    _emit(
        stream,
        Code.SOURCE_COMMAND_FAILED,
        0,
        activity_id="heating-episode:1",
        category=Category.SOURCE_CONTROL,
        requested_command="enable_heating",
        command_outcome="failed",
    )
    composer = UserActivityComposer(stream.snapshot)
    composer.process_available()
    assert all(
        activity.activity_type not in {UserActivityType.HEATING_STARTED, UserActivityType.HEATING_STOPPED}
        for activity in composer.snapshot().activities
    )


def test_failsafe_command_failure_does_not_close_supervision_lifecycle() -> None:
    stream = OperationalEventStream()
    campaign = "supervision:00000002"
    _emit(stream, Code.FAILSAFE_ENTERED, 0, activity_id=campaign, category=Category.SUPERVISION)
    _emit(
        stream,
        Code.SOURCE_COMMAND_FAILED,
        1,
        activity_id=campaign,
        category=Category.SOURCE_CONTROL,
        requested_command="disable_heating",
        command_outcome="failed",
    )
    _emit(stream, Code.RUNTIME_RECOVERED, 2, activity_id=campaign, category=Category.RUNTIME)
    composer = UserActivityComposer(stream.snapshot)

    assert composer.process_available() is True
    assert [activity.activity_type for activity in composer.snapshot().activities] == [
        UserActivityType.RUNTIME_FAILSAFE_ENTERED,
        UserActivityType.SOURCE_COMMAND_FAILED,
        UserActivityType.RUNTIME_RECOVERED,
    ]
    assert composer.snapshot().open_activity_count == 0


def test_cursor_overflow_and_failure_are_truthful() -> None:
    stream = OperationalEventStream(capacity=2)
    for sequence in range(3):
        _emit(stream, Code.RUNTIME_STARTED, sequence, activity_id=None, category=Category.RUNTIME)
    composer = UserActivityComposer(stream.snapshot, activity_capacity=1)
    assert composer.process_available() is True
    assert composer.snapshot().source_events_missed == 1
    assert composer.snapshot().source_overflow_occurrences == 1
    assert composer.snapshot().source_last_processed_sequence == 3

    _emit(stream, Code.RUNTIME_STARTED, 4, activity_id=None, category=Category.RUNTIME)
    original = composer._compose_event

    def fail(_event):
        raise RuntimeError("composition failure")

    composer._compose_event = fail  # type: ignore[method-assign]
    assert composer.process_available() is False
    assert composer.snapshot().source_last_processed_sequence == 3
    composer._compose_event = original  # type: ignore[method-assign]
    assert composer.process_available() is True
    assert composer.snapshot().source_last_processed_sequence == 4


def test_multiple_source_overflows_are_counted_independently() -> None:
    stream = OperationalEventStream(capacity=2)
    composer = UserActivityComposer(stream.snapshot)
    for sequence in range(3):
        _emit(stream, Code.RUNTIME_STARTED, sequence, activity_id=None, category=Category.RUNTIME)
    assert composer.process_available() is True

    for sequence in range(3, 6):
        _emit(stream, Code.RUNTIME_STARTED, sequence, activity_id=None, category=Category.RUNTIME)
    assert composer.process_available() is True

    snapshot = composer.snapshot()
    assert snapshot.source_events_missed == 2
    assert snapshot.source_overflow_occurrences == 2
    assert snapshot.source_last_processed_sequence == 6


def test_open_lifecycle_state_is_bounded_without_fabrication() -> None:
    stream = OperationalEventStream()
    for sequence in range(3):
        _emit(
            stream,
            Code.MEASUREMENT_BECAME_STALE,
            sequence,
            activity_id=f"measurement-incident:{sequence}",
            category=Category.MEASUREMENT,
        )
    composer = UserActivityComposer(stream.snapshot, open_activity_capacity=2)

    assert composer.process_available() is True
    snapshot = composer.snapshot()
    assert snapshot.open_activity_count == 2
    assert len(snapshot.activities) == 2
    assert snapshot.source_last_processed_sequence == 3
