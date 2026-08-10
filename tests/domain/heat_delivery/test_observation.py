from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.heat_delivery import (
    HeatDeliveryActuatorId,
    HeatDeliveryCapabilities,
    HeatDeliveryMode,
    HeatDeliveryObservation,
    HeatingDemandTransition,
    HeatingEpisode,
    HeatingEpisodeSample,
    HeatSourceObservation,
    ObservationQuality,
    ObservedValue,
)
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_observation_quality_has_only_explainable_states() -> None:
    assert {quality.value for quality in ObservationQuality} == {
        "unknown",
        "valid",
        "stale",
        "degraded",
        "conflicting",
        "unsupported",
    }


def test_observed_values_are_immutable_and_keep_missing_distinct_from_stale() -> None:
    unknown = ObservedValue[float].unknown("measurement missing")
    stale = ObservedValue(
        value=20.0,
        observed_at=NOW - timedelta(hours=1),
        quality=ObservationQuality.STALE,
        reason="measurement expired",
    )

    assert unknown.value is None
    assert unknown.observed_at is None
    assert stale.value == 20.0
    assert stale.observed_at == NOW - timedelta(hours=1)
    with pytest.raises(FrozenInstanceError):
        stale.value = 21.0  # type: ignore[misc]


@pytest.mark.parametrize(
    "quality",
    [ObservationQuality.VALID, ObservationQuality.STALE],
)
def test_value_bearing_quality_requires_value_and_source_timestamp(quality: ObservationQuality) -> None:
    with pytest.raises(ValueError, match="requires a value and timestamp"):
        ObservedValue(value=None, observed_at=None, quality=quality, reason="missing")


def test_degraded_and_conflicting_quality_require_an_explainable_reason() -> None:
    for quality in (ObservationQuality.DEGRADED, ObservationQuality.CONFLICTING):
        with pytest.raises(ValueError, match="explainable reason"):
            ObservedValue(value=20.0, observed_at=NOW, quality=quality)


def test_requested_position_and_reported_position_remain_separate() -> None:
    observation = HeatDeliveryObservation(
        zone_id=ZoneId("living_room"),
        actuator_id=HeatDeliveryActuatorId("valve"),
        captured_at=NOW,
        mode=HeatDeliveryMode.DIRECT_POSITION,
        capabilities=HeatDeliveryCapabilities(can_read_valve_position=True, can_write_valve_position=True),
        commanded_position=100.0,
        reported_position=ObservedValue.valid(63.0, NOW - timedelta(seconds=5)),
    )

    assert observation.commanded_position == 100.0
    assert observation.reported_position.value == 63.0
    assert observation.reported_position.quality is ObservationQuality.VALID


def test_source_dispatch_evidence_does_not_claim_physical_availability() -> None:
    observation = HeatSourceObservation(captured_at=NOW)

    assert observation.last_successful_dispatch_action is None
    assert observation.reported_heat_available.quality is ObservationQuality.UNKNOWN
    assert observation.reported_heat_available.value is None


def test_heating_episode_is_an_immutable_snapshot() -> None:
    source = HeatSourceObservation(captured_at=NOW)
    sample = HeatingEpisodeSample(
        captured_at=NOW,
        zone_temperature=ObservedValue.valid(20.0, NOW),
        target_temperature=22.0,
        actuator_observations=(),
        source_observation=source,
    )
    episode = HeatingEpisode(
        zone_id=ZoneId("living_room"),
        started_at=NOW,
        ended_at=None,
        termination_reason=None,
        initial_target_temperature=22.0,
        current_target_temperature=22.0,
        initial_temperature=20.0,
        current_temperature=20.0,
        demand_transitions=(
            HeatingDemandTransition(
                demand=BuildingHeatDemandStatus.HEAT_REQUIRED,
                changed_at=NOW,
            ),
        ),
        total_sample_count=1,
        samples_truncated=False,
        samples=(sample,),
    )

    with pytest.raises(FrozenInstanceError):
        episode.current_temperature = 21.0  # type: ignore[misc]
