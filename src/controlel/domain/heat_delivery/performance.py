"""Immutable, descriptive heating-performance assessment contracts."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite

from controlel.domain.value_objects.zone_id import ZoneId

from .anomaly import HeatingAnomalyObservation
from .observation import HeatingEpisodeTerminationReason, ObservationQuality

DEFAULT_STABLE_TEMPERATURE_TOLERANCE = 0.1
DEFAULT_TARGET_CHANGE_TOLERANCE = 0.1
DEFAULT_MINIMUM_OBSERVATION_DURATION = timedelta(minutes=30)
DEFAULT_MINIMUM_VALID_SAMPLE_COUNT = 3
DEFAULT_OBSERVATION_WINDOW = timedelta(hours=1)
DEFAULT_MEANINGFUL_TEMPERATURE_CHANGE = 0.2
DEFAULT_NEAR_TARGET_TOLERANCE = 0.2
DEFAULT_MAXIMUM_MEASUREMENT_AGE = timedelta(minutes=10)
DEFAULT_RECOVERY_CONFIRMATION_COUNT = 2
MAX_HEATING_PERFORMANCE_PARAMETERS = 16
MAX_HEATING_PERFORMANCE_WINDOW = timedelta(hours=24)

type HeatingPerformanceScalar = str | int | float | bool | None


class HeatingPerformanceAssessmentStatus(StrEnum):
    ASSESSED = "assessed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    INTERRUPTED = "interrupted"


class HeatingPerformanceAssessmentType(StrEnum):
    """Small stable taxonomy for passive heating-performance interpretation."""

    HEATING_PROGRESS = "heating_progress"
    TEMPERATURE_TREND = "temperature_trend"
    TARGET_APPROACH = "target_approach"


class HeatingPerformanceStatus(StrEnum):
    """Explicit live-window result; it is never a control decision."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NORMAL = "normal"
    DEGRADED = "degraded"
    ANOMALOUS = "anomalous"
    RECOVERED = "recovered"


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
    MINIMUM_OBSERVATION_DURATION_NOT_MET = "minimum_observation_duration_not_met"
    MEASUREMENT_NOT_FRESH = "measurement_not_fresh"
    HEATING_PERMISSION_NOT_ENABLED = "heating_permission_not_enabled"
    TEMPERATURE_RISING = "temperature_rising"
    TEMPERATURE_RESPONSE_FLAT = "temperature_response_flat"
    TEMPERATURE_FALLING = "temperature_falling"
    NEAR_TARGET = "near_target"
    RECOVERY_CONFIRMATION_PENDING = "recovery_confirmation_pending"
    PERFORMANCE_RECOVERED = "performance_recovered"


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
    minimum_observation_duration: timedelta = DEFAULT_MINIMUM_OBSERVATION_DURATION
    minimum_valid_sample_count: int = DEFAULT_MINIMUM_VALID_SAMPLE_COUNT
    observation_window: timedelta = DEFAULT_OBSERVATION_WINDOW
    meaningful_temperature_change: float = DEFAULT_MEANINGFUL_TEMPERATURE_CHANGE
    near_target_tolerance: float = DEFAULT_NEAR_TARGET_TOLERANCE
    maximum_measurement_age: timedelta = DEFAULT_MAXIMUM_MEASUREMENT_AGE
    recovery_confirmation_count: int = DEFAULT_RECOVERY_CONFIRMATION_COUNT

    def __post_init__(self) -> None:
        for value, label in (
            (self.stable_temperature_tolerance, "stable_temperature_tolerance"),
            (self.target_change_tolerance, "target_change_tolerance"),
        ):
            if isinstance(value, bool) or not isfinite(value) or value < 0:
                raise ValueError(f"{label} must be a finite non-negative number")
        for value, label in (
            (self.meaningful_temperature_change, "meaningful_temperature_change"),
            (self.near_target_tolerance, "near_target_tolerance"),
        ):
            if isinstance(value, bool) or not isfinite(value) or not 0 < value <= 5:
                raise ValueError(f"{label} must be a finite number between 0 and 5")
        if not 2 <= self.minimum_valid_sample_count <= 100:
            raise ValueError("minimum_valid_sample_count must be between 2 and 100")
        for value, label in (
            (self.minimum_observation_duration, "minimum_observation_duration"),
            (self.observation_window, "observation_window"),
            (self.maximum_measurement_age, "maximum_measurement_age"),
        ):
            if not isinstance(value, timedelta) or not timedelta(0) < value <= MAX_HEATING_PERFORMANCE_WINDOW:
                raise ValueError(f"{label} must be positive and no greater than 24 hours")
        if self.observation_window < self.minimum_observation_duration:
            raise ValueError("observation_window cannot be shorter than minimum_observation_duration")
        if not 2 <= self.recovery_confirmation_count <= 10:
            raise ValueError("recovery_confirmation_count must be between 2 and 10")


@dataclass(frozen=True, slots=True)
class HeatingPerformanceParameter:
    """One bounded JSON-safe scalar attached to an assessment."""

    key: str
    value: HeatingPerformanceScalar

    def __post_init__(self) -> None:
        if not self.key or not self.key.isascii() or not self.key.replace("_", "").isalnum():
            raise ValueError("parameter key must be a non-empty ASCII identifier")
        if isinstance(self.value, float) and not isfinite(self.value):
            raise ValueError("parameter float values must be finite")
        if not isinstance(self.value, str | int | float | bool | type(None)):
            raise TypeError("parameter value must be a JSON-safe scalar")


@dataclass(frozen=True, slots=True)
class HeatingPerformanceWindowEvidence:
    """Truthful bounded evidence for one live episode assessment window."""

    observation_window_started_at: datetime
    observation_window_ended_at: datetime
    elapsed_duration: timedelta
    starting_temperature: float | None
    latest_temperature: float | None
    temperature_delta: float | None
    target_temperature: float
    distance_to_target_at_start: float | None
    distance_to_target_now: float | None
    sample_count: int
    duplicate_sample_count: int
    evidence_quality: ObservationQuality
    source_observation_timestamps: tuple[datetime, ...]
    history_truncated: bool = False

    def __post_init__(self) -> None:
        _aware(self.observation_window_started_at, "observation_window_started_at")
        _aware(self.observation_window_ended_at, "observation_window_ended_at")
        if self.observation_window_ended_at < self.observation_window_started_at:
            raise ValueError("observation window cannot end before it starts")
        if self.elapsed_duration != self.observation_window_ended_at - self.observation_window_started_at:
            raise ValueError("elapsed_duration must match the observation window")
        if self.sample_count < 0 or self.duplicate_sample_count < 0:
            raise ValueError("sample counts cannot be negative")
        for value, label in (
            (self.starting_temperature, "starting_temperature"),
            (self.latest_temperature, "latest_temperature"),
            (self.temperature_delta, "temperature_delta"),
            (self.target_temperature, "target_temperature"),
            (self.distance_to_target_at_start, "distance_to_target_at_start"),
            (self.distance_to_target_now, "distance_to_target_now"),
        ):
            if value is not None and not isfinite(value):
                raise ValueError(f"{label} must be finite when present")
        if self.source_observation_timestamps != tuple(sorted(set(self.source_observation_timestamps))):
            raise ValueError("source observation timestamps must be unique and sorted")
        for timestamp in self.source_observation_timestamps:
            _aware(timestamp, "source_observation_timestamp")


@dataclass(frozen=True, slots=True)
class HeatingPerformanceWindowAssessment:
    """Canonical passive interpretation of response while heat permission was enabled."""

    assessment_id: str
    assessment_type: HeatingPerformanceAssessmentType
    status: HeatingPerformanceStatus
    assessed_at: datetime
    heating_episode_id: str
    zone_id: ZoneId
    source_id: str | None
    evidence: HeatingPerformanceWindowEvidence
    reason: HeatingPerformanceAssessmentReason
    parameters: tuple[HeatingPerformanceParameter, ...] = ()

    def __post_init__(self) -> None:
        if not self.assessment_id or not self.heating_episode_id:
            raise ValueError("assessment and episode IDs must not be empty")
        _aware(self.assessed_at, "assessed_at")
        if self.assessed_at != self.evidence.observation_window_ended_at:
            raise ValueError("assessed_at must equal the observation window end")
        keys = tuple(parameter.key for parameter in self.parameters)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("parameters must have unique keys in deterministic sorted order")
        if len(self.parameters) > MAX_HEATING_PERFORMANCE_PARAMETERS:
            raise ValueError(f"parameters must contain at most {MAX_HEATING_PERFORMANCE_PARAMETERS} items")


@dataclass(frozen=True, slots=True)
class ZoneHeatingPerformanceState:
    """Latest immutable assessment and deterministic recovery progress for one zone."""

    zone_id: ZoneId
    heating_episode_id: str
    active_heating_episode_id: str | None
    current: HeatingPerformanceWindowAssessment
    recovery_confirmation_count: int

    def __post_init__(self) -> None:
        if self.current.zone_id != self.zone_id or self.current.heating_episode_id != self.heating_episode_id:
            raise ValueError("zone performance state must match its current assessment")
        if self.active_heating_episode_id not in {None, self.heating_episode_id}:
            raise ValueError("active episode identity must match the current assessment")
        if self.recovery_confirmation_count < 0:
            raise ValueError("recovery confirmation count cannot be negative")


@dataclass(frozen=True, slots=True)
class HeatingPerformanceAssessmentErrorEvidence:
    zone_id: ZoneId
    heating_episode_id: str
    evidence_at: datetime
    exception_type: str

    def __post_init__(self) -> None:
        if not self.heating_episode_id or not self.exception_type:
            raise ValueError("assessment error evidence requires episode identity and exception type")
        _aware(self.evidence_at, "evidence_at")


@dataclass(frozen=True, slots=True)
class HeatingPerformanceSnapshot:
    """Bounded immutable read model for future adapter diagnostics."""

    schema_version: int
    assessment_capacity: int
    total_assessments_emitted: int
    dropped_assessment_count: int
    pending_zone_capacity: int
    pending_observation_count: int
    pending_observations_dropped: int
    zones: tuple[ZoneHeatingPerformanceState, ...]
    assessments: tuple[HeatingPerformanceWindowAssessment, ...]
    errors: tuple[HeatingPerformanceAssessmentErrorEvidence, ...]
    total_anomaly_transitions_emitted: int = 0
    dropped_anomaly_transition_count: int = 0
    active_anomalies: tuple[HeatingAnomalyObservation, ...] = ()
    anomaly_transitions: tuple[HeatingAnomalyObservation, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("heating performance snapshot schema_version must be 1")
        if self.assessment_capacity <= 0 or len(self.assessments) > self.assessment_capacity:
            raise ValueError("assessment history must fit its positive capacity")
        if self.pending_zone_capacity <= 0 or not 0 <= self.pending_observation_count <= self.pending_zone_capacity:
            raise ValueError("pending observation count must fit its positive capacity")
        if (
            min(
                self.total_assessments_emitted,
                self.dropped_assessment_count,
                self.pending_observations_dropped,
                self.total_anomaly_transitions_emitted,
                self.dropped_anomaly_transition_count,
            )
            < 0
        ):
            raise ValueError("snapshot counters cannot be negative")
        zone_ids = tuple(zone.zone_id for zone in self.zones)
        error_zone_ids = tuple(error.zone_id for error in self.errors)
        if zone_ids != tuple(sorted(set(zone_ids), key=lambda item: item.value)):
            raise ValueError("zone states must be unique and sorted")
        if error_zone_ids != tuple(sorted(set(error_zone_ids), key=lambda item: item.value)):
            raise ValueError("assessment errors must be unique and sorted")
        if len(self.anomaly_transitions) > self.assessment_capacity:
            raise ValueError("anomaly transition history must fit assessment_capacity")
        if self.dropped_anomaly_transition_count != (
            self.total_anomaly_transitions_emitted - len(self.anomaly_transitions)
        ):
            raise ValueError("dropped anomaly transition count must match bounded history")
        active_ids = tuple(item.anomaly_id for item in self.active_anomalies)
        if active_ids != tuple(sorted(set(active_ids))):
            raise ValueError("active anomalies must be unique and sorted")
        if any(not item.is_active for item in self.active_anomalies):
            raise ValueError("active_anomalies cannot contain cleared observations")


def heating_episode_id(zone_id: ZoneId, started_at: datetime) -> str:
    """Return the stable identity of one observed heating episode."""

    _aware(started_at, "started_at")
    return f"heating_episode:{zone_id.value}:{started_at.isoformat()}"


def heating_performance_assessment_id(
    episode_id: str,
    assessment_type: HeatingPerformanceAssessmentType,
    assessed_at: datetime,
) -> str:
    """Return a deterministic identity for one assessment revision."""

    if not episode_id:
        raise ValueError("episode_id must not be empty")
    _aware(assessed_at, "assessed_at")
    return f"performance_assessment:{episode_id}:{assessment_type.value}:{assessed_at.isoformat()}"


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
    criteria: HeatingPerformanceAssessmentCriteria
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
