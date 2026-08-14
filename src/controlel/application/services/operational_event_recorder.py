"""Transition-aware application recorder for semantic operational events."""

from collections.abc import Mapping
from datetime import datetime

from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationResult,
    HeatDemandEvaluationStatus,
)
from controlel.application.services.heat_demand_safety_policy import HeatDemandSafetyPhase
from controlel.application.services.operational_event_stream import OperationalEventStream
from controlel.application.services.source_control_policy import SourceControlOutcome
from controlel.application.services.zone_heat_demand_confirmation_policy import (
    ZoneHeatDemandConfirmationAssessment,
)
from controlel.application.state.runtime_supervision_state import RuntimeSupervisionState
from controlel.application.state.source_reconciliation_state import SourceReconciliationStatus
from controlel.application.state.zone_heat_demand_confirmation_state import ZoneHeatDemandConfirmationPhase
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.operational_events import (
    MeasurementEventCondition,
)
from controlel.domain.operational_events import (
    OperationalEventCategory as Category,
)
from controlel.domain.operational_events import (
    OperationalEventCode as Code,
)
from controlel.domain.operational_events import (
    OperationalEventSeverity as Severity,
)
from controlel.domain.runtime_supervision import CommandAuthority, SupervisorPhase
from controlel.domain.source_control import ReportedSourceEvidence, ReportedSourceState
from controlel.domain.value_objects.zone_id import ZoneId


class OperationalEventRecorder:
    """Emit only meaningful transitions from already-computed application state."""

    def __init__(self, stream: OperationalEventStream | None = None) -> None:
        self.stream = stream or OperationalEventStream()
        self._measurement: MeasurementEventCondition | None = None
        self._measurement_activity_id: str | None = None
        self._zone_confirmation: dict[str, ZoneHeatDemandConfirmationPhase] = {}
        self._zone_demand: dict[str, BuildingHeatDemandStatus] = {}
        self._demand_correlation: dict[str, str] = {}
        self._safety_phase: HeatDemandSafetyPhase | None = None
        self._reported_source: ReportedSourceState | None = None
        self._reconciliation_status: SourceReconciliationStatus | None = None
        self._reconciliation_activity_id: str | None = None
        self._building_activity_id: str | None = None
        self._building_permission_enabled = False
        self._active_deferred: tuple[str, datetime | None] | None = None
        self._supervision_state: RuntimeSupervisionState | None = None
        self._runtime_fatal_active = False

    def runtime_started(self, timestamp: datetime) -> None:
        self._emit(timestamp, Category.RUNTIME, Severity.INFO, Code.RUNTIME_STARTED)

    def runtime_stopped(self, timestamp: datetime) -> None:
        self._emit(timestamp, Category.RUNTIME, Severity.INFO, Code.RUNTIME_STOPPED)

    def runtime_fatal(
        self,
        timestamp: datetime,
        reason_code: str,
        *,
        correlation_id: str | None = None,
    ) -> None:
        if self._runtime_fatal_active:
            return
        self._runtime_fatal_active = True
        self._emit(
            timestamp,
            Category.RUNTIME,
            Severity.CRITICAL,
            Code.RUNTIME_FATAL,
            reason_code=reason_code,
            correlation_id=correlation_id,
            activity_id=correlation_id,
        )

    def measurement(self, condition: MeasurementEventCondition, timestamp: datetime) -> None:
        previous = self._measurement
        if condition is previous:
            return
        self._measurement = condition
        if condition is MeasurementEventCondition.VALID:
            code = (
                Code.MEASUREMENT_RECOVERED
                if previous
                in {
                    MeasurementEventCondition.STALE,
                    MeasurementEventCondition.UNAVAILABLE,
                }
                else Code.MEASUREMENT_BECAME_VALID
            )
            severity = Severity.NOTICE if code is Code.MEASUREMENT_RECOVERED else Severity.INFO
        elif condition is MeasurementEventCondition.STALE:
            code, severity = Code.MEASUREMENT_BECAME_STALE, Severity.WARNING
        else:
            code, severity = Code.MEASUREMENT_BECAME_UNAVAILABLE, Severity.WARNING
        if code in {Code.MEASUREMENT_BECAME_STALE, Code.MEASUREMENT_BECAME_UNAVAILABLE}:
            self._measurement_activity_id = self._measurement_activity_id or self.stream.next_correlation_id(
                "measurement-incident"
            )
        self._emit(
            timestamp,
            Category.MEASUREMENT,
            severity,
            code,
            activity_id=self._measurement_activity_id,
            previous_state=previous.value if previous else None,
            new_state=condition.value,
        )
        if code is Code.MEASUREMENT_RECOVERED:
            self._measurement_activity_id = None

    def reported_source(self, evidence: ReportedSourceEvidence, *, source_id: str | None = None) -> None:
        previous = self._reported_source
        current = evidence.state
        self._reported_source = current
        if previous is None or previous is current:
            return
        self._emit(
            evidence.observed_at,
            Category.SOURCE_RESILIENCE,
            Severity.NOTICE,
            Code.REPORTED_SOURCE_STATE_CHANGED,
            source_id=source_id,
            activity_id=self._reconciliation_activity_id,
            previous_state=previous.value,
            new_state=current.value,
            details=(("transition_history", evidence.transition_history.value),),
        )

    def evaluation(
        self,
        result: HeatDemandEvaluationResult,
        *,
        confirmation_assessments: Mapping[ZoneId, ZoneHeatDemandConfirmationAssessment] | None = None,
    ) -> None:
        timestamp = result.building_heat_demand.evaluated_at
        if (
            result.building_heat_demand.status is BuildingHeatDemandStatus.HEAT_REQUIRED
            and self._building_activity_id is None
        ):
            self._building_activity_id = self.stream.next_correlation_id("heating-episode")
        self._record_demand(result, timestamp, confirmation_assessments)
        self._record_safety(result, timestamp)
        self._record_reconciliation(result, timestamp)
        self._record_command(result, timestamp)
        if result.status is HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED and result.command is not None:
            if result.command.action is HeatingAction.ENABLE_HEATING:
                self._building_permission_enabled = True
            else:
                self._building_permission_enabled = False
                self._building_activity_id = None
        elif (
            result.building_heat_demand.status is BuildingHeatDemandStatus.NO_HEAT_REQUIRED
            and not self._building_permission_enabled
        ):
            self._building_activity_id = None

    def command_requested(
        self,
        action: HeatingAction,
        timestamp: datetime,
        *,
        correlation_id: str | None = None,
        activity_id: str | None = None,
    ) -> str:
        """Record one actual source-call attempt and return its correlation."""

        correlation = correlation_id or self.stream.next_correlation_id("source-command")
        requested_code = (
            Code.SOURCE_ENABLE_REQUESTED if action is HeatingAction.ENABLE_HEATING else Code.SOURCE_DISABLE_REQUESTED
        )
        self._emit(
            timestamp,
            Category.SOURCE_CONTROL,
            Severity.INFO,
            requested_code,
            correlation_id=correlation,
            activity_id=activity_id,
            requested_command=action.value,
            command_outcome="requested",
        )
        return correlation

    def command_dispatched(
        self,
        action: HeatingAction,
        timestamp: datetime,
        *,
        correlation_id: str,
        activity_id: str | None = None,
    ) -> None:
        """Record successful adapter dispatch without claiming reported state."""

        self._emit(
            timestamp,
            Category.SOURCE_CONTROL,
            Severity.NOTICE,
            Code.SOURCE_COMMAND_DISPATCHED,
            correlation_id=correlation_id,
            activity_id=activity_id,
            requested_command=action.value,
            command_outcome="dispatched",
        )

    def command_failed(
        self,
        action: HeatingAction,
        timestamp: datetime,
        *,
        reason_code: str,
        correlation_id: str | None = None,
        corrective_reconciliation: bool = False,
        activity_id: str | None = None,
    ) -> None:
        if corrective_reconciliation:
            self._reconciliation_activity_id = self._reconciliation_activity_id or self.stream.next_correlation_id(
                "source-reconciliation"
            )
            activity_id = self._reconciliation_activity_id
        elif activity_id is None:
            activity_id = self.stream.next_correlation_id("source-command-incident")
        correlation = correlation_id or self.command_requested(action, timestamp, activity_id=activity_id)
        self._emit(
            timestamp,
            Category.SOURCE_CONTROL,
            Severity.WARNING,
            Code.SOURCE_COMMAND_FAILED,
            reason_code=reason_code,
            correlation_id=correlation,
            activity_id=activity_id,
            requested_command=action.value,
            command_outcome="failed",
        )

    def emergency_disable_requested(self, timestamp: datetime) -> None:
        """Record safety intent without claiming dispatch or physical state."""

        self._emit(
            timestamp,
            Category.SAFETY,
            Severity.CRITICAL,
            Code.EMERGENCY_DISABLE_REQUESTED,
            requested_command=HeatingAction.DISABLE_HEATING.value,
            command_outcome="requested",
        )

    def supervision(self, state: RuntimeSupervisionState, timestamp: datetime) -> None:
        previous = self._supervision_state
        self._supervision_state = state
        if previous is None:
            return
        correlation = f"supervision:{state.normal_generation:08d}"
        if previous.command_authority is not state.command_authority:
            self._emit(
                timestamp,
                Category.SUPERVISION,
                Severity.WARNING if state.command_authority is CommandAuthority.FAILSAFE else Severity.NOTICE,
                Code.COMMAND_AUTHORITY_CHANGED,
                correlation_id=correlation,
                activity_id=correlation,
                previous_state=previous.command_authority.value,
                new_state=state.command_authority.value,
            )
        if previous.phase is not state.phase:
            if state.phase is SupervisorPhase.FAILSAFE:
                self._emit(
                    timestamp,
                    Category.SUPERVISION,
                    Severity.CRITICAL,
                    Code.FAILSAFE_ENTERED,
                    correlation_id=correlation,
                    activity_id=correlation,
                )
            elif previous.phase is not SupervisorPhase.NORMAL and state.phase is SupervisorPhase.NORMAL:
                self._emit(
                    timestamp,
                    Category.SUPERVISION,
                    Severity.NOTICE,
                    Code.FAILSAFE_EXITED,
                    correlation_id=correlation,
                    activity_id=correlation,
                )
                self._emit(
                    timestamp,
                    Category.RUNTIME,
                    Severity.NOTICE,
                    Code.RUNTIME_RECOVERED,
                    correlation_id=correlation,
                    activity_id=correlation,
                )
                self._runtime_fatal_active = False
        if not previous.restart_budget_exhausted and state.restart_budget_exhausted:
            self._emit(
                timestamp,
                Category.SUPERVISION,
                Severity.CRITICAL,
                Code.RESTART_BUDGET_EXHAUSTED,
                correlation_id=correlation,
                activity_id=correlation,
                details=(("attempts", state.restart_attempt_count),),
            )

    def restart_attempt_started(self, timestamp: datetime, *, attempt: int, budget: int, generation: int) -> None:
        self._emit(
            timestamp,
            Category.SUPERVISION,
            Severity.NOTICE,
            Code.RESTART_ATTEMPT_STARTED,
            correlation_id=f"supervision:{generation:08d}",
            activity_id=f"supervision:{generation:08d}",
            details=(("attempt", attempt), ("budget", budget)),
        )

    def restart_attempt_failed(self, timestamp: datetime, *, attempt: int, reason_code: str, generation: int) -> None:
        self._emit(
            timestamp,
            Category.SUPERVISION,
            Severity.WARNING,
            Code.RESTART_ATTEMPT_FAILED,
            reason_code=reason_code,
            correlation_id=f"supervision:{generation:08d}",
            activity_id=f"supervision:{generation:08d}",
            details=(("attempt", attempt),),
        )

    def _record_demand(
        self,
        result: HeatDemandEvaluationResult,
        timestamp: datetime,
        confirmation_assessments: Mapping[ZoneId, ZoneHeatDemandConfirmationAssessment] | None,
    ) -> None:
        for zone_input in result.building_heat_demand.zone_inputs:
            zone_id = zone_input.zone_id.value
            current = zone_input.demand
            previous = self._zone_demand.get(zone_id)
            zone_assessment = (
                confirmation_assessments.get(zone_input.zone_id)
                if confirmation_assessments is not None
                else result.confirmation_assessment
            )
            phase = (
                zone_assessment.state.phase
                if zone_assessment is not None and zone_assessment.state.last_evaluated_at == timestamp
                else None
            )
            previous_phase = self._zone_confirmation.get(zone_id)
            if phase is not None:
                self._zone_confirmation[zone_id] = phase
            if phase is ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING and previous_phase is not phase:
                correlation = self.stream.next_correlation_id(f"demand:{zone_id}")
                self._demand_correlation[zone_id] = correlation
                self._emit(
                    timestamp,
                    Category.DEMAND,
                    Severity.INFO,
                    Code.HEAT_DEMAND_STARTED,
                    zone_id=zone_id,
                    correlation_id=correlation,
                    activity_id=self._building_activity_id,
                    reason_code=result.building_heat_demand.reason.value,
                )
            if phase is ZoneHeatDemandConfirmationPhase.HEAT_REQUIRED_CONFIRMED and previous_phase is not phase:
                correlation = self._demand_correlation.setdefault(
                    zone_id,
                    self.stream.next_correlation_id(f"demand:{zone_id}"),
                )
                if previous_phase is not ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING:
                    self._emit(
                        timestamp,
                        Category.DEMAND,
                        Severity.INFO,
                        Code.HEAT_DEMAND_STARTED,
                        zone_id=zone_id,
                        correlation_id=correlation,
                        activity_id=self._building_activity_id,
                        reason_code=result.building_heat_demand.reason.value,
                    )
                self._emit(
                    timestamp,
                    Category.DEMAND,
                    Severity.NOTICE,
                    Code.HEAT_DEMAND_CONFIRMED,
                    zone_id=zone_id,
                    correlation_id=correlation,
                    activity_id=self._building_activity_id,
                    reason_code=result.building_heat_demand.reason.value,
                )
            if previous_phase is ZoneHeatDemandConfirmationPhase.CONFIRMATION_PENDING and phase in {
                ZoneHeatDemandConfirmationPhase.NO_HEAT_REQUIRED,
                ZoneHeatDemandConfirmationPhase.INDETERMINATE,
            }:
                self._emit(
                    timestamp,
                    Category.DEMAND,
                    Severity.INFO,
                    Code.HEAT_DEMAND_CANCELLED,
                    zone_id=zone_id,
                    correlation_id=self._demand_correlation.pop(zone_id, None),
                    activity_id=self._building_activity_id,
                    reason_code=result.building_heat_demand.reason.value,
                    details=(
                        (
                            "building_episode_cancelled",
                            result.building_heat_demand.status is BuildingHeatDemandStatus.NO_HEAT_REQUIRED,
                        ),
                    ),
                )
            if (
                previous is BuildingHeatDemandStatus.HEAT_REQUIRED
                and current is BuildingHeatDemandStatus.NO_HEAT_REQUIRED
            ):
                self._emit(
                    timestamp,
                    Category.DEMAND,
                    Severity.INFO,
                    Code.HEAT_DEMAND_SATISFIED,
                    zone_id=zone_id,
                    correlation_id=self._demand_correlation.pop(zone_id, None),
                    activity_id=self._building_activity_id,
                    reason_code=result.building_heat_demand.reason.value,
                )
            self._zone_demand[zone_id] = current

    def _record_safety(self, result: HeatDemandEvaluationResult, timestamp: datetime) -> None:
        phase = result.safety_assessment.phase
        previous = self._safety_phase
        self._safety_phase = phase
        if phase is previous:
            return
        if phase is HeatDemandSafetyPhase.INDETERMINATE_GRACE:
            self._emit(
                timestamp,
                Category.SAFETY,
                Severity.WARNING,
                Code.SAFETY_GRACE_STARTED,
                activity_id=self._measurement_activity_id,
            )
        elif phase is HeatDemandSafetyPhase.INDETERMINATE_TIMED_OUT:
            self._emit(
                timestamp,
                Category.SAFETY,
                Severity.WARNING,
                Code.SAFETY_GRACE_EXPIRED,
                activity_id=self._measurement_activity_id,
            )
            if result.safety_assessment.action is HeatingAction.DISABLE_HEATING:
                self._emit(
                    timestamp,
                    Category.SAFETY,
                    Severity.WARNING,
                    Code.SAFETY_DISABLE_REQUESTED,
                    activity_id=self._measurement_activity_id,
                    requested_command=HeatingAction.DISABLE_HEATING.value,
                    command_outcome="requested",
                )

    def _record_reconciliation(self, result: HeatDemandEvaluationResult, timestamp: datetime) -> None:
        assessment = result.source_reconciliation_assessment
        if assessment is None:
            return
        status = assessment.status
        previous = self._reconciliation_status
        self._reconciliation_status = status
        drift_states = {
            SourceReconciliationStatus.DRIFT_HOLDING,
            SourceReconciliationStatus.CORRECTION_REQUIRED,
            SourceReconciliationStatus.CORRECTION_PENDING,
        }
        if status in drift_states and previous not in drift_states:
            self._reconciliation_activity_id = self._reconciliation_activity_id or self.stream.next_correlation_id(
                "source-reconciliation"
            )
            self._emit(
                timestamp,
                Category.SOURCE_RESILIENCE,
                Severity.WARNING,
                Code.SOURCE_DRIFT_DETECTED,
                activity_id=self._reconciliation_activity_id,
                reason_code=assessment.reason.value,
                details=(
                    (
                        "desired_state",
                        assessment.state.desired_command.value
                        if assessment.state.desired_command is not None
                        else None,
                    ),
                    (
                        "reported_state",
                        assessment.state.reported.state.value if assessment.state.reported is not None else None,
                    ),
                ),
            )
        if status is SourceReconciliationStatus.CORRECTION_REQUIRED and previous is not status:
            self._emit(
                timestamp,
                Category.SOURCE_RESILIENCE,
                Severity.NOTICE,
                Code.SOURCE_RECONCILIATION_STARTED,
                activity_id=self._reconciliation_activity_id,
                reason_code=assessment.reason.value,
            )
        if previous in drift_states and status not in drift_states:
            completion_outcome = "reported_agreement" if status is SourceReconciliationStatus.AGREED else status.value
            self._emit(
                timestamp,
                Category.SOURCE_RESILIENCE,
                Severity.NOTICE,
                Code.SOURCE_RECONCILIATION_COMPLETED,
                activity_id=self._reconciliation_activity_id,
                reason_code=assessment.reason.value,
                details=(("completion_outcome", completion_outcome),),
            )
            self._reconciliation_activity_id = None
        if result.status is HeatDemandEvaluationStatus.RESILIENCE_COMMAND_HELD and previous is not status:
            self._emit(
                timestamp,
                Category.SOURCE_RESILIENCE,
                Severity.WARNING,
                Code.CORRECTIVE_ACTION_HELD,
                activity_id=self._reconciliation_activity_id,
            )

    def _record_command(self, result: HeatDemandEvaluationResult, timestamp: datetime) -> None:
        assessment = result.source_control_assessment
        if assessment is None or result.command is None:
            self._active_deferred = None
            return
        action = result.command.action
        activity_id = self._activity_id_for_result(result)
        if assessment.outcome is SourceControlOutcome.DEFER:
            deferred = (action.value, assessment.lockout_deadline)
            if deferred == self._active_deferred:
                return
            self._active_deferred = deferred
            code = (
                Code.SOURCE_COMMAND_DEFERRED_MINIMUM_ON
                if action is HeatingAction.DISABLE_HEATING
                else Code.SOURCE_COMMAND_DEFERRED_MINIMUM_OFF
            )
            self._emit(
                timestamp,
                Category.SOURCE_CONTROL,
                Severity.NOTICE,
                code,
                activity_id=activity_id,
                reason_code=assessment.reason.value,
                requested_command=action.value,
                command_outcome="deferred",
                details=(
                    ("deadline", assessment.lockout_deadline.isoformat() if assessment.lockout_deadline else None),
                ),
            )
            return
        self._active_deferred = None
        if assessment.outcome is not SourceControlOutcome.DISPATCH:
            return
        if result.status not in {
            HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED,
            HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED,
            HeatDemandEvaluationStatus.RESILIENCE_COMMAND_EXECUTED,
        }:
            return
        correlation = self._command_correlation(action, result=result)
        self.command_requested(action, timestamp, correlation_id=correlation, activity_id=activity_id)
        self.command_dispatched(action, timestamp, correlation_id=correlation, activity_id=activity_id)
        if result.status is HeatDemandEvaluationStatus.RESILIENCE_COMMAND_EXECUTED:
            self._emit(
                timestamp,
                Category.SOURCE_RESILIENCE,
                Severity.NOTICE,
                Code.CORRECTIVE_ACTION_DISPATCHED,
                correlation_id=correlation,
                activity_id=activity_id,
                requested_command=action.value,
                command_outcome="dispatched",
            )

    def _activity_id_for_result(self, result: HeatDemandEvaluationResult) -> str | None:
        if result.status in {
            HeatDemandEvaluationStatus.RESILIENCE_COMMAND_EXECUTED,
            HeatDemandEvaluationStatus.RESILIENCE_COMMAND_DEFERRED,
            HeatDemandEvaluationStatus.RESILIENCE_COMMAND_HELD,
        }:
            return self._reconciliation_activity_id
        if result.status in {
            HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED,
            HeatDemandEvaluationStatus.SAFETY_COMMAND_DEFERRED,
        }:
            return self._measurement_activity_id
        return self._building_activity_id

    def _command_correlation(
        self,
        action: HeatingAction,
        *,
        result: HeatDemandEvaluationResult | None = None,
    ) -> str:
        correlation = None
        if (
            action is HeatingAction.ENABLE_HEATING
            and result is not None
            and len(result.building_heat_demand.contributing_heat_zone_ids) == 1
        ):
            zone_id = result.building_heat_demand.contributing_heat_zone_ids[0].value
            correlation = self._demand_correlation.get(zone_id)
        if correlation is None:
            correlation = self.stream.next_correlation_id("source-command")
        return correlation

    def _emit(
        self,
        timestamp: datetime,
        category: Category,
        severity: Severity,
        code: Code,
        **kwargs: object,
    ) -> None:
        self.stream.emit(timestamp=timestamp, category=category, severity=severity, event_code=code, **kwargs)
