"""Deterministic, descriptive assessment of completed heating episodes."""

from collections import Counter
from datetime import datetime

from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.heat_delivery import (
    HeatDeliveryObservation,
    HeatingEpisode,
    HeatingEpisodeTerminationReason,
    HeatingPerformanceAssessment,
    HeatingPerformanceAssessmentCriteria,
    HeatingPerformanceAssessmentReason,
    HeatingPerformanceAssessmentStatus,
    HeatingPerformanceAssessmentType,
    HeatingPerformanceEvidenceSummary,
    HeatingPerformanceParameter,
    HeatingPerformanceStatus,
    HeatingPerformanceWindowAssessment,
    HeatingPerformanceWindowEvidence,
    ObservationQuality,
    ObservationQualityCount,
    ObservedTemperatureDirection,
    ObservedTemperatureResponse,
    heating_episode_id,
    heating_performance_assessment_id,
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

    def assess_progress(self, episode: HeatingEpisode) -> HeatingPerformanceWindowAssessment:
        """Assess a bounded active window without producing a control output."""

        if not episode.samples:
            raise ValueError("progress assessment requires at least one episode sample")
        assessed_at = episode.samples[-1].captured_at
        episode_identity = heating_episode_id(episode.zone_id, episode.started_at)
        latest_sample = episode.samples[-1]
        latest_source = latest_sample.source_observation
        permission_enabled_at = latest_source.last_successful_dispatch_at
        permission_enabled = latest_source.last_successful_dispatch_action is HeatingAction.ENABLE_HEATING
        window_floor = assessed_at - self.criteria.observation_window
        boundary = max(episode.started_at, window_floor)
        if permission_enabled_at is not None:
            boundary = max(boundary, permission_enabled_at)

        target_changed = False
        previous_target = None
        for sample in episode.samples:
            if sample.captured_at < boundary:
                continue
            if previous_target is not None and abs(sample.target_temperature - previous_target) > (
                self.criteria.target_change_tolerance
            ):
                boundary = sample.captured_at
                target_changed = True
            previous_target = sample.target_temperature
        selected = tuple(sample for sample in episode.samples if boundary <= sample.captured_at <= assessed_at)
        if not selected:
            selected = (latest_sample,)
        window_started_at = selected[0].captured_at

        values_by_timestamp: dict[datetime, float] = {}
        duplicate_count = 0
        conflicting = False
        non_monotonic = False
        previous_timestamp: datetime | None = None
        for sample in selected:
            observed = sample.zone_temperature
            if observed.quality is not ObservationQuality.VALID:
                continue
            if observed.observed_at is None or observed.value is None:
                raise ValueError("valid temperature observation must contain value and timestamp")
            timestamp = observed.observed_at
            value = float(observed.value)
            if previous_timestamp is not None and timestamp < previous_timestamp:
                non_monotonic = True
            if timestamp in values_by_timestamp:
                if values_by_timestamp[timestamp] == value:
                    duplicate_count += 1
                else:
                    conflicting = True
                continue
            values_by_timestamp[timestamp] = value
            previous_timestamp = timestamp

        measurements = tuple(values_by_timestamp.items())
        latest_observed = latest_sample.zone_temperature
        evidence_quality = latest_observed.quality
        reason: HeatingPerformanceAssessmentReason
        status = HeatingPerformanceStatus.INSUFFICIENT_EVIDENCE

        if episode.samples_truncated:
            reason = HeatingPerformanceAssessmentReason.HISTORY_TRUNCATED
            evidence_quality = ObservationQuality.DEGRADED
        elif not permission_enabled or permission_enabled_at is None or permission_enabled_at > assessed_at:
            reason = HeatingPerformanceAssessmentReason.HEATING_PERMISSION_NOT_ENABLED
            evidence_quality = ObservationQuality.UNKNOWN
        elif latest_observed.quality is not ObservationQuality.VALID:
            reason = HeatingPerformanceAssessmentReason.NON_VALID_MEASUREMENTS_EXCLUDED
        elif conflicting:
            reason = HeatingPerformanceAssessmentReason.CONFLICTING_MEASUREMENTS
            evidence_quality = ObservationQuality.CONFLICTING
        elif non_monotonic:
            reason = HeatingPerformanceAssessmentReason.NON_MONOTONIC_TIMESTAMPS
            evidence_quality = ObservationQuality.CONFLICTING
        elif latest_observed.observed_at is None or assessed_at - latest_observed.observed_at > (
            self.criteria.maximum_measurement_age
        ):
            reason = HeatingPerformanceAssessmentReason.MEASUREMENT_NOT_FRESH
            evidence_quality = ObservationQuality.STALE
        elif len(measurements) < self.criteria.minimum_valid_sample_count:
            reason = (
                HeatingPerformanceAssessmentReason.TARGET_CHANGED
                if target_changed
                else HeatingPerformanceAssessmentReason.INSUFFICIENT_DISTINCT_MEASUREMENTS
            )
            evidence_quality = ObservationQuality.UNKNOWN
        elif measurements[-1][0] - measurements[0][0] < self.criteria.minimum_observation_duration:
            reason = (
                HeatingPerformanceAssessmentReason.TARGET_CHANGED
                if target_changed
                else HeatingPerformanceAssessmentReason.MINIMUM_OBSERVATION_DURATION_NOT_MET
            )
            evidence_quality = ObservationQuality.UNKNOWN
        else:
            first_temperature = measurements[0][1]
            latest_temperature = measurements[-1][1]
            delta = latest_temperature - first_temperature
            distance_now = latest_sample.target_temperature - latest_temperature
            if abs(distance_now) <= self.criteria.near_target_tolerance and delta > (
                -self.criteria.meaningful_temperature_change
            ):
                status = HeatingPerformanceStatus.NORMAL
                reason = HeatingPerformanceAssessmentReason.NEAR_TARGET
            elif delta >= self.criteria.meaningful_temperature_change:
                status = HeatingPerformanceStatus.NORMAL
                reason = HeatingPerformanceAssessmentReason.TEMPERATURE_RISING
            elif delta <= -self.criteria.meaningful_temperature_change:
                status = HeatingPerformanceStatus.ANOMALOUS
                reason = HeatingPerformanceAssessmentReason.TEMPERATURE_FALLING
            else:
                status = HeatingPerformanceStatus.DEGRADED
                reason = HeatingPerformanceAssessmentReason.TEMPERATURE_RESPONSE_FLAT
            evidence_quality = ObservationQuality.VALID

        evidence = _progress_evidence(
            window_started_at=window_started_at,
            assessed_at=assessed_at,
            measurements=measurements,
            target_temperature=latest_sample.target_temperature,
            duplicate_count=duplicate_count,
            evidence_quality=evidence_quality,
            history_truncated=episode.samples_truncated,
            source_observation_timestamps=tuple(sorted({sample.source_observation.captured_at for sample in selected})),
        )
        parameters = (
            HeatingPerformanceParameter(
                "permission_enabled_at",
                permission_enabled_at.isoformat() if permission_enabled_at is not None else None,
            ),
            HeatingPerformanceParameter("target_rebased", target_changed),
        )
        return HeatingPerformanceWindowAssessment(
            assessment_id=heating_performance_assessment_id(
                episode_identity,
                HeatingPerformanceAssessmentType.HEATING_PROGRESS,
                assessed_at,
            ),
            assessment_type=HeatingPerformanceAssessmentType.HEATING_PROGRESS,
            status=status,
            assessed_at=assessed_at,
            heating_episode_id=episode_identity,
            zone_id=episode.zone_id,
            source_id=None,
            evidence=evidence,
            reason=reason,
            parameters=parameters,
        )


def _quality_counts(counts: Counter[ObservationQuality]) -> tuple[ObservationQualityCount, ...]:
    return tuple(ObservationQualityCount(quality=quality, count=counts[quality]) for quality in ObservationQuality)


def _progress_evidence(
    *,
    window_started_at: datetime,
    assessed_at: datetime,
    measurements: tuple[tuple[datetime, float], ...],
    target_temperature: float,
    duplicate_count: int,
    evidence_quality: ObservationQuality,
    history_truncated: bool,
    source_observation_timestamps: tuple[datetime, ...],
) -> HeatingPerformanceWindowEvidence:
    first_temperature = measurements[0][1] if measurements else None
    latest_temperature = measurements[-1][1] if measurements else None
    return HeatingPerformanceWindowEvidence(
        observation_window_started_at=window_started_at,
        observation_window_ended_at=assessed_at,
        elapsed_duration=assessed_at - window_started_at,
        starting_temperature=first_temperature,
        latest_temperature=latest_temperature,
        temperature_delta=(
            latest_temperature - first_temperature
            if first_temperature is not None and latest_temperature is not None
            else None
        ),
        target_temperature=target_temperature,
        distance_to_target_at_start=(target_temperature - first_temperature if first_temperature is not None else None),
        distance_to_target_now=(target_temperature - latest_temperature if latest_temperature is not None else None),
        sample_count=len(measurements),
        duplicate_sample_count=duplicate_count,
        evidence_quality=evidence_quality,
        source_observation_timestamps=source_observation_timestamps,
        history_truncated=history_truncated,
    )


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
