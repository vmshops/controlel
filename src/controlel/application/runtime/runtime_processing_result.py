from dataclasses import dataclass
from enum import StrEnum

from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationResult,
    HeatDemandEvaluationStatus,
    HeatDemandEvaluationTrigger,
)
from controlel.domain.events.decision_event import DecisionCreatedEvent


class RuntimeProcessingStatus(StrEnum):
    NO_DECISION = "no_decision"
    DECISION_WITHOUT_COMMAND = "decision_without_command"
    BUILDING_HEAT_DEMAND_INDETERMINATE = "building_heat_demand_indeterminate"
    COMMAND_EXECUTED = "command_executed"
    COMMAND_SUPPRESSED = "command_suppressed"
    SAFETY_COMMAND_EXECUTED = "safety_command_executed"
    SAFETY_COMMAND_SUPPRESSED = "safety_command_suppressed"
    COMMAND_DEFERRED = "command_deferred"
    SAFETY_COMMAND_DEFERRED = "safety_command_deferred"
    RESILIENCE_COMMAND_EXECUTED = "resilience_command_executed"
    RESILIENCE_COMMAND_SUPPRESSED = "resilience_command_suppressed"
    RESILIENCE_COMMAND_DEFERRED = "resilience_command_deferred"
    RESILIENCE_COMMAND_HELD = "resilience_command_held"
    RESILIENCE_INDETERMINATE = "resilience_indeterminate"


class TemperatureNoDecisionReason(StrEnum):
    TIMESTAMP_ADMISSION_REJECTED = "timestamp_admission_rejected"
    OUT_OF_ORDER = "out_of_order"
    SECONDARY_MEASUREMENT = "secondary_measurement"
    PRIMARY_MEASUREMENT_MISSING = "primary_measurement_missing"
    PRIMARY_MEASUREMENT_EXPIRED = "primary_measurement_expired"
    PRIMARY_MEASUREMENT_FUTURE_DATED = "primary_measurement_future_dated"


@dataclass(frozen=True)
class RuntimeProcessingResult:
    status: RuntimeProcessingStatus
    reason: TemperatureNoDecisionReason | None = None
    decision_event: DecisionCreatedEvent | None = None
    heat_demand_evaluation: HeatDemandEvaluationResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeProcessingStatus):
            raise TypeError("status must be a RuntimeProcessingStatus")
        if self.reason is not None and not isinstance(self.reason, TemperatureNoDecisionReason):
            raise TypeError("reason must be a TemperatureNoDecisionReason or None")
        if self.decision_event is not None and not isinstance(self.decision_event, DecisionCreatedEvent):
            raise TypeError("decision_event must be a DecisionCreatedEvent or None")
        if self.heat_demand_evaluation is not None and not isinstance(
            self.heat_demand_evaluation,
            HeatDemandEvaluationResult,
        ):
            raise TypeError("heat_demand_evaluation must be a HeatDemandEvaluationResult or None")

        if self.status is RuntimeProcessingStatus.NO_DECISION:
            if self.reason is None or self.decision_event is not None or self.heat_demand_evaluation is not None:
                raise ValueError("NO_DECISION requires only a reason")
            return

        if self.status is RuntimeProcessingStatus.DECISION_WITHOUT_COMMAND:
            if self.reason is not None or self.decision_event is None or self.heat_demand_evaluation is not None:
                raise ValueError("DECISION_WITHOUT_COMMAND requires only a decision_event")
            return

        expected_evaluation_status = {
            RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE: (
                HeatDemandEvaluationStatus.INDETERMINATE_GRACE
            ),
            RuntimeProcessingStatus.COMMAND_EXECUTED: HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED,
            RuntimeProcessingStatus.COMMAND_SUPPRESSED: HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED,
            RuntimeProcessingStatus.SAFETY_COMMAND_EXECUTED: HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED,
            RuntimeProcessingStatus.SAFETY_COMMAND_SUPPRESSED: HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED,
            RuntimeProcessingStatus.COMMAND_DEFERRED: HeatDemandEvaluationStatus.DEMAND_COMMAND_DEFERRED,
            RuntimeProcessingStatus.SAFETY_COMMAND_DEFERRED: HeatDemandEvaluationStatus.SAFETY_COMMAND_DEFERRED,
            RuntimeProcessingStatus.RESILIENCE_COMMAND_EXECUTED: (
                HeatDemandEvaluationStatus.RESILIENCE_COMMAND_EXECUTED
            ),
            RuntimeProcessingStatus.RESILIENCE_COMMAND_SUPPRESSED: (
                HeatDemandEvaluationStatus.RESILIENCE_COMMAND_SUPPRESSED
            ),
            RuntimeProcessingStatus.RESILIENCE_COMMAND_DEFERRED: (
                HeatDemandEvaluationStatus.RESILIENCE_COMMAND_DEFERRED
            ),
            RuntimeProcessingStatus.RESILIENCE_COMMAND_HELD: HeatDemandEvaluationStatus.RESILIENCE_COMMAND_HELD,
            RuntimeProcessingStatus.RESILIENCE_INDETERMINATE: (HeatDemandEvaluationStatus.RESILIENCE_INDETERMINATE),
        }.get(self.status)
        if expected_evaluation_status is None:
            raise ValueError(f"Unhandled RuntimeProcessingStatus: {self.status!r}")

        if (
            self.reason is not None
            or self.decision_event is None
            or self.heat_demand_evaluation is None
            or self.heat_demand_evaluation.trigger is not HeatDemandEvaluationTrigger.ACTIONABLE_DECISION
            or self.heat_demand_evaluation.status is not expected_evaluation_status
        ):
            raise ValueError(
                f"{self.status.name} requires a decision_event and matching actionable heat-demand evaluation"
            )
