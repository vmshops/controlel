"""Production-neutral startup ordering for one ordinary control runtime."""

from dataclasses import dataclass

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.heat_demand_evaluation_result import HeatDemandEvaluationResult
from controlel.application.runtime.runtime_processing_result import RuntimeProcessingResult
from controlel.application.state.source_recovery_state import SourceRecoveryState
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.operational_events import MeasurementEventCondition
from controlel.domain.source_control import ReportedSourceEvidence


@dataclass(frozen=True, slots=True)
class ControlRuntimeStartup:
    """Apply initial normalized evidence through one shared recovery lifecycle.

    Outer adapters call these methods in order. Runtime start is recorded before
    recovery begins; reported-source evidence is admitted before temperature
    evidence performs the first normal demand evaluation.
    """

    runtime: ControlRuntime

    def begin(self) -> SourceRecoveryState:
        self.runtime.record_runtime_started()
        return self.runtime.begin_source_recovery()

    def ingest_reported_source(self, evidence: ReportedSourceEvidence) -> HeatDemandEvaluationResult:
        return self.runtime.ingest_reported_source_state(evidence)

    def ingest_temperature(self, measurement: Measurement) -> RuntimeProcessingResult:
        return self.runtime.process_temperature(measurement)

    def mark_measurement_indeterminate(
        self,
        condition: MeasurementEventCondition,
    ) -> HeatDemandEvaluationResult:
        return self.runtime.mark_measurement_indeterminate(condition)
