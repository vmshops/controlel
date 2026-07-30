from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.controlel.operational import (
    TRACE_LIMIT,
    ActiveLockoutType,
    CommandOutcome,
    DecisionCode,
    DecisionReason,
    DecisionTraceRecord,
    HeatDemandState,
    MeasurementStatus,
    OperationalSnapshotSource,
    RuntimeStatus,
    SafetyState,
    initial_snapshot,
    snapshot_to_dict,
    trace_to_dict,
)

NOW = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)


def source() -> OperationalSnapshotSource:
    return OperationalSnapshotSource(
        initial_snapshot(
            now=NOW,
            zone_name="Living room",
            zone_id="living_room",
            sensor_name="Room temperature",
            sensor_id="room_temperature",
            temperature_entity_id="sensor.room_temperature",
            target_temperature=21.0,
            heating_turn_on_differential=0.3,
            heating_turn_off_differential=0.1,
            timeout_action="disable_heating",
            integration_version="0.4.0",
            core_version="0.2.0",
        )
    )


def trace(timestamp: datetime, number: int = 0) -> DecisionTraceRecord:
    return DecisionTraceRecord(
        decision_code=DecisionCode.COMMAND_DISPATCHED,
        reason_code=DecisionReason.TEMPERATURE_BELOW_TARGET,
        timestamp=timestamp,
        measured_temperature=19.0,
        target_temperature=21.0,
        resulting_demand=HeatDemandState.HEAT_REQUIRED,
        requested_command="enable_heating",
        command_outcome=CommandOutcome.DISPATCHED,
        safety_state=SafetyState.NORMAL,
        sequence=number,
    )


def test_snapshot_is_immutable_and_revisions_are_monotonic() -> None:
    snapshots = source()

    with pytest.raises(FrozenInstanceError):
        snapshots.current.runtime_status = RuntimeStatus.ACTIVE

    first = snapshots.update(now=NOW + timedelta(seconds=1), runtime_status=RuntimeStatus.ACTIVE)
    second = snapshots.update(now=NOW + timedelta(seconds=2), current_temperature=20.0)

    assert (first.revision, second.revision) == (1, 2)
    assert first.runtime_status is RuntimeStatus.ACTIVE
    assert first.current_temperature is None
    assert second.current_temperature == 20.0


def test_subscriber_gets_current_snapshot_immediately_and_unsubscribe_is_idempotent() -> None:
    snapshots = source()
    received = []

    unsubscribe = snapshots.subscribe(received.append)
    snapshots.update(now=NOW + timedelta(seconds=1), runtime_status=RuntimeStatus.ACTIVE)
    unsubscribe()
    unsubscribe()
    snapshots.update(now=NOW + timedelta(seconds=2), runtime_status=RuntimeStatus.STOPPED)

    assert [item.revision for item in received] == [0, 1]


def test_elapsed_values_advance_without_a_measurement_event() -> None:
    snapshots = source()
    deadline = NOW + timedelta(minutes=2)
    snapshots.update(
        now=NOW,
        measurement_timestamp=NOW - timedelta(seconds=10),
        safety_state=SafetyState.INDETERMINATE_GRACE,
        grace_deadline=deadline,
    )

    refreshed = snapshots.refresh_elapsed(NOW + timedelta(seconds=30))

    assert refreshed.measurement_age_seconds == 40
    assert refreshed.grace_remaining_seconds == 90


def test_expired_lockout_never_exposes_negative_remaining_duration() -> None:
    snapshots = source()
    snapshots.update(
        now=NOW,
        active_lockout_type=ActiveLockoutType.MINIMUM_ON,
        minimum_on_deadline=NOW + timedelta(seconds=10),
    )

    assert snapshots.snapshot_at(NOW + timedelta(seconds=5)).lockout_remaining_seconds == 5
    assert snapshots.snapshot_at(NOW + timedelta(seconds=10)).lockout_remaining_seconds is None


def test_grace_visibility_is_truthful_across_lifecycle_and_stale_updates() -> None:
    snapshots = source()
    assert snapshots.snapshot_at(NOW).grace_remaining_seconds is None
    assert snapshots.snapshot_at(NOW).grace_deadline is None

    deadline = NOW + timedelta(seconds=60)
    started = snapshots.update(
        now=NOW,
        safety_state=SafetyState.INDETERMINATE_GRACE,
        grace_deadline=deadline,
    )
    assert started.grace_remaining_seconds == 60
    assert snapshots.snapshot_at(NOW + timedelta(seconds=30)).grace_remaining_seconds == 30

    recovered = snapshots.update(
        now=NOW + timedelta(seconds=31),
        safety_state=SafetyState.NORMAL,
        grace_deadline=None,
    )
    assert recovered.grace_remaining_seconds is None
    assert recovered.grace_deadline is None

    second_deadline = NOW + timedelta(seconds=120)
    snapshots.update(
        now=NOW + timedelta(seconds=60),
        safety_state=SafetyState.INDETERMINATE_GRACE,
        grace_deadline=second_deadline,
    )
    timed_out = snapshots.update(
        now=second_deadline,
        safety_state=SafetyState.TIMEOUT_ACTION_APPLIED,
        grace_deadline=None,
    )
    assert timed_out.grace_remaining_seconds is None
    assert timed_out.grace_deadline is None

    normal = snapshots.update(
        now=second_deadline + timedelta(seconds=1),
        safety_state=SafetyState.NORMAL,
    )
    assert normal.grace_remaining_seconds is None
    assert normal.grace_deadline is None

    reloaded = source()
    assert reloaded.current.grace_remaining_seconds is None
    assert reloaded.current.grace_deadline is None

    snapshots.close()
    stale_callback = snapshots.update(
        now=second_deadline + timedelta(seconds=2),
        safety_state=SafetyState.INDETERMINATE_GRACE,
        grace_deadline=second_deadline + timedelta(minutes=1),
    )
    assert stale_callback.safety_state is SafetyState.NORMAL
    assert stale_callback.grace_remaining_seconds is None
    assert stale_callback.grace_deadline is None


def test_trace_is_bounded_and_records_use_snapshot_revision_sequence() -> None:
    snapshots = source()

    for number in range(TRACE_LIMIT + 5):
        timestamp = NOW + timedelta(seconds=number)
        snapshots.update(now=timestamp, trace_record=trace(timestamp, number))

    assert len(snapshots.trace) == TRACE_LIMIT
    assert snapshots.trace[0].sequence == 6
    assert snapshots.trace[-1].sequence == TRACE_LIMIT + 5
    assert snapshots.current.last_decision is DecisionCode.COMMAND_DISPATCHED


def test_close_detaches_subscribers_and_prevents_stale_updates() -> None:
    snapshots = source()
    received = []
    snapshots.subscribe(received.append)
    snapshots.close()

    result = snapshots.update(now=NOW + timedelta(seconds=1), runtime_status=RuntimeStatus.ACTIVE)

    assert result.revision == 0
    assert snapshots.current.runtime_status is RuntimeStatus.STARTING
    assert len(received) == 1


def test_diagnostics_serialization_uses_json_safe_stable_values() -> None:
    snapshots = source()
    snapshots.update(now=NOW, trace_record=trace(NOW))

    payload = snapshot_to_dict(snapshots.current)
    records = trace_to_dict(snapshots.trace)

    assert payload["runtime_status"] == "starting"
    assert payload["updated_at"] == NOW.isoformat()
    assert records == [
        {
            "decision_code": "command_dispatched",
            "reason_code": "temperature_below_target",
            "timestamp": NOW.isoformat(),
            "measured_temperature": 19.0,
            "target_temperature": 21.0,
            "resulting_demand": "heat_required",
            "requested_command": "enable_heating",
            "command_outcome": "dispatched",
            "safety_state": "normal",
            "raw_demand": None,
            "hysteresis_demand": None,
            "source_control_state": None,
            "deferred_reason": None,
            "safety_bypassed_lockout": False,
            "emergency_disable_outcome": "none",
            "sequence": 1,
        }
    ]


def test_latest_input_status_and_active_demand_cause_remove_ambiguous_snapshot_mapping() -> None:
    snapshots = source()
    snapshots.update(
        now=NOW,
        measurement_status=MeasurementStatus.STALE,
        latest_input_status=MeasurementStatus.STALE,
        demand_reason=DecisionReason.MEASUREMENT_STALE,
        active_demand_cause=DecisionReason.MEASUREMENT_STALE,
    )

    snapshot = snapshots.update(
        now=NOW + timedelta(seconds=1),
        measurement_status=MeasurementStatus.INVALID_VALUE,
        latest_input_status=MeasurementStatus.INVALID_VALUE,
    )

    assert snapshot.latest_input_status is MeasurementStatus.INVALID_VALUE
    assert snapshot.active_demand_cause is DecisionReason.MEASUREMENT_STALE
