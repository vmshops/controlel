"""Immutable, localization-neutral Water Safety diagnostic projection contracts."""

from dataclasses import asdict, dataclass
from typing import Any

WATER_SAFETY_DIAGNOSTICS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WaterSafetyActionsAvailableV1:
    silence: bool
    disable: bool
    enable: bool
    test_notification: bool
    test_siren: bool


@dataclass(frozen=True)
class WaterSafetyDiagnosticsSnapshotV1:
    schema_version: int
    state: str
    assessment_status: str
    sensor_condition: str | None
    area_name: str
    zone_name: str
    active_incident: bool
    incident_silenced: bool
    processing_enabled: bool
    owned_siren_count: int
    last_siren_command_outcome: str | None
    actions_available: WaterSafetyActionsAvailableV1


def water_safety_diagnostics_to_dict(snapshot: WaterSafetyDiagnosticsSnapshotV1) -> dict[str, Any]:
    return asdict(snapshot)
