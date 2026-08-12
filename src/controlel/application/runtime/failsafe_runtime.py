"""Minimal event-driven source controller used while normal runtime is quarantined."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from controlel.application.ports.heat_source_port import HeatSourcePort
from controlel.application.services.operating_mode_policy import OperatingModePolicy
from controlel.application.services.source_control_policy import SourceControlOutcome, SourceControlPolicy
from controlel.application.state.operating_mode_state import OperatingModeState
from controlel.application.state.runtime_supervision_state import RuntimeHandoverEvidence
from controlel.application.state.source_control_state import SourceControlState
from controlel.application.state.source_reconciliation_state import SourceReconciliationState
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.heat_delivery import ObservationQuality
from controlel.domain.operating_mode import (
    OperatingMode,
    SafeHeatingProfile,
    SafeHeatingTemperatureEvidence,
)
from controlel.domain.source_control import ReportedSourceEvidence, SourceCapabilities, SourceOwnership


@dataclass(frozen=True)
class FailsafeEvaluation:
    mode: OperatingMode
    desired_action: HeatingAction | None
    dispatched: bool
    next_evaluation_at: datetime | None
    source_control_state: SourceControlState


class FailsafeRuntime:
    """Apply only trusted fallback hysteresis and authoritative source protection."""

    def __init__(
        self,
        source: HeatSourcePort,
        profile: SafeHeatingProfile,
        *,
        minimum_on_time: timedelta,
        minimum_off_time: timedelta,
        capabilities: SourceCapabilities = SourceCapabilities(),
        ownership: SourceOwnership = SourceOwnership.CONTROLEL_OWNED,
    ) -> None:
        self._source = source
        self._mode_policy = OperatingModePolicy(safe_heating_profile=profile)
        self._source_policy = SourceControlPolicy(
            minimum_on_time=minimum_on_time,
            minimum_off_time=minimum_off_time,
        )
        self._capabilities = capabilities
        self.ownership = ownership
        self.reported_source_evidence: ReportedSourceEvidence | None = None
        self.source_reconciliation_state: SourceReconciliationState | None = None
        self._mode_state: OperatingModeState | None = None
        self.source_control_state: SourceControlState | None = None

    def ingest_reported_source(self, evidence: ReportedSourceEvidence) -> None:
        self.reported_source_evidence = evidence

    def restore_handover(self, evidence: RuntimeHandoverEvidence) -> None:
        """Restore only explicit source evidence before failsafe evaluation."""

        self.reported_source_evidence = evidence.reported_source
        self.ownership = evidence.source_ownership
        self._capabilities = evidence.source_capabilities
        self.source_control_state = evidence.source_control_state
        self.source_reconciliation_state = evidence.reconciliation_state

    @property
    def capabilities(self) -> SourceCapabilities:
        return self._capabilities

    def evaluate(
        self,
        *,
        now: datetime,
        evidence: SafeHeatingTemperatureEvidence | None,
        manual_recovery: bool = False,
    ) -> FailsafeEvaluation:
        mode = (
            OperatingMode.MANUAL_RECOVERY_HEAT
            if manual_recovery
            else OperatingMode.SAFE_HEATING
            if evidence is not None and evidence.value is not None and evidence.quality is ObservationQuality.VALID
            else OperatingMode.EMERGENCY_OFF
        )
        state = self._mode_state or self._mode_policy.initial_state(now=now)
        if state.mode is not mode:
            state = self._mode_policy.activate(state, mode=mode, now=now)
        assessment = self._mode_policy.evaluate(
            current_state=state,
            normal_action=None,
            preferred_evidence=evidence,
            fallback_evidence=None,
            source_capabilities=self._capabilities,
            now=now,
        )
        self._mode_state = assessment.state
        action = assessment.desired_source_command
        if action is None:
            action = HeatingAction.DISABLE_HEATING
        source_assessment = self._source_policy.evaluate(
            desired_command=action,
            now=now,
            current_state=self.source_control_state,
            safety_command=mode is OperatingMode.EMERGENCY_OFF,
        )
        self.source_control_state = source_assessment.state
        dispatched = False
        if source_assessment.outcome is SourceControlOutcome.DISPATCH:
            try:
                self._source.execute(HeatSourceCommand(command_type=CommandFamily.HEATING, action=action))
            except Exception:
                self.source_control_state = self._source_policy.record_failed(
                    source_assessment,
                    failed_at=now,
                )
                raise
            self.source_control_state = self._source_policy.record_dispatched(
                source_assessment,
                dispatched_at=now,
                safety_command=mode is OperatingMode.EMERGENCY_OFF,
            )
            dispatched = True
        deadlines = [
            deadline
            for deadline in (
                assessment.next_reevaluation_at,
                self.source_control_state.next_reevaluation_deadline,
            )
            if deadline is not None
        ]
        return FailsafeEvaluation(
            mode=mode,
            desired_action=action,
            dispatched=dispatched,
            next_evaluation_at=min(deadlines) if deadlines else None,
            source_control_state=self.source_control_state,
        )
