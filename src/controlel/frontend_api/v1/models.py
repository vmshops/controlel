"""Immutable input evidence and JSON-safe DTOs for Frontend API v1."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Literal, cast

type RuntimeStatus = Literal["active", "degraded", "stopped"]
type ModuleStatus = Literal["active", "inactive", "error"]
type AttentionSeverity = Literal["info", "notice", "warning", "critical"]
type DemandStatus = Literal["heat_required", "no_heat_required", "indeterminate"]
type Permission = Literal["enabled", "disabled", "unknown"]
type RequestedCommand = Literal["enable", "disable"]
type CommandOutcome = Literal["dispatched", "failed", "suppressed", "deferred", "held"]
type ReportedSourceState = Literal["ENABLED", "DISABLED", "UNKNOWN", "UNAVAILABLE"]
type DecisionAction = Literal["enable_heating", "disable_heating", "observe_only"]
type MeasurementState = Literal["fresh", "expired", "future_dated", "missing"]
type SetupState = Literal["ready", "incomplete", "invalid", "unknown"]
type SetupSeverity = Literal["error", "warning", "info"]
type WaterSafetyStateV1 = Literal["OK", "WET", "SENSOR_FAULT", "DISABLED"]
type WaterSafetyAssessmentStatusV1 = Literal["CONFIRMED", "INDETERMINATE_GRACE", "DISABLED"]
type MoistureConditionV1 = Literal["DRY", "WET", "UNAVAILABLE", "UNKNOWN"]
type SirenCommandOutcomeV1 = Literal["accepted", "failed"]
type WaterSafetyActionV1 = Literal["silence", "disable", "enable", "test_notification", "test_siren"]
type EvidenceScalar = str | int | float | bool | None


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_identifier(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class ScopeV1:
    """Stable Controlel scope; host locators are deliberately absent."""

    type: str
    module_id: str | None = None
    zone_id: str | None = None
    sensor_id: str | None = None
    source_id: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.type, "scope type")


@dataclass(frozen=True, slots=True)
class SystemEvidenceV1:
    status: RuntimeStatus
    operating_mode: str
    operating_mode_reason: str | None = None
    operating_mode_since: datetime | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.operating_mode, "operating_mode")
        if self.operating_mode_since is not None:
            _require_aware(self.operating_mode_since, "operating_mode_since")


@dataclass(frozen=True, slots=True)
class ModuleEvidenceV1:
    module_id: str
    status: ModuleStatus
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.module_id, "module_id")


@dataclass(frozen=True, slots=True)
class AttentionEvidenceV1:
    attention_id: str
    severity: AttentionSeverity
    code: str
    scope: ScopeV1
    summary: str
    first_seen_at: datetime

    def __post_init__(self) -> None:
        _require_identifier(self.attention_id, "attention_id")
        _require_identifier(self.code, "attention code")
        _require_aware(self.first_seen_at, "first_seen_at")


@dataclass(frozen=True, slots=True)
class DecisionEvidenceItemV1:
    code: str
    value: EvidenceScalar

    def __post_init__(self) -> None:
        _require_identifier(self.code, "evidence code")
        if isinstance(self.value, float) and not isfinite(self.value):
            raise ValueError("evidence float values must be finite")


@dataclass(frozen=True, slots=True)
class DecisionEvidenceV1:
    decision_id: str
    zone_id: str
    sensor_id: str
    action: DecisionAction
    observed_at: datetime
    reason_code: str | None
    evidence: tuple[DecisionEvidenceItemV1, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.decision_id, "decision_id")
        _require_identifier(self.zone_id, "zone_id")
        _require_identifier(self.sensor_id, "sensor_id")
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class HeatSourceEvidenceV1:
    permission: Permission = "unknown"
    requested_command: RequestedCommand | None = None
    command_outcome: CommandOutcome | None = None
    reported_state: ReportedSourceState = "UNKNOWN"
    last_decision: DecisionEvidenceV1 | None = None


@dataclass(frozen=True, slots=True)
class BuildingEvidenceV1:
    demand_status: DemandStatus = "indeterminate"
    demand_reason_code: str | None = None
    heat_source: HeatSourceEvidenceV1 = HeatSourceEvidenceV1()


@dataclass(frozen=True, slots=True)
class ZoneEvidenceV1:
    zone_id: str
    name: str
    target_temperature_c: float
    measurement_temperature_c: float | None = None
    measurement_observed_at: datetime | None = None
    measurement_max_age: timedelta | None = None
    demand_requires_heat: bool | None = None
    demand_observed_at: datetime | None = None
    demand_reason_code: str | None = None
    last_decision: DecisionEvidenceV1 | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.zone_id, "zone_id")
        if not isfinite(self.target_temperature_c):
            raise ValueError("target_temperature_c must be finite")
        if self.measurement_temperature_c is not None and not isfinite(self.measurement_temperature_c):
            raise ValueError("measurement_temperature_c must be finite")
        if self.measurement_observed_at is not None:
            _require_aware(self.measurement_observed_at, "measurement_observed_at")
        if self.demand_observed_at is not None:
            _require_aware(self.demand_observed_at, "demand_observed_at")
        if self.measurement_max_age is not None and self.measurement_max_age <= timedelta(0):
            raise ValueError("measurement_max_age must be positive")
        if (self.measurement_temperature_c is None) != (self.measurement_observed_at is None):
            raise ValueError("measurement value and timestamp must both be present or absent")


@dataclass(frozen=True, slots=True)
class OperationalEventEvidenceV1:
    event_id: str
    timestamp: datetime
    category: str
    severity: AttentionSeverity
    event_code: str
    summary_code: str
    reason_code: str | None
    scope: ScopeV1
    previous_state: str | None = None
    new_state: str | None = None
    requested_command: RequestedCommand | None = None
    command_outcome: CommandOutcome | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.event_id, "event_id")
        _require_aware(self.timestamp, "event timestamp")


@dataclass(frozen=True, slots=True)
class EventStreamEvidenceV1:
    events: tuple[OperationalEventEvidenceV1, ...] = ()
    total_emitted: int = 0
    dropped: int = 0

    def __post_init__(self) -> None:
        if self.dropped < 0 or self.total_emitted != len(self.events) + self.dropped:
            raise ValueError("event stream counts are inconsistent")


@dataclass(frozen=True, slots=True)
class MissingConfigurationEvidenceV1:
    code: str
    scope: ScopeV1
    severity: SetupSeverity


@dataclass(frozen=True, slots=True)
class ValidationMessageEvidenceV1:
    code: str
    severity: SetupSeverity
    scope: ScopeV1
    summary: str


@dataclass(frozen=True, slots=True)
class SetupEvidenceV1:
    state: SetupState = "unknown"
    reason_code: str | None = None
    missing_configuration: tuple[MissingConfigurationEvidenceV1, ...] = ()
    validation_messages: tuple[ValidationMessageEvidenceV1, ...] = ()


@dataclass(frozen=True, slots=True)
class WaterSafetyEvidenceV1:
    state: WaterSafetyStateV1
    assessment_status: WaterSafetyAssessmentStatusV1
    sensor_condition: MoistureConditionV1 | None
    area_name: str | None
    zone_name: str | None
    active_incident: bool
    incident_silenced: bool
    processing_enabled: bool
    owned_siren_count: int
    last_siren_command_outcome: SirenCommandOutcomeV1 | None
    actions_available: tuple[WaterSafetyActionV1, ...] = ()

    def __post_init__(self) -> None:
        if self.owned_siren_count < 0:
            raise ValueError("owned_siren_count must not be negative")
        if self.actions_available != tuple(sorted(set(self.actions_available))):
            raise ValueError("actions_available must be unique and sorted")


@dataclass(frozen=True, slots=True)
class FrontendApiEvidenceV1:
    """One host-created, read-only evidence snapshot consumed by the provider."""

    system: SystemEvidenceV1
    modules: tuple[ModuleEvidenceV1, ...] = ()
    attention: tuple[AttentionEvidenceV1, ...] = ()
    building: BuildingEvidenceV1 = BuildingEvidenceV1()
    zones: tuple[ZoneEvidenceV1, ...] = ()
    event_stream: EventStreamEvidenceV1 = EventStreamEvidenceV1()
    latest_decision: DecisionEvidenceV1 | None = None
    retained_decision_count: int = 0
    total_decisions: int = 0
    setup: SetupEvidenceV1 = SetupEvidenceV1()
    water_safety: WaterSafetyEvidenceV1 | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.retained_decision_count <= self.total_decisions:
            raise ValueError("decision retention counts are inconsistent")
        if self.latest_decision is not None and self.retained_decision_count == 0:
            raise ValueError("latest_decision requires retained decision evidence")


@dataclass(frozen=True, slots=True)
class FrontendResponseV1:
    frontend_api_version: int
    generated_at: str


@dataclass(frozen=True, slots=True)
class SystemV1:
    status: RuntimeStatus
    operating_mode: str
    operating_mode_reason: str | None
    operating_mode_since: str | None


@dataclass(frozen=True, slots=True)
class ModuleV1:
    module_id: str
    status: ModuleStatus
    reason: str | None


@dataclass(frozen=True, slots=True)
class AttentionV1:
    attention_id: str
    severity: AttentionSeverity
    code: str
    scope: ScopeV1
    summary: str
    first_seen_at: str


@dataclass(frozen=True, slots=True)
class OverviewResponseV1(FrontendResponseV1):
    system: SystemV1
    modules: tuple[ModuleV1, ...]
    attention: tuple[AttentionV1, ...]


@dataclass(frozen=True, slots=True)
class DecisionSummaryV1:
    decision_id: str
    action: DecisionAction
    observed_at: str
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class HeatSourceV1:
    permission: Permission
    requested_command: RequestedCommand | None
    command_outcome: CommandOutcome | None
    reported_state: ReportedSourceState
    physical_state: Literal["unknown"]
    last_decision_summary: DecisionSummaryV1 | None


@dataclass(frozen=True, slots=True)
class BuildingV1:
    demand_status: DemandStatus
    demand_reason_code: str | None
    heat_source: HeatSourceV1


@dataclass(frozen=True, slots=True)
class ZoneV1:
    zone_id: str
    name: str
    current_temperature_c: float | None
    measurement_state: MeasurementState
    measurement_age_seconds: float | None
    target_temperature_c: float
    demand_state: DemandStatus
    demand_reason_code: str | None
    last_decision: DecisionSummaryV1 | None


@dataclass(frozen=True, slots=True)
class HeatingResponseV1(FrontendResponseV1):
    building: BuildingV1
    zones: tuple[ZoneV1, ...]


@dataclass(frozen=True, slots=True)
class EventStreamHealthV1:
    total_emitted: int
    retained: int
    dropped: int


@dataclass(frozen=True, slots=True)
class HealthV1:
    runtime_status: RuntimeStatus
    operating_mode: str
    event_stream: EventStreamHealthV1


@dataclass(frozen=True, slots=True)
class EventCommandV1:
    action: RequestedCommand | None
    outcome: CommandOutcome | None


@dataclass(frozen=True, slots=True)
class OperationalEventV1:
    event_id: str
    timestamp: str
    category: str
    severity: AttentionSeverity
    event_code: str
    summary_code: str
    reason_code: str | None
    scope: ScopeV1
    previous_state: str | None
    new_state: str | None
    command: EventCommandV1 | None


@dataclass(frozen=True, slots=True)
class DecisionTraceV1:
    decision_id: str
    zone_id: str
    sensor_id: str
    action: DecisionAction
    observed_at: str
    reason_code: str | None
    evidence: tuple[DecisionEvidenceItemV1, ...]
    retained_count: int
    total_decisions: int


@dataclass(frozen=True, slots=True)
class DiagnosticsResponseV1(FrontendResponseV1):
    health: HealthV1
    recent_events: tuple[OperationalEventV1, ...]
    decision_trace: DecisionTraceV1 | None


@dataclass(frozen=True, slots=True)
class ReadinessV1:
    state: SetupState
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class MissingConfigurationV1:
    code: str
    scope: ScopeV1
    severity: SetupSeverity


@dataclass(frozen=True, slots=True)
class ValidationMessageV1:
    code: str
    severity: SetupSeverity
    scope: ScopeV1
    summary: str


@dataclass(frozen=True, slots=True)
class SetupResponseV1(FrontendResponseV1):
    readiness: ReadinessV1
    missing_configuration: tuple[MissingConfigurationV1, ...]
    validation_messages: tuple[ValidationMessageV1, ...]


@dataclass(frozen=True, slots=True)
class WaterSafetyResponseV1(FrontendResponseV1):
    state: WaterSafetyStateV1
    assessment_status: WaterSafetyAssessmentStatusV1
    sensor_condition: MoistureConditionV1 | None
    area_name: str | None
    zone_name: str | None
    active_incident: bool
    incident_silenced: bool
    processing_enabled: bool
    owned_siren_count: int
    last_siren_command_outcome: SirenCommandOutcomeV1 | None
    actions_available: tuple[WaterSafetyActionV1, ...]


def frontend_response_to_dict(response: FrontendResponseV1) -> dict[str, Any]:
    """Return JSON-native containers and scalar values from one response."""

    return cast(dict[str, Any], _json_value(asdict(response)))


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value
