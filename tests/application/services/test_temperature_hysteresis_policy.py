from math import inf, nan

import pytest

from controlel.application.services.temperature_hysteresis_policy import (
    TemperatureHysteresisPolicy,
    TemperatureHysteresisReason,
)
from controlel.application.state.temperature_hysteresis_state import (
    HysteresisDemandState,
)


def policy(on: float = 0.3, off: float = 0.1) -> TemperatureHysteresisPolicy:
    return TemperatureHysteresisPolicy(
        turn_on_differential=on,
        turn_off_differential=off,
    )


def evaluate(
    current: float,
    *,
    previous: HysteresisDemandState | None = None,
    raw: bool | None = None,
    configured: TemperatureHysteresisPolicy | None = None,
):
    current_state = None
    if previous is not None:
        from controlel.application.state.temperature_hysteresis_state import (
            TemperatureHysteresisState,
        )

        current_state = TemperatureHysteresisState(demand=previous)
    return (configured or policy()).evaluate(
        current_temperature=current,
        target_temperature=22.5,
        raw_requires_heat=current < 22.5 if raw is None else raw,
        current_state=current_state,
    )


def test_exact_asymmetric_thresholds_and_equality() -> None:
    enabled = evaluate(22.2, previous=HysteresisDemandState.NO_HEAT_REQUIRED)
    disabled = evaluate(22.6, previous=HysteresisDemandState.HEAT_REQUIRED)

    assert (enabled.enable_threshold, enabled.disable_threshold) == (
        pytest.approx(22.2),
        pytest.approx(22.6),
    )
    assert enabled.state.demand is HysteresisDemandState.HEAT_REQUIRED
    assert enabled.reason is TemperatureHysteresisReason.BELOW_ENABLE_THRESHOLD
    assert disabled.state.demand is HysteresisDemandState.NO_HEAT_REQUIRED
    assert disabled.reason is TemperatureHysteresisReason.ABOVE_DISABLE_THRESHOLD


@pytest.mark.parametrize(
    ("previous", "expected"),
    [
        (
            HysteresisDemandState.HEAT_REQUIRED,
            HysteresisDemandState.HEAT_REQUIRED,
        ),
        (
            HysteresisDemandState.NO_HEAT_REQUIRED,
            HysteresisDemandState.NO_HEAT_REQUIRED,
        ),
    ],
)
def test_deadband_preserves_previous_resolved_demand(previous, expected) -> None:
    assessment = evaluate(22.4, previous=previous)

    assert assessment.state.demand is expected
    assert assessment.preserved_previous_demand is True
    assert assessment.reason is TemperatureHysteresisReason.PRESERVED_PREVIOUS_DEMAND


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, HysteresisDemandState.HEAT_REQUIRED),
        (False, HysteresisDemandState.NO_HEAT_REQUIRED),
    ],
)
def test_startup_inside_deadband_uses_raw_exact_threshold_deterministically(
    raw,
    expected,
) -> None:
    assessment = evaluate(22.4 if raw else 22.55, raw=raw)

    assert assessment.state.demand is expected
    assert assessment.reason is TemperatureHysteresisReason.STARTUP_FROM_RAW_DEMAND


@pytest.mark.parametrize(
    ("previous", "temperature", "expected"),
    [
        (previous, temperature, expected)
        for previous in HysteresisDemandState
        for temperature, expected in (
            (22.49, HysteresisDemandState.HEAT_REQUIRED),
            (22.5, HysteresisDemandState.NO_HEAT_REQUIRED),
            (22.51, HysteresisDemandState.NO_HEAT_REQUIRED),
        )
    ],
)
def test_zero_hysteresis_is_exact_legacy_mode(previous, temperature, expected) -> None:
    assessment = evaluate(
        temperature,
        previous=previous,
        configured=policy(0, 0),
    )

    assert assessment.state.demand is expected
    assert assessment.reason is TemperatureHysteresisReason.LEGACY_EXACT_THRESHOLD


@pytest.mark.parametrize("previous", list(HysteresisDemandState))
def test_zero_hysteresis_repeated_target_equality_never_alternates(previous) -> None:
    configured = policy(0, 0)

    first = evaluate(22.5, previous=previous, configured=configured)
    second = evaluate(22.5, previous=first.state.demand, configured=configured)
    third = evaluate(22.5, previous=second.state.demand, configured=configured)

    assert [item.state.demand for item in (first, second, third)] == [
        HysteresisDemandState.NO_HEAT_REQUIRED,
    ] * 3


@pytest.mark.parametrize("value", [-0.1, nan, inf, -inf])
def test_invalid_differentials_are_rejected(value: float) -> None:
    with pytest.raises((TypeError, ValueError)):
        TemperatureHysteresisPolicy(
            turn_on_differential=value,
            turn_off_differential=0.1,
        )


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_non_finite_temperatures_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        policy().evaluate(
            current_temperature=value,
            target_temperature=22.5,
            raw_requires_heat=False,
            current_state=None,
        )
