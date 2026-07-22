from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingResult,
    RuntimeProcessingStatus,
    TemperatureNoDecisionReason,
)
from controlel.domain.commands.command import Command
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.decisions.decision import Decision
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.demands.building_heat_demand import BuildingHeatDemand
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def create_decision_event() -> DecisionCreatedEvent:
    return DecisionCreatedEvent(
        decision=Decision(
            sensor_id=SensorId(value="living_room_temperature"),
            zone_id=ZoneId(value="living_room"),
            observed_at=NOW,
            action=DecisionAction.ENABLE_HEATING,
        )
    )


def create_demand(
    status: BuildingHeatDemandStatus,
) -> BuildingHeatDemand:
    return BuildingHeatDemand(
        status=status,
        evaluated_at=NOW,
        eligible_demands=(),
        missing_zone_ids=(),
        expired_zone_ids=(),
        future_dated_zone_ids=(),
    )


def create_command(
    action: HeatingAction = HeatingAction.ENABLE_HEATING,
) -> HeatSourceCommand:
    return HeatSourceCommand(
        command_type=CommandFamily.HEATING,
        action=action,
    )


def test_runtime_processing_status_has_stable_string_values():
    assert {status.name: status.value for status in RuntimeProcessingStatus} == {
        "NO_DECISION": "no_decision",
        "DECISION_WITHOUT_COMMAND": "decision_without_command",
        "BUILDING_HEAT_DEMAND_INDETERMINATE": "building_heat_demand_indeterminate",
        "COMMAND_EXECUTED": "command_executed",
        "COMMAND_SUPPRESSED": "command_suppressed",
    }
    assert all(isinstance(status, str) for status in RuntimeProcessingStatus)


def test_temperature_no_decision_reason_has_stable_string_values():
    assert {reason.name: reason.value for reason in TemperatureNoDecisionReason} == {
        "TIMESTAMP_ADMISSION_REJECTED": "timestamp_admission_rejected",
        "OUT_OF_ORDER": "out_of_order",
        "SECONDARY_MEASUREMENT": "secondary_measurement",
        "PRIMARY_MEASUREMENT_MISSING": "primary_measurement_missing",
        "PRIMARY_MEASUREMENT_EXPIRED": "primary_measurement_expired",
        "PRIMARY_MEASUREMENT_FUTURE_DATED": "primary_measurement_future_dated",
    }


def test_runtime_processing_result_is_immutable():
    result = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.NO_DECISION,
        reason=TemperatureNoDecisionReason.OUT_OF_ORDER,
    )

    with pytest.raises(FrozenInstanceError):
        result.reason = TemperatureNoDecisionReason.SECONDARY_MEASUREMENT


def test_accepts_every_valid_status_combination():
    decision_event = create_decision_event()
    indeterminate = create_demand(BuildingHeatDemandStatus.INDETERMINATE)
    requires_heat = create_demand(BuildingHeatDemandStatus.HEAT_REQUIRED)
    command = create_command()

    no_decision = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.NO_DECISION,
        reason=TemperatureNoDecisionReason.OUT_OF_ORDER,
    )
    without_command = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.DECISION_WITHOUT_COMMAND,
        decision_event=decision_event,
    )
    indeterminate_result = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE,
        decision_event=decision_event,
        building_heat_demand=indeterminate,
    )
    executed = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.COMMAND_EXECUTED,
        decision_event=decision_event,
        building_heat_demand=requires_heat,
        command=command,
    )
    suppressed = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.COMMAND_SUPPRESSED,
        decision_event=decision_event,
        building_heat_demand=requires_heat,
        command=command,
    )

    assert no_decision.reason is TemperatureNoDecisionReason.OUT_OF_ORDER
    assert without_command.decision_event is decision_event
    assert indeterminate_result.building_heat_demand is indeterminate
    assert executed.command is command
    assert suppressed.command is command


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"decision_event": create_decision_event()},
        {"command": create_command()},
        {"building_heat_demand": create_demand(BuildingHeatDemandStatus.INDETERMINATE)},
    ],
)
def test_no_decision_rejects_invalid_field_combinations(fields):
    with pytest.raises(ValueError, match="NO_DECISION requires only a reason"):
        RuntimeProcessingResult(status=RuntimeProcessingStatus.NO_DECISION, **fields)


def test_indeterminate_requires_exact_indeterminate_combination():
    with pytest.raises(
        ValueError,
        match="BUILDING_HEAT_DEMAND_INDETERMINATE requires",
    ):
        RuntimeProcessingResult(
            status=RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE,
            decision_event=create_decision_event(),
            building_heat_demand=create_demand(BuildingHeatDemandStatus.HEAT_REQUIRED),
        )

    with pytest.raises(ValueError, match="BUILDING_HEAT_DEMAND_INDETERMINATE requires"):
        RuntimeProcessingResult(
            status=RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE,
            decision_event=create_decision_event(),
            building_heat_demand=create_demand(BuildingHeatDemandStatus.INDETERMINATE),
            command=create_command(),
        )


@pytest.mark.parametrize(
    "status",
    [RuntimeProcessingStatus.COMMAND_EXECUTED, RuntimeProcessingStatus.COMMAND_SUPPRESSED],
)
def test_command_statuses_require_determinate_aggregate_and_heat_source_command(status):
    with pytest.raises(ValueError, match="requires a decision_event"):
        RuntimeProcessingResult(
            status=status,
            decision_event=create_decision_event(),
            command=create_command(),
        )

    with pytest.raises(ValueError, match="requires a determinate"):
        RuntimeProcessingResult(
            status=status,
            decision_event=create_decision_event(),
            building_heat_demand=create_demand(BuildingHeatDemandStatus.INDETERMINATE),
            command=create_command(),
        )

    with pytest.raises(TypeError, match="HeatSourceCommand"):
        RuntimeProcessingResult(
            status=status,
            decision_event=create_decision_event(),
            building_heat_demand=create_demand(BuildingHeatDemandStatus.HEAT_REQUIRED),
            command=Command(
                zone_id=ZoneId(value="living_room"),
                command_type=CommandFamily.HEATING,
                action=HeatingAction.ENABLE_HEATING,
            ),
        )


@pytest.mark.parametrize(
    ("demand_status", "action"),
    [
        (BuildingHeatDemandStatus.HEAT_REQUIRED, HeatingAction.DISABLE_HEATING),
        (BuildingHeatDemandStatus.NO_HEAT_REQUIRED, HeatingAction.ENABLE_HEATING),
    ],
)
def test_command_status_rejects_aggregate_action_mismatch(demand_status, action):
    with pytest.raises(ValueError, match="requires command action"):
        RuntimeProcessingResult(
            status=RuntimeProcessingStatus.COMMAND_EXECUTED,
            decision_event=create_decision_event(),
            building_heat_demand=create_demand(demand_status),
            command=create_command(action),
        )
