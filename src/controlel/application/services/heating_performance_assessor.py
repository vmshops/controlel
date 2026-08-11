"""Deterministic, descriptive assessment of completed heating episodes."""

from collections import Counter
from datetime import datetime

from controlel.domain.heat_delivery import (
    HeatDeliveryObservation,
    HeatingEpisode,
    HeatingEpisodeTerminationReason,
    HeatingPerformanceAssessment,
    HeatingPerformanceAssessmentCriteria,
    HeatingPerformanceAssessmentReason,
    HeatingPerformanceAssessmentStatus,
    HeatingPerformanceEvidenceSummary,
    ObservationQuality,
    ObservationQualityCount,
    ObservedTemperatureDirection,
    ObservedTemperatureResponse,
)


class HeatingPerformanceAssessor:
    """Explain observed temperature response without making a decision."""

    def __init__(self, criteria: HeatingPerformanceAssessmentCriteria | None = None) -> None:
        self.criteria = criteria or HeatingPerformanceAssessmentCriteria()

    def assess(self, episode: HeatingEpisode) -> HeatingPerformanceAssessment:
        if episode.ended_at is None or episode.termination_reason is None:
            raise ValueError("only a completed heating episode can be assessed")

        temperature_quality_counts = Counter(sample.zone_temperature.quality for sample in episode.samples)
        source_quality_counts = Counter(
            sample.source_observation.reported_heat_available.quality for sample in episode.samples
        )
        valid_measurements: list[tuple[datetime, float]] = []
        values_by_timestamp: dict[datetime, float] = {}
        duplicate_count = 0
        conflicting = False
        non_monotonic = False
        previous_timestamp = None
        for sample in episode.samples:
            observation = sample.zone_temperature
            if observation.quality is not ObservationQuality.VALID:
                continue
            timestamp = observation.observed_at
            value = observation.value
            if timestamp is None or value is None:
                raise ValueError("valid temperature observation must contain value and timestamp")
            numeric_value = float(value)
            if timestamp in values_by_timestamp:
                if values_by_timestamp[timestamp] == numeric_value:
                    duplicate_count += 1
                else:
                    conflicting = True
                continue
            if previous_timestamp is not None and timestamp < previous_timestamp:
                non_monotonic = True
            values_by_timestamp[timestamp] = numeric_value
            valid_measurements.append((timestamp, numeric_value))
            previous_timestamp = timestamp

        reasons: list[HeatingPerformanceAssessmentReason] = []
        if duplicate_count:
            reasons.append(HeatingPerformanceAssessmentReason.DUPLICATE_MEASUREMENTS_REMOVED)
        if any(quality is not ObservationQuality.VALID for quality in temperature_quality_counts):
            reasons.append(HeatingPerformanceAssessmentReason.NON_VALID_MEASUREMENTS_EXCLUDED)
        target_values = tuple(sample.target_temperature for sample in episode.samples)
        target_changed = bool(target_values) and (
            max(target_values) - min(target_values) > self.criteria.target_change_tolerance
        )
        if target_changed:
            reasons.append(HeatingPerformanceAssessmentReason.TARGET_CHANGED)
        if episode.samples_truncated:
            reasons.append(HeatingPerformanceAssessmentReason.HISTORY_TRUNCATED)
        if all(sample.source_observation.reported_heat_available.value is None for sample in episode.samples):
            reasons.append(HeatingPerformanceAssessmentReason.PHYSICAL_SOURCE_STATE_UNKNOWN)

        response = None
        if conflicting or non_monotonic:
            status = HeatingPerformanceAssessmentStatus.CONFLICTING_EVIDENCE
            if conflicting:
                reasons.append(HeatingPerformanceAssessmentReason.CONFLICTING_MEASUREMENTS)
            if non_monotonic:
                reasons.append(HeatingPerformanceAssessmentReason.NON_MONOTONIC_TIMESTAMPS)
        elif len(valid_measurements) < 2:
            status = HeatingPerformanceAssessmentStatus.INSUFFICIENT_EVIDENCE
            reasons.append(HeatingPerformanceAssessmentReason.INSUFFICIENT_DISTINCT_MEASUREMENTS)
        else:
            first_timestamp, first_temperature = valid_measurements[0]
            last_timestamp, last_temperature = valid_measurements[-1]
            duration = last_timestamp - first_timestamp
            temperature_change = last_temperature - first_temperature
            if temperature_change > self.criteria.stable_temperature_tolerance:
                direction = ObservedTemperatureDirection.INCREASED
            elif temperature_change < -self.criteria.stable_temperature_tolerance:
                direction = ObservedTemperatureDirection.DECREASED
            else:
                direction = ObservedTemperatureDirection.UNCHANGED
            response = ObservedTemperatureResponse(
                first_temperature=first_temperature,
                first_observed_at=first_timestamp,
                last_temperature=last_temperature,
                last_observed_at=last_timestamp,
                temperature_change=temperature_change,
                observation_duration=duration,
                temperature_change_per_hour=(temperature_change * 3600 / duration.total_seconds()),
                direction=direction,
            )
            reasons.append(HeatingPerformanceAssessmentReason.OBSERVED_TEMPERATURE_RESPONSE)
            status = (
                HeatingPerformanceAssessmentStatus.ASSESSED
                if episode.termination_reason is HeatingEpisodeTerminationReason.DEMAND_CLEARED
                else HeatingPerformanceAssessmentStatus.INTERRUPTED
            )

        interruption_reason = _interruption_reason(episode.termination_reason)
        if interruption_reason is not None:
            reasons.append(interruption_reason)

        return HeatingPerformanceAssessment(
            zone_id=episode.zone_id,
            episode_started_at=episode.started_at,
            episode_ended_at=episode.ended_at,
            assessed_at=episode.ended_at,
            status=status,
            criteria=self.criteria,
            temperature_response=response,
            evidence=HeatingPerformanceEvidenceSummary(
                total_sample_count=episode.total_sample_count,
                retained_sample_count=episode.retained_sample_count,
                samples_truncated=episode.samples_truncated,
                distinct_valid_measurement_count=len(valid_measurements),
                duplicate_valid_measurement_count=duplicate_count,
                zone_temperature_quality_counts=_quality_counts(temperature_quality_counts),
                target_changed=target_changed,
                actuator_command_evidence_count=sum(
                    _has_actuator_command_evidence(observation)
                    for sample in episode.samples
                    for observation in sample.actuator_observations
                ),
                actuator_reported_value_count=sum(
                    _actuator_reported_value_count(observation)
                    for sample in episode.samples
                    for observation in sample.actuator_observations
                ),
                source_permission_evidence_count=sum(
                    sample.source_observation.last_requested_action is not None
                    or sample.source_observation.last_successful_dispatch_action is not None
                    for sample in episode.samples
                ),
                source_availability_quality_counts=_quality_counts(source_quality_counts),
            ),
            reasons=tuple(reasons),
            termination_reason=episode.termination_reason,
        )


def _quality_counts(counts: Counter[ObservationQuality]) -> tuple[ObservationQualityCount, ...]:
    return tuple(ObservationQualityCount(quality=quality, count=counts[quality]) for quality in ObservationQuality)


def _has_actuator_command_evidence(observation: HeatDeliveryObservation) -> bool:
    return any(
        value is not None
        for value in (
            observation.commanded_target_temperature,
            observation.commanded_position,
            observation.commanded_binary_open,
            observation.commanded_remote_temperature,
            observation.last_requested_command,
            observation.last_successful_command,
        )
    )


def _actuator_reported_value_count(observation: HeatDeliveryObservation) -> int:
    return sum(
        reported.value is not None
        for reported in (
            observation.reported_target_temperature,
            observation.reported_local_temperature,
            observation.reported_position,
            observation.reported_binary_open,
            observation.reported_activity,
        )
    )


def _interruption_reason(
    termination_reason: HeatingEpisodeTerminationReason,
) -> HeatingPerformanceAssessmentReason | None:
    return {
        HeatingEpisodeTerminationReason.DEMAND_CLEARED: None,
        HeatingEpisodeTerminationReason.DEMAND_INDETERMINATE: (
            HeatingPerformanceAssessmentReason.DEMAND_BECAME_INDETERMINATE
        ),
        HeatingEpisodeTerminationReason.RUNTIME_STOPPED: HeatingPerformanceAssessmentReason.RUNTIME_STOPPED,
        HeatingEpisodeTerminationReason.FATAL_SHUTDOWN: HeatingPerformanceAssessmentReason.FATAL_SHUTDOWN,
    }[termination_reason]
