"""Bounded immutable diagnostics for M30.2 source resilience."""

from dataclasses import dataclass

SOURCE_RESILIENCE_DIAGNOSTICS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SourceResilienceDiagnosticsV1:
    schema_version: int
    updated_at: str | None
    operating_mode: str
    operating_mode_reason: str
    desired_source_state: str | None
    reported_source_state: str | None
    reported_source_observed_at: str | None
    last_successful_command: str | None
    source_ownership: str
    source_capabilities: tuple[str, ...]
    drift_detected: bool | None
    reconciliation_status: str | None
    reconciliation_reason: str | None
    transition_history: str
    recovery_status: str | None
    recovery_reason: str | None
    corrective_intent_pending: str | None
    corrective_action_blocked_reason: str | None
    corrective_action_blocked_deadline: str | None
    manual_recovery_active: bool
    manual_recovery_deadline: str | None
    manual_recovery_remaining_seconds: float | None
    safe_heating_degraded: bool
    water_target_intent: float | None
