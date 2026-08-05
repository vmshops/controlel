from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.services.zone_heat_demand_confirmation_policy import (
    ZoneHeatDemandConfirmationPolicy,
)
from controlel.application.state.zone_heat_demand_confirmation_state import (
    ZoneHeatDemandConfirmationPhase,
    ZoneHeatDemandConfirmationReason,
)
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
HEAT = BuildingHeatDemandStatus.HEAT_REQUIRED
NO_HEAT = BuildingHeatDemandStatus.NO_HEAT_REQUIRED
INDETERMINATE = BuildingHeatDemandStatus.INDETERMINATE


def evaluate(
    policy: ZoneHeatDemandConfirmationPolicy,
    demand: BuildingHeatDemandStatus,
    *,
    at: datetime = NOW,
    state=None,
    deadline: bool = False,
):
    return policy.evaluate(
        hysteresis_demand=demand,
        now=at,
        current_state=state,
        deadline_reevaluation=deadline,
    )


def test_zero_duration_preserves_immediate_legacy_behavior() -> None:
    result = evaluate(
        ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(0)),
        HEAT,
    )

    assert result.output_demand is HEAT
    assert result.state.phase is ZoneHeatDemandConfirmationPhase.HEAT_REQUIRED_CONFIRMED
    assert result.state.last_reason is ZoneHeatDemandConfirmationReason.BYPASSED_ZERO_DURATION
    assert result.state.confirmation_deadline is None


def test_confirmation_starts_and_repeated_demand_keeps_one_deadline() -> None:
    policy = ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(minutes=2))
    started = evaluate(policy, HEAT)
    repeated = evaluate(
        policy,
        HEAT,
        at=NOW + timedelta(seconds=30),
        state=started.state,
    )

    assert started.output_demand is NO_HEAT
    assert started.state.phase is ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING
    assert started.state.confirmation_started_at == NOW
    assert started.state.confirmation_deadline == NOW + timedelta(minutes=2)
    assert repeated.state.confirmation_started_at == started.state.confirmation_started_at
    assert repeated.state.confirmation_deadline == started.state.confirmation_deadline


def test_one_microsecond_before_deadline_remains_pending() -> None:
    policy = ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(minutes=2))
    started = evaluate(policy, HEAT)

    result = evaluate(
        policy,
        HEAT,
        at=NOW + timedelta(minutes=2) - timedelta(microseconds=1),
        state=started.state,
    )

    assert result.output_demand is NO_HEAT
    assert result.state.phase is ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING


def test_exact_deadline_confirms_only_current_heat_demand() -> None:
    policy = ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(minutes=2))
    started = evaluate(policy, HEAT)

    result = evaluate(
        policy,
        HEAT,
        at=NOW + timedelta(minutes=2),
        state=started.state,
        deadline=True,
    )

    assert result.output_demand is HEAT
    assert result.state.phase is ZoneHeatDemandConfirmationPhase.HEAT_REQUIRED_CONFIRMED
    assert result.state.last_reason is ZoneHeatDemandConfirmationReason.COMPLETED


def test_demand_clearing_cancels_pending_immediately() -> None:
    policy = ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(minutes=2))
    started = evaluate(policy, HEAT)

    result = evaluate(
        policy,
        NO_HEAT,
        at=NOW + timedelta(seconds=40),
        state=started.state,
    )

    assert result.output_demand is NO_HEAT
    assert result.state.confirmation_deadline is None
    assert result.state.last_reason is (ZoneHeatDemandConfirmationReason.CANCELLED_DEMAND_CLEARED)


def test_demand_clear_at_deadline_does_not_complete_confirmation() -> None:
    policy = ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(minutes=2))
    started = evaluate(policy, HEAT)

    result = evaluate(
        policy,
        NO_HEAT,
        at=NOW + timedelta(minutes=2),
        state=started.state,
        deadline=True,
    )

    assert result.output_demand is NO_HEAT
    assert result.state.last_reason is (ZoneHeatDemandConfirmationReason.EXPIRED_BUT_DEMAND_CHANGED)


def test_indeterminate_cancels_pending_and_recovery_starts_full_interval() -> None:
    policy = ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(minutes=2))
    started = evaluate(policy, HEAT)
    invalid = evaluate(
        policy,
        INDETERMINATE,
        at=NOW + timedelta(seconds=90),
        state=started.state,
    )
    recovered_at = NOW + timedelta(seconds=100)
    recovered = evaluate(
        policy,
        HEAT,
        at=recovered_at,
        state=invalid.state,
    )

    assert invalid.output_demand is INDETERMINATE
    assert invalid.state.last_reason is (ZoneHeatDemandConfirmationReason.CANCELLED_MEASUREMENT_INDETERMINATE)
    assert invalid.state.confirmation_deadline is None
    assert recovered.output_demand is NO_HEAT
    assert recovered.state.confirmation_started_at == recovered_at
    assert recovered.state.confirmation_deadline == recovered_at + timedelta(minutes=2)


def test_confirmed_demand_survives_indeterminate_state_for_valid_recovery() -> None:
    policy = ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(minutes=2))
    pending = evaluate(policy, HEAT)
    confirmed = evaluate(
        policy,
        HEAT,
        at=NOW + timedelta(minutes=2),
        state=pending.state,
    )
    invalid = evaluate(
        policy,
        INDETERMINATE,
        at=NOW + timedelta(minutes=3),
        state=confirmed.state,
    )
    recovered = evaluate(
        policy,
        HEAT,
        at=NOW + timedelta(minutes=4),
        state=invalid.state,
    )

    assert invalid.output_demand is INDETERMINATE
    assert invalid.state.confirmed_demand is HEAT
    assert recovered.output_demand is HEAT
    assert recovered.state.confirmation_deadline is None


def test_confirmed_demand_is_removed_without_turn_off_delay() -> None:
    policy = ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(minutes=2))
    pending = evaluate(policy, HEAT)
    confirmed = evaluate(
        policy,
        HEAT,
        at=NOW + timedelta(minutes=2),
        state=pending.state,
    )

    cleared = evaluate(
        policy,
        NO_HEAT,
        at=NOW + timedelta(minutes=3),
        state=confirmed.state,
    )

    assert cleared.output_demand is NO_HEAT
    assert cleared.state.phase is ZoneHeatDemandConfirmationPhase.NO_HEAT_REQUIRED


def test_stop_and_fatal_clear_pending_deadline() -> None:
    policy = ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(minutes=2))
    pending = evaluate(policy, HEAT)

    stopped = policy.stopped_state(
        pending.state,
        now=NOW + timedelta(seconds=1),
    )
    fatal = policy.fatal_state(
        pending.state,
        now=NOW + timedelta(seconds=1),
    )

    assert stopped.phase is ZoneHeatDemandConfirmationPhase.STOPPED
    assert fatal.phase is ZoneHeatDemandConfirmationPhase.FATAL_ERROR
    assert stopped.confirmation_deadline is None
    assert fatal.confirmation_deadline is None


def test_remaining_duration_never_becomes_negative() -> None:
    policy = ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(seconds=1))
    pending = evaluate(policy, HEAT)

    assert pending.state.remaining_at(NOW + timedelta(seconds=2)) == timedelta(0)


def test_timezone_aware_timestamps_are_required() -> None:
    policy = ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(seconds=1))

    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate(policy, HEAT, at=datetime(2026, 1, 1, 12))


def test_duration_must_be_non_negative() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(seconds=-1))
