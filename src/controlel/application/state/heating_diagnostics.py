"""Immutable, localization-neutral heating diagnostic projection contracts."""

from dataclasses import asdict, dataclass
from typing import Any

HEATING_DIAGNOSTICS_SCHEMA_VERSION = 1
MAX_PROJECTED_ACTUATORS = 16
MAX_PROJECTED_PIPELINE_ERRORS = 32
MAX_PROJECTED_ZONES = 64


@dataclass(frozen=True)
class QualityCountV1:
    quality: str
    count: int


@dataclass(frozen=True)
class ObservedValueDiagnosticsV1:
    value: str | float | bool | None
    quality: str
    reason_code: str | None
    observed_at: str | None


@dataclass(frozen=True)
class DerivedValueDiagnosticsV1:
    value: float | None
    quality: str
    reason_code: str | None


@dataclass(frozen=True)
class TemperatureEvidenceV1:
    first_valid_temperature: float | None
    first_valid_observed_at: str | None
    latest_valid_temperature: float | None
    latest_valid_observed_at: str | None
    terminal_temperature: float | None
    terminal_temperature_quality: str
    terminal_temperature_reason_code: str | None
    temperature_delta: float | None
    observation_duration_seconds: float | None
    response_trend: str
    distinct_valid_measurement_count: int
    duplicate_valid_measurement_count: int
    excluded_quality_counts: tuple[QualityCountV1, ...]
    conflicting_evidence: bool
    non_monotonic_evidence: bool


@dataclass(frozen=True)
class TargetEvidenceV1:
    initial_target_temperature: float
    final_target_temperature: float
    target_changed: bool | None
    start_target_relative_error: DerivedValueDiagnosticsV1
    end_target_relative_error: DerivedValueDiagnosticsV1


@dataclass(frozen=True)
class CommandEvidenceV1:
    kind: str
    value: float | bool
    requested_at: str


@dataclass(frozen=True)
class ActuatorEvidenceV1:
    actuator_id: str
    mode: str
    capabilities: tuple[str, ...]
    requested_command: CommandEvidenceV1 | None
    successfully_dispatched_command: CommandEvidenceV1 | None
    command_outcome: str | None
    command_evidence_at: str | None
    reported_target_temperature: ObservedValueDiagnosticsV1
    reported_local_temperature: ObservedValueDiagnosticsV1
    reported_position: ObservedValueDiagnosticsV1
    reported_binary_open: ObservedValueDiagnosticsV1
    reported_activity: ObservedValueDiagnosticsV1


@dataclass(frozen=True)
class SourceEvidenceV1:
    requested_permission: str | None
    successfully_dispatched_permission: str | None
    successful_dispatch_at: str | None
    physical_heat_available: ObservedValueDiagnosticsV1


@dataclass(frozen=True)
class EpisodeDiagnosticsV1:
    zone_id: str
    lifecycle: str
    started_at: str
    ended_at: str | None
    completed_duration_seconds: float | None
    observed_duration_through_latest_evidence_seconds: float
    termination_reason: str | None
    total_sample_count: int
    retained_sample_count: int
    samples_truncated: bool
    temperature: TemperatureEvidenceV1
    target: TargetEvidenceV1
    actuators: tuple[ActuatorEvidenceV1, ...]
    actuator_count_truncated: bool
    source: SourceEvidenceV1


@dataclass(frozen=True)
class AssessmentCriteriaV1:
    stable_temperature_tolerance: float
    target_change_tolerance: float


@dataclass(frozen=True)
class AssessmentEvidenceV1:
    total_sample_count: int
    retained_sample_count: int
    samples_truncated: bool
    distinct_valid_measurement_count: int
    duplicate_valid_measurement_count: int
    zone_temperature_quality_counts: tuple[QualityCountV1, ...]
    target_changed: bool
    actuator_command_evidence_count: int
    actuator_reported_value_count: int
    source_permission_evidence_count: int
    source_availability_quality_counts: tuple[QualityCountV1, ...]


@dataclass(frozen=True)
class TemperatureResponseV1:
    first_temperature: float
    first_observed_at: str
    last_temperature: float
    last_observed_at: str
    temperature_change: float
    observation_duration_seconds: float
    temperature_change_per_hour: float
    direction: str


@dataclass(frozen=True)
class AssessmentDiagnosticsV1:
    zone_id: str
    episode_started_at: str
    episode_ended_at: str
    assessed_at: str
    status: str
    reason_codes: tuple[str, ...]
    termination_reason: str
    criteria: AssessmentCriteriaV1
    temperature_response: TemperatureResponseV1 | None
    evidence: AssessmentEvidenceV1
    conflicting_evidence: bool
    non_monotonic_evidence: bool
    history_truncated: bool


@dataclass(frozen=True)
class DiagnosticErrorEvidenceV1:
    component: str
    reason_code: str
    exception_type: str
    zone_id: str | None
    evidence_at: str | None
    episode_started_at: str | None = None


@dataclass(frozen=True)
class PendingDropEvidenceV1:
    zone_id: str
    episode_started_at: str
    episode_ended_at: str
    reason_code: str


@dataclass(frozen=True)
class ZoneHeatingDiagnosticsV1:
    zone_id: str
    active_episode: EpisodeDiagnosticsV1 | None
    latest_completed_episode: EpisodeDiagnosticsV1 | None
    latest_assessment: AssessmentDiagnosticsV1 | None
    observation_error: DiagnosticErrorEvidenceV1 | None


@dataclass(frozen=True)
class ShadowPipelineDiagnosticsV1:
    health_code: str
    enabled: bool
    pending_assessment_count: int
    retained_assessment_count: int
    assessment_capacity: int
    dropped_pending_assessment_count: int
    latest_drop: PendingDropEvidenceV1 | None
    assessment_error_count: int
    observation_error_count: int
    error_evidence_truncated: bool
    assessment_errors: tuple[DiagnosticErrorEvidenceV1, ...]
    observation_errors: tuple[DiagnosticErrorEvidenceV1, ...]
    projection_error: DiagnosticErrorEvidenceV1 | None


@dataclass(frozen=True)
class HeatingDiagnosticsSnapshotV1:
    schema_version: int
    updated_at: str | None
    total_zone_count: int
    zones_truncated: bool
    zones: tuple[ZoneHeatingDiagnosticsV1, ...]
    pipeline: ShadowPipelineDiagnosticsV1


def heating_diagnostics_to_dict(snapshot: HeatingDiagnosticsSnapshotV1) -> dict[str, Any]:
    """Return only JSON-native primitives from one immutable snapshot."""

    return asdict(snapshot)


def empty_heating_diagnostics_snapshot(zone_id: str) -> HeatingDiagnosticsSnapshotV1:
    """Create deterministic empty diagnostics without a fabricated timestamp."""

    return HeatingDiagnosticsSnapshotV1(
        schema_version=HEATING_DIAGNOSTICS_SCHEMA_VERSION,
        updated_at=None,
        total_zone_count=1,
        zones_truncated=False,
        zones=(
            ZoneHeatingDiagnosticsV1(
                zone_id=zone_id,
                active_episode=None,
                latest_completed_episode=None,
                latest_assessment=None,
                observation_error=None,
            ),
        ),
        pipeline=ShadowPipelineDiagnosticsV1(
            health_code="healthy",
            enabled=True,
            pending_assessment_count=0,
            retained_assessment_count=0,
            assessment_capacity=0,
            dropped_pending_assessment_count=0,
            latest_drop=None,
            assessment_error_count=0,
            observation_error_count=0,
            error_evidence_truncated=False,
            assessment_errors=(),
            observation_errors=(),
            projection_error=None,
        ),
    )
