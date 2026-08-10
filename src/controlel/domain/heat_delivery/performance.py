"""Immutable, descriptive heating-performance assessment contracts."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite

from controlel.domain.value_objects.zone_id import ZoneId

from .observation import HeatingEpisodeTerminationReason, ObservationQuality

DEFAULT_STABLE_TEMPERATURE_TOLERANCE = 0.1
DEFAULT_TARGET_CHANGE_TOLERANCE = 0.1


class HeatingPerformanceAssessmentStatus(StrEnum):
    ASSESSED = "assessed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    INTERRUPTED = "interrupted"


class ObservedTemperatureDirection(StrEnum):
    INCREASED = "increased"
    UNCHANGED = "unchanged"
    DECREASED = "decreased"
    UNKNOWN = "unknown"


class HeatingPerformanceAssessmentReason(StrEnum):
    OBSERVED_TEMPERATURE_RESPONSE = "observed_temperature_response"
    INSUFFICIENT_DISTINCT_MEASUREMENTS = "insufficient_distinct_measurements"
    DUPLICATE_MEASUREMENTS_REMOVED = "duplicate_measurements_removed"
    NON_VALID_MEASUREMENTS_EXCLUDED = "non_valid_measurements_excluded"
    NON_MONOTONIC_TIMESTAMPS = "non_monotonic_timestamps"
    CONFLICTING_MEASUREMENTS = "conflicting_measurements"
    TARGET_CHANGED = "target_changed"
    HISTORY_TRUNCATED = "history_truncated"
    DEMAND_BECAME_INDETERMINATE = "demand_became_indeterminate"
    RUNTIME_STOPPED = "runtime_stopped"
    FATAL_SHUTDOWN = "fatal_shutdown"
    PHYSICAL_SOURCE_STATE_UNKNOWN = "physical_source_state_unknown"


@dataclass(frozen=True)
class ObservationQualityCount:
    quality: ObservationQuality
    count: int

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError("observation quality count cannot be negative")


@dataclass(frozen=True)
class HeatingPerformanceAssessmentCriteria:
    """Explicit deterministic tolerances; never inferred from observations."""

    stable_temperature_tolerance: float = DEFAULT_STABLE_TEMPERATURE_TOLERANCE
    target_change_tolerance: float = DEFAULT_TARGET_CHANGE_TOLERANCE

    def __post_init__(self) -> None:
        for value, label in (
            (self.stable_temperature_tolerance, "stable_temperature_tolerance"),
            (self.target_change_tolerance, "target_change_tolerance"),
        ):
            if isinstance(value, bool) or not isfinite(value) or value < 0:
                raise ValueError(f"{label} must be a finite non-negative number")


@dataclass(frozen=True)
class ObservedTemperatureResponse:
    first_temperature: float
    first_observed_at: datetime
    last_temperature: float
    last_observed_at: datetime
    temperature_change: float
    observation_duration: timedelta
    temperature_change_per_hour: float
    direction: ObservedTemperatureDirection

    def __post_init__(self) -> None:
        _aware(self.first_observed_at, "first_observed_at")
        _aware(self.last_observed_at, "last_observed_at")
        if self.last_observed_at <= self.first_observed_at:
            raise ValueError("temperature response requires increasing timestamps")
        for value, label in (
            (self.first_temperature, "first_temperature"),
            (self.last_temperature, "last_temperature"),
            (self.temperature_change, "temperature_change"),
            (self.temperature_change_per_hour, "temperature_change_per_hour"),
        ):
            if not isfinite(value):
                raise ValueError(f"{label} must be finite")
        if self.observation_duration <= timedelta(0):
            raise ValueError("observation_duration must be positive")


@dataclass(frozen=True)
class HeatingPerformanceEvidenceSummary:
    total_sample_count: int
    retained_sample_count: int
    samples_truncated: bool
    distinct_valid_measurement_count: int
    duplicate_valid_measurement_count: int
    zone_temperature_quality_counts: tuple[ObservationQualityCount, ...]
    target_changed: bool
    actuator_command_evidence_count: int
    actuator_reported_value_count: int
    source_permission_evidence_count: int
    source_availability_quality_counts: tuple[ObservationQualityCount, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.total_sample_count, "total_sample_count"),
            (self.retained_sample_count, "retained_sample_count"),
            (self.distinct_valid_measurement_count, "distinct_valid_measurement_count"),
            (self.duplicate_valid_measurement_count, "duplicate_valid_measurement_count"),
            (self.actuator_command_evidence_count, "actuator_command_evidence_count"),
            (self.actuator_reported_value_count, "actuator_reported_value_count"),
            (self.source_permission_evidence_count, "source_permission_evidence_count"),
        ):
            if value < 0:
                raise ValueError(f"{label} cannot be negative")
        if self.retained_sample_count > self.total_sample_count:
            raise ValueError("retained_sample_count cannot exceed total_sample_count")
        if self.samples_truncated is not (self.total_sample_count > self.retained_sample_count):
            raise ValueError("samples_truncated must describe incomplete retained history")


@dataclass(frozen=True)
class HeatingPerformanceAssessment:
    zone_id: ZoneId
    episode_started_at: datetime
    episode_ended_at: datetime
    assessed_at: datetime
    status: HeatingPerformanceAssessmentStatus
    temperature_response: ObservedTemperatureResponse | None
    evidence: HeatingPerformanceEvidenceSummary
    reasons: tuple[HeatingPerformanceAssessmentReason, ...]
    termination_reason: HeatingEpisodeTerminationReason

    def __post_init__(self) -> None:
        _aware(self.episode_started_at, "episode_started_at")
        _aware(self.episode_ended_at, "episode_ended_at")
        _aware(self.assessed_at, "assessed_at")
        if self.episode_ended_at < self.episode_started_at:
            raise ValueError("assessment episode cannot end before it starts")
        if self.assessed_at != self.episode_ended_at:
            raise ValueError("assessed_at must be derived from the episode end")
        if not self.reasons:
            raise ValueError("assessment requires at least one explainable reason")
        has_response = self.temperature_response is not None
        if (
            self.status
            in {
                HeatingPerformanceAssessmentStatus.ASSESSED,
                HeatingPerformanceAssessmentStatus.INTERRUPTED,
            }
            and not has_response
        ):
            raise ValueError(f"{self.status.value} assessment requires a temperature response")
        if (
            self.status
            in {
                HeatingPerformanceAssessmentStatus.INSUFFICIENT_EVIDENCE,
                HeatingPerformanceAssessmentStatus.CONFLICTING_EVIDENCE,
            }
            and has_response
        ):
            raise ValueError(f"{self.status.value} assessment cannot contain a temperature response")


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
