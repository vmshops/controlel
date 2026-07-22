from dataclasses import dataclass
from enum import StrEnum

from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand import BuildingHeatDemand
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.events.decision_event import DecisionCreatedEvent


class RuntimeProcessingStatus(StrEnum):
    NO_DECISION = "no_decision"
    DECISION_WITHOUT_COMMAND = "decision_without_command"
    BUILDING_HEAT_DEMAND_INDETERMINATE = "building_heat_demand_indeterminate"
    COMMAND_EXECUTED = "command_executed"
    COMMAND_SUPPRESSED = "command_suppressed"


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
    building_heat_demand: BuildingHeatDemand | None = None
    command: HeatSourceCommand | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeProcessingStatus):
            raise TypeError("status must be a RuntimeProcessingStatus")
        if self.reason is not None and not isinstance(self.reason, TemperatureNoDecisionReason):
            raise TypeError("reason must be a TemperatureNoDecisionReason or None")
        if self.decision_event is not None and not isinstance(self.decision_event, DecisionCreatedEvent):
            raise TypeError("decision_event must be a DecisionCreatedEvent or None")
        if self.building_heat_demand is not None and not isinstance(
            self.building_heat_demand,
            BuildingHeatDemand,
        ):
            raise TypeError("building_heat_demand must be a BuildingHeatDemand or None")
        if self.command is not None and not isinstance(self.command, HeatSourceCommand):
            raise TypeError("command must be a HeatSourceCommand or None")

        if self.status is RuntimeProcessingStatus.NO_DECISION:
            if (
                self.reason is None
                or self.decision_event is not None
                or self.building_heat_demand is not None
                or self.command is not None
            ):
                raise ValueError("NO_DECISION requires only a reason")
            return

        if self.status is RuntimeProcessingStatus.DECISION_WITHOUT_COMMAND:
            if (
                self.reason is not None
                or self.decision_event is None
                or self.building_heat_demand is not None
                or self.command is not None
            ):
                raise ValueError("DECISION_WITHOUT_COMMAND requires only a decision_event")
            return

        if self.status is RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE:
            if (
                self.reason is not None
                or self.decision_event is None
                or self.building_heat_demand is None
                or self.building_heat_demand.status is not BuildingHeatDemandStatus.INDETERMINATE
                or self.command is not None
            ):
                raise ValueError(
                    "BUILDING_HEAT_DEMAND_INDETERMINATE requires a decision_event "
                    "and indeterminate building_heat_demand without a command"
                )
            return

        command_statuses = {
            RuntimeProcessingStatus.COMMAND_EXECUTED,
            RuntimeProcessingStatus.COMMAND_SUPPRESSED,
        }
        if self.status not in command_statuses:
            raise ValueError(f"Unhandled RuntimeProcessingStatus: {self.status!r}")

        if (
            self.reason is not None
            or self.decision_event is None
            or self.building_heat_demand is None
            or self.command is None
        ):
            raise ValueError(
                f"{self.status.name} requires a decision_event, building_heat_demand and command without a reason"
            )

        action_by_status = {
            BuildingHeatDemandStatus.HEAT_REQUIRED: HeatingAction.ENABLE_HEATING,
            BuildingHeatDemandStatus.NO_HEAT_REQUIRED: HeatingAction.DISABLE_HEATING,
        }
        try:
            expected_action = action_by_status[self.building_heat_demand.status]
        except KeyError:
            raise ValueError(f"{self.status.name} requires a determinate building_heat_demand") from None

        if self.command.action is not expected_action:
            raise ValueError(f"{self.building_heat_demand.status.name} requires command action {expected_action.value}")
