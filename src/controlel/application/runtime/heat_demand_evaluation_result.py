from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from controlel.application.services.heat_demand_safety_policy import (
    HeatDemandSafetyAssessment,
    HeatDemandSafetyPhase,
)
from controlel.application.services.source_control_policy import (
    SourceControlAssessment,
)
from controlel.application.services.temperature_hysteresis_policy import (
    TemperatureHysteresisAssessment,
)
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand import BuildingHeatDemand
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)


class HeatDemandEvaluationTrigger(StrEnum):
    STARTUP = "startup"
    ACTIONABLE_DECISION = "actionable_decision"
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class HeatDemandEvaluationStatus(StrEnum):
    INDETERMINATE_GRACE = "indeterminate_grace"
    DEMAND_COMMAND_EXECUTED = "demand_command_executed"
    DEMAND_COMMAND_SUPPRESSED = "demand_command_suppressed"
    SAFETY_COMMAND_EXECUTED = "safety_command_executed"
    SAFETY_COMMAND_SUPPRESSED = "safety_command_suppressed"
    DEMAND_COMMAND_DEFERRED = "demand_command_deferred"
    SAFETY_COMMAND_DEFERRED = "safety_command_deferred"


@dataclass(frozen=True)
class HeatDemandEvaluationResult:
    trigger: HeatDemandEvaluationTrigger
    status: HeatDemandEvaluationStatus
    building_heat_demand: BuildingHeatDemand
    safety_assessment: HeatDemandSafetyAssessment
    command: HeatSourceCommand | None
    scheduled_for: datetime | None
    next_evaluation_at: datetime | None
    hysteresis_assessment: TemperatureHysteresisAssessment | None = None
    source_control_assessment: SourceControlAssessment | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, HeatDemandEvaluationTrigger):
            raise TypeError("trigger must be a HeatDemandEvaluationTrigger")
        if not isinstance(self.status, HeatDemandEvaluationStatus):
            raise TypeError("status must be a HeatDemandEvaluationStatus")
        if not isinstance(self.building_heat_demand, BuildingHeatDemand):
            raise TypeError("building_heat_demand must be a BuildingHeatDemand")
        if not isinstance(self.safety_assessment, HeatDemandSafetyAssessment):
            raise TypeError("safety_assessment must be a HeatDemandSafetyAssessment")
        if self.command is not None and not isinstance(self.command, HeatSourceCommand):
            raise TypeError("command must be a HeatSourceCommand or None")
        if self.hysteresis_assessment is not None and not isinstance(
            self.hysteresis_assessment,
            TemperatureHysteresisAssessment,
        ):
            raise TypeError("hysteresis_assessment must be a TemperatureHysteresisAssessment or None")
        if self.source_control_assessment is not None and not isinstance(
            self.source_control_assessment,
            SourceControlAssessment,
        ):
            raise TypeError("source_control_assessment must be a SourceControlAssessment or None")

        for field_name, value in (
            ("scheduled_for", self.scheduled_for),
            ("next_evaluation_at", self.next_evaluation_at),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} must be timezone-aware")

        if self.next_evaluation_at is not None and self.next_evaluation_at <= self.building_heat_demand.evaluated_at:
            raise ValueError("next_evaluation_at must be later than building_heat_demand.evaluated_at")
        if self.safety_assessment.state.last_evaluated_at != self.building_heat_demand.evaluated_at:
            raise ValueError("safety assessment and building demand evaluation times must match")

        if self.trigger is HeatDemandEvaluationTrigger.SCHEDULED:
            if self.scheduled_for is None:
                raise ValueError("SCHEDULED requires scheduled_for")
        elif self.scheduled_for is not None:
            raise ValueError(f"{self.trigger.name} requires scheduled_for=None")

        if self.status is HeatDemandEvaluationStatus.INDETERMINATE_GRACE:
            if (
                self.building_heat_demand.status is not BuildingHeatDemandStatus.INDETERMINATE
                or self.safety_assessment.phase is not HeatDemandSafetyPhase.INDETERMINATE_GRACE
                or self.command is not None
                or self.next_evaluation_at is None
            ):
                raise ValueError(
                    "INDETERMINATE_GRACE requires indeterminate demand, grace assessment, "
                    "no command, and a next evaluation"
                )
            return

        demand_statuses = {
            HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED,
            HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED,
            HeatDemandEvaluationStatus.DEMAND_COMMAND_DEFERRED,
        }
        if self.status in demand_statuses:
            action_by_status = {
                BuildingHeatDemandStatus.HEAT_REQUIRED: HeatingAction.ENABLE_HEATING,
                BuildingHeatDemandStatus.NO_HEAT_REQUIRED: HeatingAction.DISABLE_HEATING,
            }
            expected_action = action_by_status.get(self.building_heat_demand.status)
            if (
                expected_action is None
                or self.safety_assessment.phase is not HeatDemandSafetyPhase.DETERMINATE
                or self.command is None
                or self.command.action is not expected_action
            ):
                raise ValueError(f"{self.status.name} requires determinate demand and its matching command")
            return

        safety_statuses = {
            HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED,
            HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED,
            HeatDemandEvaluationStatus.SAFETY_COMMAND_DEFERRED,
        }
        if self.status in safety_statuses:
            if (
                self.building_heat_demand.status is not BuildingHeatDemandStatus.INDETERMINATE
                or self.safety_assessment.phase is not HeatDemandSafetyPhase.INDETERMINATE_TIMED_OUT
                or self.command is None
                or self.command.action is not self.safety_assessment.action
            ):
                raise ValueError(f"{self.status.name} requires timed-out indeterminate demand and its safety command")
            return

        raise ValueError(f"Unhandled HeatDemandEvaluationStatus: {self.status!r}")
