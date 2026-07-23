from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.services.heat_demand_safety_policy import (
    HeatDemandClockRegressionError,
    HeatDemandSafetyPhase,
    HeatDemandSafetyPolicy,
)
from controlel.application.state.heat_demand_safety_state import (
    HeatDemandSafetyState,
)
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand import BuildingHeatDemand
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
GRACE = timedelta(minutes=5)


def demand(
    status: BuildingHeatDemandStatus,
    evaluated_at: datetime = NOW,
) -> BuildingHeatDemand:
    return BuildingHeatDemand(
        status=status,
        evaluated_at=evaluated_at,
        eligible_demands=(),
        missing_zone_ids=(),
        expired_zone_ids=(),
        future_dated_zone_ids=(),
    )


def policy(
    grace: timedelta = GRACE,
    action: HeatingAction = HeatingAction.DISABLE_HEATING,
) -> HeatDemandSafetyPolicy:
    return HeatDemandSafetyPolicy(grace, action)


@pytest.mark.parametrize("invalid", [60, "five minutes", None])
def test_non_timedelta_grace_is_rejected(invalid):
    with pytest.raises(TypeError, match="timedelta"):
        HeatDemandSafetyPolicy(invalid, HeatingAction.DISABLE_HEATING)


def test_negative_grace_is_rejected_and_zero_is_immediate_timeout():
    with pytest.raises(ValueError, match="negative"):
        policy(timedelta(microseconds=-1))

    result = policy(timedelta(0)).evaluate(
        demand(BuildingHeatDemandStatus.INDETERMINATE),
        None,
    )

    assert result.phase is HeatDemandSafetyPhase.INDETERMINATE_TIMED_OUT
    assert result.timeout_at == NOW


def test_raw_timeout_action_is_rejected_and_both_typed_actions_are_accepted():
    with pytest.raises(TypeError, match="HeatingAction"):
        HeatDemandSafetyPolicy(GRACE, "disable_heating")

    for action in HeatingAction:
        assert HeatDemandSafetyPolicy(GRACE, action).timeout_action is action


@pytest.mark.parametrize(
    ("status", "expected_action"),
    [
        (BuildingHeatDemandStatus.HEAT_REQUIRED, HeatingAction.ENABLE_HEATING),
        (BuildingHeatDemandStatus.NO_HEAT_REQUIRED, HeatingAction.DISABLE_HEATING),
    ],
)
def test_determinate_truth_table_clears_period_and_records_status(status, expected_action):
    current = HeatDemandSafetyState(
        indeterminate_since=NOW - timedelta(minutes=1),
        last_determinate_status=BuildingHeatDemandStatus.NO_HEAT_REQUIRED,
        last_evaluated_at=NOW - timedelta(seconds=1),
    )

    result = policy(action=expected_action).evaluate(demand(status), current)

    assert result.phase is HeatDemandSafetyPhase.DETERMINATE
    assert result.state.indeterminate_since is None
    assert result.state.last_determinate_status is status
    assert result.timeout_at is None
    assert result.action is None


def test_indeterminate_grace_and_exact_timeout_boundary():
    within = policy().evaluate(
        demand(BuildingHeatDemandStatus.INDETERMINATE, NOW + GRACE - datetime.resolution),
        HeatDemandSafetyState(indeterminate_since=NOW, last_evaluated_at=NOW),
    )
    boundary = policy().evaluate(
        demand(BuildingHeatDemandStatus.INDETERMINATE, NOW + GRACE),
        within.state,
    )

    assert within.phase is HeatDemandSafetyPhase.INDETERMINATE_GRACE
    assert within.action is None
    assert boundary.phase is HeatDemandSafetyPhase.INDETERMINATE_TIMED_OUT
    assert boundary.action is HeatingAction.DISABLE_HEATING


def test_persistent_period_ignores_later_hint_and_preserves_last_determinate_status():
    current = HeatDemandSafetyState(
        indeterminate_since=NOW,
        last_determinate_status=BuildingHeatDemandStatus.HEAT_REQUIRED,
        last_evaluated_at=NOW,
    )
    evaluated_at = NOW + timedelta(minutes=1)

    result = policy().evaluate(
        demand(BuildingHeatDemandStatus.INDETERMINATE, evaluated_at),
        current,
        indeterminate_start_hint=evaluated_at,
    )

    assert result.state.indeterminate_since is NOW
    assert result.state.last_determinate_status is BuildingHeatDemandStatus.HEAT_REQUIRED
    assert result.state.last_evaluated_at == evaluated_at


def test_scheduled_start_hint_is_used_and_invalid_hints_are_rejected():
    hint = NOW - timedelta(minutes=1)
    result = policy().evaluate(
        demand(BuildingHeatDemandStatus.INDETERMINATE),
        None,
        indeterminate_start_hint=hint,
    )

    assert result.state.indeterminate_since == hint
    with pytest.raises(ValueError, match="timezone-aware"):
        policy().evaluate(
            demand(BuildingHeatDemandStatus.INDETERMINATE),
            None,
            indeterminate_start_hint=datetime(2026, 1, 1, 12),
        )
    with pytest.raises(ValueError, match="later"):
        policy().evaluate(
            demand(BuildingHeatDemandStatus.INDETERMINATE),
            None,
            indeterminate_start_hint=NOW + datetime.resolution,
        )


def test_equal_evaluation_time_is_allowed_and_regression_is_explicit():
    state = HeatDemandSafetyState(last_evaluated_at=NOW)

    assert policy().evaluate(demand(BuildingHeatDemandStatus.HEAT_REQUIRED), state)

    earlier = NOW - datetime.resolution
    with pytest.raises(HeatDemandClockRegressionError) as raised:
        policy().evaluate(demand(BuildingHeatDemandStatus.HEAT_REQUIRED, earlier), state)

    assert raised.value.previous_evaluated_at == NOW
    assert raised.value.current_evaluated_at == earlier
    assert NOW.isoformat() in str(raised.value)
    assert earlier.isoformat() in str(raised.value)
