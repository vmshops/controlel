"""Application contracts for truthful Water Safety output and evidence handling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from controlel.application.setup import ProviderReference
from controlel.domain.water_safety import MoistureObservation, WaterIncident, WaterSafetySnapshot, WaterSafetyState


class WaterOutputKind(StrEnum):
    NOTIFICATION = "NOTIFICATION"
    SIREN = "SIREN"


class WaterOutputAction(StrEnum):
    NOTIFY_WET = "NOTIFY_WET"
    NOTIFY_RECOVERY = "NOTIFY_RECOVERY"
    NOTIFY_SENSOR_FAULT = "NOTIFY_SENSOR_FAULT"
    REQUEST_SIREN_ON = "REQUEST_SIREN_ON"
    REQUEST_SIREN_OFF = "REQUEST_SIREN_OFF"


class WaterOutputOutcome(StrEnum):
    """Adapter outcome only; ACCEPTED never claims a physical output state."""

    ACCEPTED = "ACCEPTED"
    FAILED = "FAILED"


class WaterSafetyEventCode(StrEnum):
    RUNTIME_STARTED = "RUNTIME_STARTED"
    OBSERVATION_ACCEPTED = "OBSERVATION_ACCEPTED"
    OBSERVATION_IGNORED_OUT_OF_ORDER = "OBSERVATION_IGNORED_OUT_OF_ORDER"
    WET_INCIDENT_STARTED = "WET_INCIDENT_STARTED"
    WET_INCIDENT_RECOVERED = "WET_INCIDENT_RECOVERED"
    SENSOR_GRACE_STARTED = "SENSOR_GRACE_STARTED"
    SENSOR_FAULT_STARTED = "SENSOR_FAULT_STARTED"
    SENSOR_FAULT_RECOVERED = "SENSOR_FAULT_RECOVERED"
    SENSOR_FAULT_NOTIFICATION_REPEATED = "SENSOR_FAULT_NOTIFICATION_REPEATED"
    OUTPUT_REQUESTED = "OUTPUT_REQUESTED"
    INCIDENT_SILENCED = "INCIDENT_SILENCED"
    MODULE_DISABLE_STARTED = "MODULE_DISABLE_STARTED"
    MODULE_DISABLED = "MODULE_DISABLED"
    MODULE_ENABLED = "MODULE_ENABLED"


@dataclass(frozen=True, slots=True)
class WaterOutputOwner:
    """Stable ownership key usable by a future generic Safety Shutdown."""

    environment_id: str
    module_key: str
    module_instance_id: str

    def __post_init__(self) -> None:
        if not self.environment_id or not self.module_key or not self.module_instance_id:
            raise ValueError("output ownership fields must not be empty")


@dataclass(frozen=True, slots=True)
class WaterOutputCommand:
    """One requested side effect, kept distinct from its reported outcome."""

    command_id: str
    requested_at: datetime
    owner: WaterOutputOwner
    output_kind: WaterOutputKind
    action: WaterOutputAction
    target_role: str
    target: ProviderReference
    incident_id: str | None = None
    message_code: str | None = None
    custom_message: str | None = None
    repeated: bool = False

    def __post_init__(self) -> None:
        if not self.command_id or not self.target_role:
            raise ValueError("command_id and target_role must not be empty")
        _require_aware(self.requested_at, "requested_at")
        if self.output_kind is WaterOutputKind.NOTIFICATION:
            if self.action not in {
                WaterOutputAction.NOTIFY_WET,
                WaterOutputAction.NOTIFY_RECOVERY,
                WaterOutputAction.NOTIFY_SENSOR_FAULT,
            }:
                raise ValueError("notification output requires a notification action")
            if not self.message_code:
                raise ValueError("notification output requires message_code")
        elif self.action not in {WaterOutputAction.REQUEST_SIREN_ON, WaterOutputAction.REQUEST_SIREN_OFF}:
            raise ValueError("siren output requires a siren action")


@dataclass(frozen=True, slots=True)
class WaterOutputCommandResult:
    """What an adapter reported about accepting a request; physical state remains unknown."""

    command_id: str
    occurred_at: datetime
    outcome: WaterOutputOutcome
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if not self.command_id:
            raise ValueError("command_id must not be empty")
        _require_aware(self.occurred_at, "occurred_at")
        if self.outcome is WaterOutputOutcome.FAILED and not self.failure_code:
            raise ValueError("failed output command requires failure_code")
        if self.outcome is WaterOutputOutcome.ACCEPTED and self.failure_code is not None:
            raise ValueError("accepted output command cannot include failure_code")


@dataclass(frozen=True, slots=True)
class OwnedWaterOutput:
    """A configured module-owned persistent output and its last request evidence."""

    owner: WaterOutputOwner
    target_role: str
    target: ProviderReference
    last_requested_action: WaterOutputAction | None = None
    last_command_outcome: WaterOutputOutcome | None = None
    last_requested_at: datetime | None = None
    last_failure_code: str | None = None

    def __post_init__(self) -> None:
        if not self.target_role:
            raise ValueError("target_role must not be empty")
        if self.last_requested_at is not None:
            _require_aware(self.last_requested_at, "last_requested_at")
        supplied = (
            self.last_requested_action is not None,
            self.last_command_outcome is not None,
            self.last_requested_at is not None,
        )
        if len(set(supplied)) != 1:
            raise ValueError("last output request fields must be present together")
        if self.last_command_outcome is WaterOutputOutcome.FAILED and not self.last_failure_code:
            raise ValueError("failed output request evidence requires last_failure_code")
        if self.last_command_outcome is not WaterOutputOutcome.FAILED and self.last_failure_code is not None:
            raise ValueError("only failed output request evidence may include last_failure_code")


@dataclass(frozen=True, slots=True)
class WaterSafetyEvent:
    """Immutable evidence/history hook payload."""

    event_id: str
    occurred_at: datetime
    code: WaterSafetyEventCode
    previous_state: WaterSafetyState
    new_state: WaterSafetyState
    observation: MoistureObservation | None = None
    incident_id: str | None = None
    command: WaterOutputCommand | None = None
    command_result: WaterOutputCommandResult | None = None
    details: tuple[tuple[str, str | int | float | bool | None], ...] = ()

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id must not be empty")
        _require_aware(self.occurred_at, "occurred_at")
        keys = tuple(key for key, _ in self.details)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("event detail keys must be unique and sorted")
        if (self.command is None) != (self.command_result is None):
            raise ValueError("output evidence requires both command and command result")


@dataclass(frozen=True, slots=True)
class WaterSafetyProcessingResult:
    previous_state: WaterSafetyState
    state: WaterSafetyState
    snapshot: WaterSafetySnapshot
    events: tuple[WaterSafetyEvent, ...] = ()
    output_results: tuple[WaterOutputCommandResult, ...] = ()


@dataclass(frozen=True, slots=True)
class WaterSafetyDiagnostics:
    """Current assessment, observations, deadlines, and command evidence."""

    state: WaterSafetyState
    processing_enabled: bool
    sensor_id: str
    zone_id: str
    area_id: str
    critical_sensor: bool
    latest_observation: MoistureObservation | None
    active_incident: WaterIncident | None
    last_incident: WaterIncident | None
    fault_deadline: datetime | None
    next_fault_notification_at: datetime | None
    owned_outputs: tuple[OwnedWaterOutput, ...]
    canonical_revision_id: str
    semantic_configuration_fingerprint: str


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
