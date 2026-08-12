"""Deterministic presentation-neutral projection of source resilience evidence."""

from dataclasses import asdict
from datetime import datetime
from typing import Any

from controlel.application.services.operating_mode_policy import OperatingModeAssessment
from controlel.application.state.operating_mode_state import OperatingModeState
from controlel.application.state.source_control_state import SourceControlState
from controlel.application.state.source_reconciliation_state import (
    SourceReconciliationAssessment,
    SourceReconciliationStatus,
)
from controlel.application.state.source_recovery_state import SourceRecoveryAssessment
from controlel.application.state.source_resilience_diagnostics import (
    SOURCE_RESILIENCE_DIAGNOSTICS_SCHEMA_VERSION,
    SourceResilienceDiagnosticsV1,
)
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.operating_mode import OperatingMode
from controlel.domain.source_control import (
    ReportedSourceEvidence,
    SourceCapabilities,
    SourceOwnership,
    TransitionHistoryKnowledge,
)


class SourceResilienceDiagnosticsProjector:
    """Project one bounded snapshot without influencing any control state."""

    def project(
        self,
        *,
        operating_mode_state: OperatingModeState,
        operating_mode_assessment: OperatingModeAssessment | None,
        ownership: SourceOwnership,
        capabilities: SourceCapabilities,
        reported: ReportedSourceEvidence | None,
        last_successful_command: HeatingAction | None,
        reconciliation: SourceReconciliationAssessment | None,
        recovery: SourceRecoveryAssessment | None,
        source_control_state: SourceControlState | None,
        now: datetime,
    ) -> SourceResilienceDiagnosticsV1:
        _aware(now)
        timestamps = [operating_mode_state.last_evaluated_at]
        if reported is not None:
            timestamps.append(reported.observed_at)
        if reconciliation is not None:
            timestamps.append(reconciliation.state.last_evaluated_at)
        if recovery is not None:
            timestamps.append(recovery.state.last_evaluated_at)
        if source_control_state is not None:
            timestamps.append(source_control_state.last_evaluated_at)

        drift_detected = _drift(reconciliation)
        blocked_reason, blocked_deadline = _blocked(reconciliation, recovery, source_control_state)
        manual_deadline = operating_mode_state.manual_recovery_deadline
        manual_active = operating_mode_state.mode is OperatingMode.MANUAL_RECOVERY_HEAT
        return SourceResilienceDiagnosticsV1(
            schema_version=SOURCE_RESILIENCE_DIAGNOSTICS_SCHEMA_VERSION,
            updated_at=max(timestamps).isoformat() if timestamps else None,
            operating_mode=operating_mode_state.mode.value,
            operating_mode_reason=operating_mode_state.reason.value,
            desired_source_state=(
                reconciliation.state.desired_command.value
                if reconciliation is not None and reconciliation.state.desired_command is not None
                else operating_mode_assessment.desired_source_command.value
                if operating_mode_assessment is not None
                and operating_mode_assessment.desired_source_command is not None
                else None
            ),
            reported_source_state=reported.state.value if reported is not None else None,
            reported_source_observed_at=reported.observed_at.isoformat() if reported is not None else None,
            last_successful_command=(last_successful_command.value if last_successful_command is not None else None),
            source_ownership=ownership.value,
            source_capabilities=tuple(sorted(capability.value for capability in capabilities.values)),
            drift_detected=drift_detected,
            reconciliation_status=reconciliation.status.value if reconciliation is not None else None,
            reconciliation_reason=reconciliation.reason.value if reconciliation is not None else None,
            transition_history=(
                reported.transition_history.value if reported is not None else TransitionHistoryKnowledge.UNKNOWN.value
            ),
            recovery_status=recovery.status.value if recovery is not None else None,
            recovery_reason=recovery.reason.value if recovery is not None else None,
            corrective_intent_pending=(
                reconciliation.state.corrective_intent.value
                if reconciliation is not None and reconciliation.state.corrective_intent is not None
                else None
            ),
            corrective_action_blocked_reason=blocked_reason,
            corrective_action_blocked_deadline=blocked_deadline.isoformat() if blocked_deadline is not None else None,
            manual_recovery_active=manual_active,
            manual_recovery_deadline=manual_deadline.isoformat() if manual_deadline is not None else None,
            manual_recovery_remaining_seconds=(
                max(0.0, (manual_deadline - now).total_seconds())
                if manual_active and manual_deadline is not None
                else None
            ),
            safe_heating_degraded=(
                operating_mode_assessment.degraded if operating_mode_assessment is not None else False
            ),
            water_target_intent=(
                operating_mode_assessment.water_target_intent.target_temperature
                if operating_mode_assessment is not None and operating_mode_assessment.water_target_intent is not None
                else None
            ),
        )


def source_resilience_diagnostics_to_dict(
    snapshot: SourceResilienceDiagnosticsV1,
) -> dict[str, Any]:
    """Convert the fixed schema to JSON-safe primitives."""

    payload = asdict(snapshot)
    payload["source_capabilities"] = list(snapshot.source_capabilities)
    return payload


def _drift(assessment: SourceReconciliationAssessment | None) -> bool | None:
    if assessment is None or assessment.status in {
        SourceReconciliationStatus.EXPECTED_UNKNOWN,
        SourceReconciliationStatus.REPORTED_INDETERMINATE,
    }:
        return None
    return assessment.status in {
        SourceReconciliationStatus.DRIFT_HOLDING,
        SourceReconciliationStatus.CORRECTION_REQUIRED,
        SourceReconciliationStatus.CORRECTION_PENDING,
    }


def _blocked(
    reconciliation: SourceReconciliationAssessment | None,
    recovery: SourceRecoveryAssessment | None,
    source: SourceControlState | None,
) -> tuple[str | None, datetime | None]:
    if recovery is not None and recovery.blocks_source_commands:
        return recovery.reason.value, recovery.deadline
    if source is not None and source.active_lockout_type is not None:
        return source.active_lockout_type.value, source.active_lockout_deadline
    if reconciliation is not None and reconciliation.next_reevaluation_at is not None:
        return reconciliation.reason.value, reconciliation.next_reevaluation_at
    return None, None


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
