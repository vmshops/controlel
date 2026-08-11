from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.controlel.operational import (
    TRACE_LIMIT,
    ActiveLockoutType,
    CommandOutcome,
    ConfirmationState,
    DecisionCode,
    DecisionReason,
    DecisionTraceRecord,
    EmergencyDisableOutcome,
    HeatDemandState,
    MeasurementStatus,
    OperationalSnapshotSource,
    OperationalSummaryCode,
    RuntimeStatus,
    SafetyState,
    SourceControlState,
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
            primary_measurement_max_age_seconds=300.0,
            sensor_failure_grace_period_seconds=60.0,
            minimum_heating_on_time_seconds=600.0,
            minimum_heating_off_time_seconds=300.0,
            timeout_action="disable_heating",
            diagnostic_profile="basic",
            diagnostic_refresh_cadence_seconds=None,
            debug_expiry_deadline=None,
            debug_profile_duration_seconds=3600.0,
            trace_capacity=20,
            integration_version="0.8.0",
            core_version="0.5.0",
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
        active_lockout_deadline=NOW + timedelta(seconds=10),
        minimum_on_deadline=NOW + timedelta(seconds=10),
    )

    assert snapshots.snapshot_at(NOW + timedelta(seconds=5)).lockout_remaining_seconds == 5
    assert snapshots.snapshot_at(NOW + timedelta(seconds=10)).lockout_remaining_seconds is None


def test_passive_boundary_does_not_create_lockout_or_deferred_countdown() -> None:
    snapshots = source()
    boundary = NOW + timedelta(minutes=5)
    snapshot = snapshots.update(
        now=NOW,
        runtime_status=RuntimeStatus.ACTIVE,
        zone_heat_demand=HeatDemandState.NO_HEAT_REQUIRED,
        source_control_state=SourceControlState.HEATING_NOT_REQUESTED,
        earliest_next_enable_time=boundary,
        minimum_off_deadline=boundary,
        aggregate_demand="disable_heating",
    )

    assert snapshot.earliest_next_enable_time == boundary
    assert snapshot.active_lockout_type is None
    assert snapshot.active_lockout_deadline is None
    assert snapshot.active_lockout_remaining_seconds is None
    assert snapshot.deferred_command is None
    assert snapshot.deferred_remaining_seconds is None
    assert snapshot.source_control_summary == (
        f"No heating requested; next enable allowed after {boundary.isoformat()}."
    )


def test_active_lockout_and_deferred_countdowns_share_the_truthful_deadline() -> None:
    snapshots = source()
    deadline = NOW + timedelta(seconds=42)
    snapshot = snapshots.update(
        now=NOW,
        runtime_status=RuntimeStatus.ACTIVE,
        zone_heat_demand=HeatDemandState.HEAT_REQUIRED,
        active_lockout_type=ActiveLockoutType.MINIMUM_OFF,
        active_lockout_deadline=deadline,
        deferred_command="enable_heating",
        deferred_reason="minimum_off_time_active",
        deferred_since=NOW,
        deferred_deadline=deadline,
    )

    assert snapshot.active_lockout_remaining_seconds == 42
    assert snapshot.deferred_remaining_seconds == 42
    assert snapshot.source_control_summary == ("Heating requested; waiting for minimum-off protection: 42 s.")
    payload = snapshot_to_dict(snapshot)
    assert payload["active_lockout_deadline"] == deadline.isoformat()
    assert payload["deferred_since"] == NOW.isoformat()
    assert payload["deferred_deadline"] == deadline.isoformat()


def test_minimum_on_and_safety_summaries_never_claim_physical_state() -> None:
    snapshots = source()
    deadline = NOW + timedelta(seconds=18)
    waiting = snapshots.update(
        now=NOW,
        runtime_status=RuntimeStatus.ACTIVE,
        zone_heat_demand=HeatDemandState.NO_HEAT_REQUIRED,
        active_lockout_type=ActiveLockoutType.MINIMUM_ON,
        active_lockout_deadline=deadline,
        deferred_command="disable_heating",
        deferred_reason="minimum_on_time_active",
        deferred_since=NOW,
        deferred_deadline=deadline,
    )

    assert waiting.source_control_summary == ("Heating no longer requested; waiting for minimum-on protection: 18 s.")

    bypassed = snapshots.update(
        now=NOW,
        active_lockout_type=None,
        active_lockout_deadline=None,
        deferred_command=None,
        deferred_reason=None,
        deferred_since=None,
        deferred_deadline=None,
        safety_bypassed_lockout=True,
    )

    assert bypassed.source_control_summary == "Safety disable bypassed minimum-on protection."
    assert "boiler" not in bypassed.source_control_summary.casefold()


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
            "confirmed_zone_demand": None,
            "confirmation_state": None,
            "confirmation_reason": None,
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


def test_confirmation_countdown_is_active_only_while_pending() -> None:
    snapshots = source()
    deadline = NOW + timedelta(seconds=120)

    pending = snapshots.update(
        now=NOW,
        heat_demand_confirmation_duration_seconds=120.0,
        confirmation_state=ConfirmationState.CONFIRMATION_PENDING,
        confirmation_started_at=NOW,
        confirmation_deadline=deadline,
        confirmation_reason="heat_demand_confirmation_started",
    )
    refreshed = snapshots.refresh_elapsed(NOW + timedelta(seconds=36))

    assert pending.confirmation_remaining_seconds == 120.0
    assert refreshed.confirmation_remaining_seconds == 84.0
    completed = snapshots.update(
        now=deadline,
        confirmation_state=ConfirmationState.HEAT_REQUIRED_CONFIRMED,
        confirmation_started_at=None,
        confirmation_deadline=None,
    )
    assert completed.confirmation_remaining_seconds is None


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {
                "runtime_status": RuntimeStatus.ACTIVE,
                "zone_heat_demand": HeatDemandState.NO_HEAT_REQUIRED,
            },
            OperationalSummaryCode.NO_HEAT_REQUESTED,
        ),
        (
            {
                "runtime_status": RuntimeStatus.ACTIVE,
                "zone_heat_demand": HeatDemandState.HEAT_REQUIRED,
            },
            OperationalSummaryCode.HEAT_REQUESTED,
        ),
        (
            {
                "runtime_status": RuntimeStatus.ACTIVE,
                "zone_heat_demand": HeatDemandState.HEAT_REQUIRED,
                "active_lockout_type": ActiveLockoutType.MINIMUM_OFF,
                "minimum_off_deadline": NOW + timedelta(seconds=48),
            },
            OperationalSummaryCode.HEAT_DEFERRED_MINIMUM_OFF,
        ),
        (
            {
                "runtime_status": RuntimeStatus.ACTIVE,
                "safety_state": SafetyState.INDETERMINATE_GRACE,
                "grace_deadline": NOW + timedelta(seconds=60),
            },
            OperationalSummaryCode.SENSOR_FAILURE_GRACE,
        ),
        (
            {
                "runtime_status": RuntimeStatus.FATAL_ERROR,
                "emergency_disable_outcome": EmergencyDisableOutcome.FAILED,
            },
            OperationalSummaryCode.FATAL_EMERGENCY_DISABLE_FAILED,
        ),
    ],
)
def test_human_summary_selects_stable_non_physical_machine_code(
    changes: dict[str, object],
    expected: OperationalSummaryCode,
) -> None:
    snapshots = source()

    snapshot = snapshots.update(now=NOW, **changes)

    assert snapshot.operational_summary_code is expected
    assert "boiler" not in snapshot.operational_summary_translation_key
    assert "physically" not in snapshot.operational_summary_translation_key


def test_elapsed_refresh_only_notifies_countdown_subscribers() -> None:
    snapshots = source()
    static: list[object] = []
    countdown: list[object] = []
    snapshots.subscribe(static.append)
    snapshots.subscribe(countdown.append, elapsed_refresh=True)

    snapshots.refresh_elapsed(NOW + timedelta(seconds=1))

    assert len(static) == 1
    assert len(countdown) == 2
