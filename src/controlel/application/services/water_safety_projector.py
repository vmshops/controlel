"""Deterministic projection of Water Safety evidence into presentation-neutral diagnostics."""

from controlel.application.state.water_safety_diagnostics import (
    WATER_SAFETY_DIAGNOSTICS_SCHEMA_VERSION,
    WaterSafetyActionsAvailableV1,
    WaterSafetyDiagnosticsSnapshotV1,
)
from controlel.application.water_safety.model import WaterOutputOutcome, WaterSafetyDiagnostics
from controlel.domain.water_safety import WaterSafetyState


class WaterSafetyDiagnosticsProjector:
    """Build immutable diagnostics without affecting observation or control."""

    def project(
        self,
        diagnostics: WaterSafetyDiagnostics,
        *,
        area_name: str,
        zone_name: str,
    ) -> WaterSafetyDiagnosticsSnapshotV1:
        latest = diagnostics.latest_observation
        sensor_condition = None if latest is None else latest.condition.value
        incident = diagnostics.active_incident
        incident_silenced = incident is not None and incident.silenced_at is not None
        owned_sirens = diagnostics.owned_outputs
        last_siren_outcome = _last_siren_command_outcome(owned_sirens)
        return WaterSafetyDiagnosticsSnapshotV1(
            schema_version=WATER_SAFETY_DIAGNOSTICS_SCHEMA_VERSION,
            state=diagnostics.state.value,
            assessment_status=diagnostics.assessment_status.value,
            sensor_condition=sensor_condition,
            area_name=area_name,
            zone_name=zone_name,
            active_incident=incident is not None,
            incident_silenced=incident_silenced,
            processing_enabled=diagnostics.processing_enabled,
            owned_siren_count=len(owned_sirens),
            last_siren_command_outcome=last_siren_outcome,
            actions_available=_actions_available(diagnostics),
        )


def _last_siren_command_outcome(owned_outputs: tuple[object, ...]) -> str | None:
    latest_at = None
    latest_outcome: str | None = None
    for output in owned_outputs:
        requested_at = getattr(output, "last_requested_at", None)
        outcome = getattr(output, "last_command_outcome", None)
        if requested_at is None or outcome is None:
            continue
        if latest_at is None or requested_at > latest_at:
            latest_at = requested_at
            latest_outcome = "accepted" if outcome is WaterOutputOutcome.ACCEPTED else "failed"
    return latest_outcome


def _actions_available(diagnostics: WaterSafetyDiagnostics) -> WaterSafetyActionsAvailableV1:
    state = diagnostics.state
    processing_enabled = diagnostics.processing_enabled
    incident = diagnostics.active_incident
    incident_silenced = incident is not None and incident.silenced_at is not None
    safe_for_test = state is not WaterSafetyState.WET and state is not WaterSafetyState.DISABLED
    return WaterSafetyActionsAvailableV1(
        silence=(
            processing_enabled and state is WaterSafetyState.WET and incident is not None and not incident_silenced
        ),
        disable=processing_enabled and state is not WaterSafetyState.DISABLED,
        enable=state is WaterSafetyState.DISABLED,
        test_notification=safe_for_test and processing_enabled,
        test_siren=safe_for_test and processing_enabled and bool(diagnostics.owned_outputs),
    )
