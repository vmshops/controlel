from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.controlel.observability import ObservabilityController
from custom_components.controlel.operational import (
    ActiveLockoutType,
    ConfirmationState,
    DecisionCode,
    DecisionReason,
    DecisionTraceRecord,
    HeatDemandState,
    OperationalSnapshotSource,
    SafetyState,
    initial_snapshot,
)

NOW = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)


def source() -> OperationalSnapshotSource:
    return OperationalSnapshotSource(
        initial_snapshot(
            now=NOW,
            zone_name="Living room",
            zone_id="living_room",
            sensor_name="Temperature",
            sensor_id="temperature",
            temperature_entity_id="sensor.temperature",
            target_temperature=21.0,
            heating_turn_on_differential=0.3,
            heating_turn_off_differential=0.1,
            heat_demand_confirmation_duration_seconds=120.0,
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


@dataclass
class ScheduledInterval:
    callback: object
    interval: timedelta
    cancelled: bool = False


class FakeIntervals:
    def __init__(self) -> None:
        self.installed: list[ScheduledInterval] = []

    def subscribe(self, hass, callback, interval):
        del hass
        scheduled = ScheduledInterval(callback, interval)
        self.installed.append(scheduled)

        def cancel() -> None:
            scheduled.cancelled = True

        return cancel


def controller(
    profile: str,
    *,
    debug_duration: timedelta | None = timedelta(hours=1),
) -> tuple[ObservabilityController, OperationalSnapshotSource, FakeIntervals]:
    snapshots = source()
    intervals = FakeIntervals()
    result = ObservabilityController(
        hass=object(),
        source=snapshots,
        configured_profile=profile,
        profile_before_debug="detailed",
        debug_duration=debug_duration,
        interval_subscriber=intervals.subscribe,
        logger=__import__("logging").getLogger(__name__),
        now=lambda: NOW,
    )
    return result, snapshots, intervals


@pytest.mark.parametrize(
    ("profile", "seconds", "capacity"),
    [
        ("basic", None, 20),
        ("detailed", 10.0, 100),
        ("debug", 1.0, 500),
    ],
)
def test_profile_cadence_and_trace_capacity(
    profile: str,
    seconds: float | None,
    capacity: int,
) -> None:
    profile_controller, snapshots, _ = controller(profile)

    profile_controller.start()

    assert snapshots.current.diagnostic_refresh_cadence_seconds == seconds
    assert snapshots.trace_capacity == capacity
    assert snapshots.current.trace_capacity == capacity


def test_only_active_countdowns_install_debug_refresh() -> None:
    profile_controller, snapshots, intervals = controller(
        "debug",
        debug_duration=None,
    )
    profile_controller.start()
    assert intervals.installed == []

    snapshots.update(
        now=NOW,
        active_lockout_type=ActiveLockoutType.MINIMUM_OFF,
        active_lockout_deadline=NOW + timedelta(seconds=30),
        minimum_off_deadline=NOW + timedelta(seconds=30),
    )

    assert intervals.installed[-1].interval == timedelta(seconds=1)
    intervals.installed[-1].callback(NOW + timedelta(seconds=30))
    assert snapshots.current.lockout_remaining_seconds is None
    assert intervals.installed[-1].cancelled is True


def test_detailed_refresh_uses_ten_seconds_and_basic_never_installs() -> None:
    detailed, detailed_source, detailed_intervals = controller("detailed")
    detailed.start()
    detailed_source.update(
        now=NOW,
        safety_state=SafetyState.INDETERMINATE_GRACE,
        grace_deadline=NOW + timedelta(seconds=60),
    )
    assert detailed_intervals.installed[-1].interval == timedelta(seconds=10)

    basic, basic_source, basic_intervals = controller("basic")
    basic.start()
    basic_source.update(
        now=NOW,
        safety_state=SafetyState.INDETERMINATE_GRACE,
        grace_deadline=NOW + timedelta(seconds=60),
    )
    assert basic_intervals.installed == []


def test_passive_boundaries_never_install_periodic_refresh() -> None:
    for profile in ("basic", "detailed", "debug"):
        profile_controller, snapshots, intervals = controller(profile, debug_duration=None)
        profile_controller.start()
        snapshots.update(
            now=NOW,
            earliest_next_enable_time=NOW + timedelta(seconds=30),
            minimum_off_deadline=NOW + timedelta(seconds=30),
        )

        assert intervals.installed == []


def test_debug_expiry_returns_to_previous_profile_without_reload() -> None:
    profile_controller, snapshots, intervals = controller(
        "debug",
        debug_duration=timedelta(minutes=60),
    )
    profile_controller.start()
    scheduled = intervals.installed[-1]

    scheduled.callback(NOW + timedelta(minutes=60))

    assert scheduled.cancelled is True
    assert profile_controller.active_profile == "detailed"
    assert snapshots.current.diagnostic_profile == "detailed"
    assert snapshots.current.debug_expiry_deadline is None
    assert snapshots.trace_capacity == 100


def test_manual_debug_has_no_expiry_and_stop_rejects_stale_callback() -> None:
    profile_controller, snapshots, intervals = controller(
        "debug",
        debug_duration=None,
    )
    profile_controller.start()
    snapshots.update(
        now=NOW,
        safety_state=SafetyState.INDETERMINATE_GRACE,
        grace_deadline=NOW + timedelta(seconds=10),
    )
    scheduled = intervals.installed[-1]
    revision = snapshots.current.revision

    profile_controller.stop()
    scheduled.callback(NOW + timedelta(seconds=1))

    assert scheduled.cancelled is True
    assert snapshots.current.revision == revision
    assert snapshots.current.debug_expiry_deadline is None


def test_profile_trace_capacity_remains_bounded() -> None:
    profile_controller, snapshots, _ = controller("detailed")
    profile_controller.start()
    for number in range(120):
        timestamp = NOW + timedelta(seconds=number)
        snapshots.update(
            now=timestamp,
            trace_record=DecisionTraceRecord(
                decision_code=DecisionCode.HEAT_REQUESTED,
                reason_code=DecisionReason.BELOW_ENABLE_THRESHOLD,
                timestamp=timestamp,
                measured_temperature=20.0,
                target_temperature=21.0,
                resulting_demand=HeatDemandState.HEAT_REQUIRED,
                requested_command=None,
                command_outcome="none",
                safety_state=SafetyState.NORMAL,
            ),
        )

    assert len(snapshots.trace) == 100


def test_diagnostics_explain_configured_and_inactive_countdowns() -> None:
    profile_controller, snapshots, _ = controller("detailed")
    profile_controller.start()

    payload = profile_controller.diagnostics(NOW)

    assert payload["countdowns"]["minimum_heating_on"] == {
        "configured_duration_seconds": 600.0,
        "active": False,
        "deadline": None,
        "remaining_seconds": None,
        "reason": "successful_enable_command",
        "expiry_action": "reevaluate_current_source_demand",
    }
    assert payload["countdowns"]["debug_profile_expiry"]["configured_duration_seconds"] == 3600.0


@pytest.mark.parametrize(
    ("state", "deadline_field", "name"),
    [
        (
            {
                "active_lockout_type": ActiveLockoutType.MINIMUM_OFF,
                "active_lockout_deadline": NOW + timedelta(seconds=30),
            },
            "minimum_off_deadline",
            "minimum_heating_off",
        ),
        (
            {"safety_state": SafetyState.INDETERMINATE_GRACE},
            "grace_deadline",
            "sensor_failure_grace",
        ),
        (
            {
                "confirmation_state": ConfirmationState.CONFIRMATION_PENDING,
                "confirmation_started_at": NOW,
            },
            "confirmation_deadline",
            "heat_demand_confirmation",
        ),
    ],
)
def test_active_lockout_and_grace_use_profile_cadence_without_regulation_changes(
    state: dict[str, object],
    deadline_field: str,
    name: str,
) -> None:
    profile_controller, snapshots, intervals = controller("debug", debug_duration=None)
    profile_controller.start()
    snapshots.update(
        now=NOW,
        **state,
        **{deadline_field: NOW + timedelta(seconds=30)},
    )

    assert intervals.installed[-1].interval == timedelta(seconds=1)
    assert name in profile_controller.diagnostics(NOW)["active_countdown_names"]
