from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.services.heating_performance_assessor import HeatingPerformanceAssessor
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.heat_delivery import (
    HeatingDemandTransition,
    HeatingEpisode,
    HeatingEpisodeSample,
    HeatingEpisodeTerminationReason,
    HeatingPerformanceAssessmentCriteria,
    HeatingPerformanceAssessmentReason,
    HeatingPerformanceAssessmentStatus,
    HeatSourceObservation,
    ObservationQuality,
    ObservedTemperatureDirection,
    ObservedValue,
)
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ZONE = ZoneId("living_room")


def sample(
    *,
    captured_at: datetime,
    temperature: ObservedValue[float],
    target_temperature: float = 22.0,
) -> HeatingEpisodeSample:
    return HeatingEpisodeSample(
        captured_at=captured_at,
        zone_temperature=temperature,
        target_temperature=target_temperature,
        actuator_observations=(),
        source_observation=HeatSourceObservation(captured_at=captured_at),
    )


def completed_episode(
    *samples: HeatingEpisodeSample,
    termination_reason: HeatingEpisodeTerminationReason = HeatingEpisodeTerminationReason.DEMAND_CLEARED,
    total_sample_count: int | None = None,
    samples_truncated: bool = False,
) -> HeatingEpisode:
    ended_at = samples[-1].captured_at
    final_demand = (
        BuildingHeatDemandStatus.NO_HEAT_REQUIRED
        if termination_reason is HeatingEpisodeTerminationReason.DEMAND_CLEARED
        else BuildingHeatDemandStatus.INDETERMINATE
    )
    return HeatingEpisode(
        zone_id=ZONE,
        started_at=NOW,
        ended_at=ended_at,
        termination_reason=termination_reason,
        initial_target_temperature=samples[0].target_temperature,
        current_target_temperature=samples[-1].target_temperature,
        initial_temperature=(
            float(samples[0].zone_temperature.value) if samples[0].zone_temperature.value is not None else None
        ),
        current_temperature=(
            float(samples[-1].zone_temperature.value) if samples[-1].zone_temperature.value is not None else None
        ),
        demand_transitions=(
            HeatingDemandTransition(demand=BuildingHeatDemandStatus.HEAT_REQUIRED, changed_at=NOW),
            HeatingDemandTransition(demand=final_demand, changed_at=ended_at),
        ),
        total_sample_count=total_sample_count if total_sample_count is not None else len(samples),
        samples_truncated=samples_truncated,
        samples=tuple(samples),
    )


def test_assessment_is_immutable_and_deterministic() -> None:
    episode = completed_episode(
        sample(captured_at=NOW, temperature=ObservedValue.valid(20.0, NOW)),
        sample(
            captured_at=NOW + timedelta(hours=1),
            temperature=ObservedValue.valid(21.0, NOW + timedelta(hours=1)),
        ),
    )
    assessor = HeatingPerformanceAssessor()

    first = assessor.assess(episode)
    second = assessor.assess(episode)

    assert first == second
    assert first.assessed_at == episode.ended_at
    assert first.status is HeatingPerformanceAssessmentStatus.ASSESSED
    assert first.temperature_response is not None
    assert first.temperature_response.temperature_change == 1.0
    assert first.temperature_response.temperature_change_per_hour == 1.0
    assert first.temperature_response.direction is ObservedTemperatureDirection.INCREASED
    with pytest.raises(FrozenInstanceError):
        first.status = HeatingPerformanceAssessmentStatus.INTERRUPTED  # type: ignore[misc]


def test_non_valid_measurements_are_explained_as_insufficient_evidence() -> None:
    episode = completed_episode(
        sample(captured_at=NOW, temperature=ObservedValue.unknown("measurement missing")),
        sample(
            captured_at=NOW + timedelta(hours=1),
            temperature=ObservedValue(
                value=20.0,
                observed_at=NOW - timedelta(hours=1),
                quality=ObservationQuality.STALE,
                reason="measurement expired",
            ),
        ),
    )

    assessment = HeatingPerformanceAssessor().assess(episode)

    assert assessment.status is HeatingPerformanceAssessmentStatus.INSUFFICIENT_EVIDENCE
    assert assessment.temperature_response is None
    assert assessment.evidence.distinct_valid_measurement_count == 0
    assert HeatingPerformanceAssessmentReason.NON_VALID_MEASUREMENTS_EXCLUDED in assessment.reasons


def test_duplicate_measurement_is_removed_without_weighting_the_response() -> None:
    episode = completed_episode(
        sample(captured_at=NOW, temperature=ObservedValue.valid(20.0, NOW)),
        sample(
            captured_at=NOW + timedelta(minutes=30),
            temperature=ObservedValue.valid(20.0, NOW),
        ),
        sample(
            captured_at=NOW + timedelta(hours=1),
            temperature=ObservedValue.valid(21.0, NOW + timedelta(hours=1)),
        ),
    )

    assessment = HeatingPerformanceAssessor().assess(episode)

    assert assessment.status is HeatingPerformanceAssessmentStatus.ASSESSED
    assert assessment.evidence.distinct_valid_measurement_count == 2
    assert assessment.evidence.duplicate_valid_measurement_count == 1
    assert HeatingPerformanceAssessmentReason.DUPLICATE_MEASUREMENTS_REMOVED in assessment.reasons


def test_conflicting_values_at_one_timestamp_are_not_assessed() -> None:
    episode = completed_episode(
        sample(captured_at=NOW, temperature=ObservedValue.valid(20.0, NOW)),
        sample(
            captured_at=NOW + timedelta(minutes=1),
            temperature=ObservedValue.valid(21.0, NOW),
        ),
    )

    assessment = HeatingPerformanceAssessor().assess(episode)

    assert assessment.status is HeatingPerformanceAssessmentStatus.CONFLICTING_EVIDENCE
    assert assessment.temperature_response is None
    assert HeatingPerformanceAssessmentReason.CONFLICTING_MEASUREMENTS in assessment.reasons


def test_non_monotonic_measurement_timestamps_are_explained_as_conflicting() -> None:
    episode = completed_episode(
        sample(
            captured_at=NOW,
            temperature=ObservedValue.valid(20.0, NOW + timedelta(minutes=10)),
        ),
        sample(
            captured_at=NOW + timedelta(minutes=10),
            temperature=ObservedValue.valid(20.5, NOW + timedelta(minutes=5)),
        ),
    )

    assessment = HeatingPerformanceAssessor().assess(episode)

    assert assessment.status is HeatingPerformanceAssessmentStatus.CONFLICTING_EVIDENCE
    assert HeatingPerformanceAssessmentReason.NON_MONOTONIC_TIMESTAMPS in assessment.reasons


def test_target_change_is_reported_without_changing_observed_response() -> None:
    episode = completed_episode(
        sample(captured_at=NOW, temperature=ObservedValue.valid(20.0, NOW), target_temperature=22.0),
        sample(
            captured_at=NOW + timedelta(hours=1),
            temperature=ObservedValue.valid(21.0, NOW + timedelta(hours=1)),
            target_temperature=23.0,
        ),
    )

    assessment = HeatingPerformanceAssessor().assess(episode)

    assert assessment.status is HeatingPerformanceAssessmentStatus.ASSESSED
    assert assessment.evidence.target_changed is True
    assert HeatingPerformanceAssessmentReason.TARGET_CHANGED in assessment.reasons
    assert assessment.temperature_response is not None
    assert assessment.temperature_response.temperature_change == 1.0


@pytest.mark.parametrize(
    ("temperature_change", "expected_direction"),
    [
        (0.124, ObservedTemperatureDirection.UNCHANGED),
        (0.125, ObservedTemperatureDirection.UNCHANGED),
        (0.126, ObservedTemperatureDirection.INCREASED),
        (-0.124, ObservedTemperatureDirection.UNCHANGED),
        (-0.125, ObservedTemperatureDirection.UNCHANGED),
        (-0.126, ObservedTemperatureDirection.DECREASED),
    ],
)
def test_temperature_direction_uses_explicit_tolerance_boundaries(
    temperature_change: float,
    expected_direction: ObservedTemperatureDirection,
) -> None:
    episode = completed_episode(
        sample(captured_at=NOW, temperature=ObservedValue.valid(20.0, NOW)),
        sample(
            captured_at=NOW + timedelta(hours=1),
            temperature=ObservedValue.valid(20.0 + temperature_change, NOW + timedelta(hours=1)),
        ),
    )
    assessor = HeatingPerformanceAssessor(
        HeatingPerformanceAssessmentCriteria(
            stable_temperature_tolerance=0.125,
            target_change_tolerance=0.125,
        )
    )

    assessment = assessor.assess(episode)

    assert assessment.temperature_response is not None
    assert assessment.temperature_response.direction is expected_direction


@pytest.mark.parametrize(
    ("target_change", "expected_changed"),
    [(0.124, False), (0.125, False), (0.126, True)],
)
def test_target_change_uses_explicit_tolerance_boundaries(
    target_change: float,
    expected_changed: bool,
) -> None:
    episode = completed_episode(
        sample(
            captured_at=NOW,
            temperature=ObservedValue.valid(20.0, NOW),
            target_temperature=22.0,
        ),
        sample(
            captured_at=NOW + timedelta(hours=1),
            temperature=ObservedValue.valid(21.0, NOW + timedelta(hours=1)),
            target_temperature=22.0 + target_change,
        ),
    )
    assessor = HeatingPerformanceAssessor(
        HeatingPerformanceAssessmentCriteria(
            stable_temperature_tolerance=0.125,
            target_change_tolerance=0.125,
        )
    )

    assessment = assessor.assess(episode)

    assert assessment.evidence.target_changed is expected_changed
    assert (HeatingPerformanceAssessmentReason.TARGET_CHANGED in assessment.reasons) is expected_changed


def test_truncated_history_is_never_presented_as_complete_evidence() -> None:
    episode = completed_episode(
        sample(captured_at=NOW, temperature=ObservedValue.valid(20.0, NOW)),
        sample(
            captured_at=NOW + timedelta(hours=1),
            temperature=ObservedValue.valid(21.0, NOW + timedelta(hours=1)),
        ),
        total_sample_count=4,
        samples_truncated=True,
    )

    assessment = HeatingPerformanceAssessor().assess(episode)

    assert assessment.evidence.total_sample_count == 4
    assert assessment.evidence.retained_sample_count == 2
    assert assessment.evidence.samples_truncated is True
    assert HeatingPerformanceAssessmentReason.HISTORY_TRUNCATED in assessment.reasons


def test_interrupted_episode_reports_response_without_becoming_a_decision() -> None:
    episode = completed_episode(
        sample(captured_at=NOW, temperature=ObservedValue.valid(20.0, NOW)),
        sample(
            captured_at=NOW + timedelta(hours=1),
            temperature=ObservedValue.valid(20.5, NOW + timedelta(hours=1)),
        ),
        termination_reason=HeatingEpisodeTerminationReason.RUNTIME_STOPPED,
    )

    assessment = HeatingPerformanceAssessor().assess(episode)

    assert assessment.status is HeatingPerformanceAssessmentStatus.INTERRUPTED
    assert assessment.temperature_response is not None
    assert HeatingPerformanceAssessmentReason.RUNTIME_STOPPED in assessment.reasons
    assert HeatingPerformanceAssessmentReason.PHYSICAL_SOURCE_STATE_UNKNOWN in assessment.reasons
