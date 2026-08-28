"""Immutable, host-neutral Water Safety v1 state contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

WATER_SAFETY_STATE_SCHEMA_VERSION = 1


class MoistureCondition(StrEnum):
    """A sensor observation; UNKNOWN and UNAVAILABLE are never dry evidence."""

    DRY = "DRY"
    WET = "WET"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class WaterSafetyState(StrEnum):
    """Primary state; consult assessment status before presenting OK as confirmed."""

    OK = "OK"
    WET = "WET"
    SENSOR_FAULT = "SENSOR_FAULT"
    DISABLED = "DISABLED"


class WaterSafetyAssessmentStatus(StrEnum):
    """Whether the primary state is currently supported by usable sensor evidence."""

    CONFIRMED = "CONFIRMED"
    INDETERMINATE_GRACE = "INDETERMINATE_GRACE"
    DISABLED = "DISABLED"


class WaterIncidentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RECOVERED = "RECOVERED"


@dataclass(frozen=True, slots=True)
class MoistureObservation:
    """What the configured sensor reported, without assessment or inference."""

    sensor_id: str
    condition: MoistureCondition
    observed_at: datetime
    provider_state: str | None = None

    def __post_init__(self) -> None:
        if not self.sensor_id:
            raise ValueError("sensor_id must not be empty")
        _require_aware(self.observed_at, "observed_at")
        if not isinstance(self.condition, MoistureCondition):
            raise TypeError("condition must be a MoistureCondition")


@dataclass(frozen=True, slots=True)
class WaterIncident:
    """One evidence-based wet incident; disable does not fabricate recovery."""

    incident_id: str
    status: WaterIncidentStatus
    started_at: datetime
    last_confirmed_wet_at: datetime
    recovered_at: datetime | None = None
    silenced_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.incident_id:
            raise ValueError("incident_id must not be empty")
        _require_aware(self.started_at, "started_at")
        _require_aware(self.last_confirmed_wet_at, "last_confirmed_wet_at")
        if self.last_confirmed_wet_at < self.started_at:
            raise ValueError("last confirmed wet time cannot precede incident start")
        if self.recovered_at is not None:
            _require_aware(self.recovered_at, "recovered_at")
        if self.silenced_at is not None:
            _require_aware(self.silenced_at, "silenced_at")
        if self.status is WaterIncidentStatus.ACTIVE and self.recovered_at is not None:
            raise ValueError("active incident cannot have recovered_at")
        if self.status is WaterIncidentStatus.RECOVERED:
            if self.recovered_at is None:
                raise ValueError("recovered incident requires recovered_at")
            if self.recovered_at < self.last_confirmed_wet_at:
                raise ValueError("recovery cannot precede last confirmed wet evidence")


@dataclass(frozen=True, slots=True)
class WaterSafetySnapshot:
    """Persistable runtime state used for deterministic restart recovery."""

    environment_id: str
    module_instance_id: str
    canonical_revision_id: str
    semantic_configuration_fingerprint: str
    sensor_id: str
    state: WaterSafetyState
    processing_enabled: bool
    latest_observation: MoistureObservation | None = None
    last_confirmed_observation: MoistureObservation | None = None
    active_incident: WaterIncident | None = None
    last_incident: WaterIncident | None = None
    unavailable_since: datetime | None = None
    fault_deadline: datetime | None = None
    next_fault_notification_at: datetime | None = None
    next_incident_sequence: int = 1
    next_command_sequence: int = 1
    next_event_sequence: int = 1
    schema_version: int = WATER_SAFETY_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, label in (
            (self.environment_id, "environment_id"),
            (self.module_instance_id, "module_instance_id"),
            (self.canonical_revision_id, "canonical_revision_id"),
            (self.semantic_configuration_fingerprint, "semantic_configuration_fingerprint"),
            (self.sensor_id, "sensor_id"),
        ):
            if not value:
                raise ValueError(f"{label} must not be empty")
        if self.schema_version != WATER_SAFETY_STATE_SCHEMA_VERSION:
            raise ValueError(f"unsupported Water Safety state schema version: {self.schema_version}")
        if self.state is WaterSafetyState.DISABLED and self.processing_enabled:
            raise ValueError("DISABLED state cannot have processing enabled")
        if self.state is not WaterSafetyState.DISABLED and not self.processing_enabled:
            raise ValueError("non-DISABLED state requires processing enabled")
        if self.active_incident is not None and self.active_incident.status is not WaterIncidentStatus.ACTIVE:
            raise ValueError("active_incident must have ACTIVE status")
        if self.state is WaterSafetyState.WET and self.active_incident is None:
            raise ValueError("WET state requires an active incident")
        if self.state is WaterSafetyState.OK and self.active_incident is not None:
            raise ValueError("OK state cannot retain an active incident")
        if self.last_incident is not None and self.last_incident.status is not WaterIncidentStatus.RECOVERED:
            raise ValueError("last_incident must have RECOVERED status")
        if self.last_confirmed_observation is not None and self.last_confirmed_observation.condition not in {
            MoistureCondition.DRY,
            MoistureCondition.WET,
        }:
            raise ValueError("last_confirmed_observation must be DRY or WET")
        if (self.unavailable_since is None) != (self.fault_deadline is None):
            raise ValueError("unavailable_since and fault_deadline must be present together")
        if self.fault_deadline is not None and self.state not in {WaterSafetyState.OK, WaterSafetyState.WET}:
            raise ValueError("sensor grace deadline requires OK or WET state")
        if self.unavailable_since is not None:
            _require_aware(self.unavailable_since, "unavailable_since")
            assert self.fault_deadline is not None
            _require_aware(self.fault_deadline, "fault_deadline")
            if self.fault_deadline < self.unavailable_since:
                raise ValueError("fault deadline cannot precede unavailable observation")
        if self.next_fault_notification_at is not None:
            _require_aware(self.next_fault_notification_at, "next_fault_notification_at")
            if self.state is not WaterSafetyState.SENSOR_FAULT:
                raise ValueError("fault notification deadline requires SENSOR_FAULT state")
        for sequence_value, sequence_label in (
            (self.next_incident_sequence, "next_incident_sequence"),
            (self.next_command_sequence, "next_command_sequence"),
            (self.next_event_sequence, "next_event_sequence"),
        ):
            if sequence_value < 1:
                raise ValueError(f"{sequence_label} must be positive")

    @property
    def assessment_status(self) -> WaterSafetyAssessmentStatus:
        if not self.processing_enabled:
            return WaterSafetyAssessmentStatus.DISABLED
        if self.fault_deadline is not None:
            return WaterSafetyAssessmentStatus.INDETERMINATE_GRACE
        return WaterSafetyAssessmentStatus.CONFIRMED


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
