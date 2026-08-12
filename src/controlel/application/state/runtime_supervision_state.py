"""Immutable application state for runtime supervision."""

from dataclasses import dataclass
from datetime import datetime

from controlel.application.state.source_control_state import SourceControlState
from controlel.application.state.source_reconciliation_state import SourceReconciliationState
from controlel.domain.operating_mode import OperatingMode
from controlel.domain.runtime_supervision import CommandAuthority, FailsafeReason, SupervisorPhase
from controlel.domain.source_control import ReportedSourceEvidence, SourceCapabilities, SourceOwnership


@dataclass(frozen=True)
class RuntimeSupervisionState:
    phase: SupervisorPhase
    command_authority: CommandAuthority
    normal_generation: int
    fatal_cause_code: str | None
    failsafe_mode: OperatingMode | None
    failsafe_reason: FailsafeReason | None
    restart_attempt_count: int
    restart_budget: int
    next_restart_at: datetime | None
    restart_budget_exhausted: bool
    manual_recovery_deadline: datetime | None
    last_recovered_to_normal_at: datetime | None


@dataclass(frozen=True)
class RuntimeSupervisionDiagnosticsV1:
    schema_version: int
    supervisor_state: str
    active_command_authority: str
    normal_runtime_generation: int
    last_fatal_cause_code: str | None
    failsafe_state: str | None
    failsafe_reason: str | None
    restart_attempt_count: int
    restart_budget: int
    next_restart_at: str | None
    restart_budget_exhausted: bool
    manual_recovery_deadline: str | None
    last_successful_recovery_to_normal: str | None


@dataclass(frozen=True)
class RuntimeHandoverEvidence:
    """Truthful source evidence transferred before NORMAL authority activation."""

    reported_source: ReportedSourceEvidence | None
    source_ownership: SourceOwnership
    source_capabilities: SourceCapabilities
    source_control_state: SourceControlState | None
    reconciliation_state: SourceReconciliationState | None
