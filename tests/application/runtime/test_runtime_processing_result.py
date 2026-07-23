from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationResult,
    HeatDemandEvaluationStatus,
    HeatDemandEvaluationTrigger,
)
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingResult,
    RuntimeProcessingStatus,
    TemperatureNoDecisionReason,
)
from controlel.application.services.heat_demand_safety_policy import (
    HeatDemandSafetyAssessment,
    HeatDemandSafetyPhase,
)
from controlel.application.state.heat_demand_safety_state import (
    HeatDemandSafetyState,
)
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


def decision_event() -> DecisionCreatedEvent:
    return DecisionCreatedEvent(
        decision=Decision(
            sensor_id=SensorId(value="living_room_temperature"),
            zone_id=ZoneId(value="living_room"),
            observed_at=NOW,
            action=DecisionAction.ENABLE_HEATING,
        )
    )


def evaluation(status: HeatDemandEvaluationStatus) -> HeatDemandEvaluationResult:
    if status is HeatDemandEvaluationStatus.INDETERMINATE_GRACE:
        demand_status = BuildingHeatDemandStatus.INDETERMINATE
        phase = HeatDemandSafetyPhase.INDETERMINATE_GRACE
        action = None
        timeout_at = NOW + timedelta(minutes=1)
        next_evaluation_at = timeout_at
    elif status in {
        HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED,
        HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED,
    }:
        demand_status = BuildingHeatDemandStatus.INDETERMINATE
        phase = HeatDemandSafetyPhase.INDETERMINATE_TIMED_OUT
        action = HeatingAction.DISABLE_HEATING
        timeout_at = NOW
        next_evaluation_at = None
    else:
        demand_status = BuildingHeatDemandStatus.HEAT_REQUIRED
        phase = HeatDemandSafetyPhase.DETERMINATE
        action = HeatingAction.ENABLE_HEATING
        timeout_at = None
        next_evaluation_at = NOW + timedelta(minutes=5)

    building_demand = BuildingHeatDemand(
        status=demand_status,
        evaluated_at=NOW,
        eligible_demands=(),
        missing_zone_ids=(),
        expired_zone_ids=(),
        future_dated_zone_ids=(),
    )
    safety = HeatDemandSafetyAssessment(
        state=HeatDemandSafetyState(
            indeterminate_since=None if phase is HeatDemandSafetyPhase.DETERMINATE else NOW,
            last_evaluated_at=NOW,
        ),
        phase=phase,
        timeout_at=timeout_at,
        action=action if phase is HeatDemandSafetyPhase.INDETERMINATE_TIMED_OUT else None,
    )
    command = HeatSourceCommand(command_type=CommandFamily.HEATING, action=action) if action is not None else None
    return HeatDemandEvaluationResult(
        trigger=HeatDemandEvaluationTrigger.ACTIONABLE_DECISION,
        status=status,
        building_heat_demand=building_demand,
        safety_assessment=safety,
        command=command,
        scheduled_for=None,
        next_evaluation_at=next_evaluation_at,
    )


def test_runtime_processing_status_has_stable_string_values():
    assert {status.name: status.value for status in RuntimeProcessingStatus} == {
        "NO_DECISION": "no_decision",
        "DECISION_WITHOUT_COMMAND": "decision_without_command",
        "BUILDING_HEAT_DEMAND_INDETERMINATE": "building_heat_demand_indeterminate",
        "COMMAND_EXECUTED": "command_executed",
        "COMMAND_SUPPRESSED": "command_suppressed",
        "SAFETY_COMMAND_EXECUTED": "safety_command_executed",
        "SAFETY_COMMAND_SUPPRESSED": "safety_command_suppressed",
    }


def test_temperature_no_decision_reason_values_remain_stable():
    assert [reason.value for reason in TemperatureNoDecisionReason] == [
        "timestamp_admission_rejected",
        "out_of_order",
        "secondary_measurement",
        "primary_measurement_missing",
        "primary_measurement_expired",
        "primary_measurement_future_dated",
    ]


def test_result_is_immutable_and_accepts_no_decision_and_observe_only():
    no_decision = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.NO_DECISION,
        reason=TemperatureNoDecisionReason.OUT_OF_ORDER,
    )
    observe = RuntimeProcessingResult(
        status=RuntimeProcessingStatus.DECISION_WITHOUT_COMMAND,
        decision_event=decision_event(),
    )

    assert observe.heat_demand_evaluation is None
    with pytest.raises(FrozenInstanceError):
        no_decision.reason = TemperatureNoDecisionReason.SECONDARY_MEASUREMENT


@pytest.mark.parametrize(
    ("runtime_status", "evaluation_status"),
    [
        (
            RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE,
            HeatDemandEvaluationStatus.INDETERMINATE_GRACE,
        ),
        (
            RuntimeProcessingStatus.COMMAND_EXECUTED,
            HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED,
        ),
        (
            RuntimeProcessingStatus.COMMAND_SUPPRESSED,
            HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED,
        ),
        (
            RuntimeProcessingStatus.SAFETY_COMMAND_EXECUTED,
            HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED,
        ),
        (
            RuntimeProcessingStatus.SAFETY_COMMAND_SUPPRESSED,
            HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED,
        ),
    ],
)
def test_actionable_statuses_require_exact_nested_evaluation(runtime_status, evaluation_status):
    nested = evaluation(evaluation_status)
    result = RuntimeProcessingResult(
        status=runtime_status,
        decision_event=decision_event(),
        heat_demand_evaluation=nested,
    )

    assert result.heat_demand_evaluation is nested


def test_runtime_status_rejects_wrong_nested_status_or_non_actionable_trigger():
    nested = evaluation(HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED)
    with pytest.raises(ValueError, match="matching actionable"):
        RuntimeProcessingResult(
            status=RuntimeProcessingStatus.COMMAND_EXECUTED,
            decision_event=decision_event(),
            heat_demand_evaluation=nested,
        )

    manual = HeatDemandEvaluationResult(
        trigger=HeatDemandEvaluationTrigger.MANUAL,
        status=nested.status,
        building_heat_demand=nested.building_heat_demand,
        safety_assessment=nested.safety_assessment,
        command=nested.command,
        scheduled_for=None,
        next_evaluation_at=nested.next_evaluation_at,
    )
    with pytest.raises(ValueError, match="matching actionable"):
        RuntimeProcessingResult(
            status=RuntimeProcessingStatus.COMMAND_SUPPRESSED,
            decision_event=decision_event(),
            heat_demand_evaluation=manual,
        )


def test_direct_building_demand_and_command_fields_are_removed():
    assert "building_heat_demand" not in RuntimeProcessingResult.__dataclass_fields__
    assert "command" not in RuntimeProcessingResult.__dataclass_fields__
