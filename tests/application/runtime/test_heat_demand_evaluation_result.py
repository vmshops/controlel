from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationResult,
    HeatDemandEvaluationStatus,
    HeatDemandEvaluationTrigger,
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
from controlel.domain.demands.building_heat_demand import BuildingHeatDemand
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)


def demand(
    status: BuildingHeatDemandStatus,
    evaluated_at: datetime = NOW,
) -> BuildingHeatDemand:
    return BuildingHeatDemand(
        status=status,
        evaluated_at=evaluated_at,
        eligible_demands=(),
        missing_zone_ids=(),
        expired_zone_ids=(),
        future_dated_zone_ids=(),
    )


def assessment(
    phase: HeatDemandSafetyPhase,
    evaluated_at: datetime = NOW,
    action: HeatingAction | None = None,
) -> HeatDemandSafetyAssessment:
    determinate = phase is HeatDemandSafetyPhase.DETERMINATE
    state = HeatDemandSafetyState(
        indeterminate_since=None if determinate else NOW,
        last_evaluated_at=evaluated_at,
    )
    return HeatDemandSafetyAssessment(
        state=state,
        phase=phase,
        timeout_at=None if determinate else LATER,
        action=action,
    )


def command(action: HeatingAction) -> HeatSourceCommand:
    return HeatSourceCommand(command_type=CommandFamily.HEATING, action=action)


def grace_result(**changes) -> HeatDemandEvaluationResult:
    fields = {
        "trigger": HeatDemandEvaluationTrigger.STARTUP,
        "status": HeatDemandEvaluationStatus.INDETERMINATE_GRACE,
        "building_heat_demand": demand(BuildingHeatDemandStatus.INDETERMINATE),
        "safety_assessment": assessment(HeatDemandSafetyPhase.INDETERMINATE_GRACE),
        "command": None,
        "scheduled_for": None,
        "next_evaluation_at": LATER,
    }
    fields.update(changes)
    return HeatDemandEvaluationResult(**fields)


def test_enum_values_are_stable_strings():
    assert [item.value for item in HeatDemandEvaluationTrigger] == [
        "startup",
        "actionable_decision",
        "scheduled",
        "manual",
    ]
    assert [item.value for item in HeatDemandEvaluationStatus] == [
        "indeterminate_grace",
        "demand_command_executed",
        "demand_command_suppressed",
        "safety_command_executed",
        "safety_command_suppressed",
        "demand_command_deferred",
        "safety_command_deferred",
        "resilience_command_executed",
        "resilience_command_suppressed",
        "resilience_command_deferred",
        "resilience_command_held",
        "resilience_indeterminate",
    ]
    assert all(isinstance(item, str) for item in (*HeatDemandEvaluationTrigger, *HeatDemandEvaluationStatus))


def test_result_is_immutable():
    result = grace_result()

    with pytest.raises(FrozenInstanceError):
        result.command = command(HeatingAction.DISABLE_HEATING)


def test_scheduled_trigger_requires_scheduled_for_and_other_triggers_reject_it():
    with pytest.raises(ValueError, match="SCHEDULED requires"):
        grace_result(trigger=HeatDemandEvaluationTrigger.SCHEDULED)

    for trigger in (
        HeatDemandEvaluationTrigger.STARTUP,
        HeatDemandEvaluationTrigger.ACTIONABLE_DECISION,
        HeatDemandEvaluationTrigger.MANUAL,
    ):
        with pytest.raises(ValueError, match="scheduled_for=None"):
            grace_result(trigger=trigger, scheduled_for=NOW)

    assert grace_result(
        trigger=HeatDemandEvaluationTrigger.SCHEDULED,
        scheduled_for=NOW,
    )


def test_grace_requires_exact_aggregate_phase_command_and_deadline():
    with pytest.raises(ValueError, match="INDETERMINATE_GRACE"):
        grace_result(building_heat_demand=demand(BuildingHeatDemandStatus.HEAT_REQUIRED))
    with pytest.raises(ValueError, match="INDETERMINATE_GRACE"):
        grace_result(command=command(HeatingAction.DISABLE_HEATING))
    with pytest.raises(ValueError, match="INDETERMINATE_GRACE"):
        grace_result(next_evaluation_at=None)


@pytest.mark.parametrize(
    ("aggregate_status", "action"),
    [
        (BuildingHeatDemandStatus.HEAT_REQUIRED, HeatingAction.ENABLE_HEATING),
        (BuildingHeatDemandStatus.NO_HEAT_REQUIRED, HeatingAction.DISABLE_HEATING),
    ],
)
@pytest.mark.parametrize(
    "result_status",
    [
        HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED,
        HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED,
    ],
)
def test_determinate_command_invariants(aggregate_status, action, result_status):
    result = HeatDemandEvaluationResult(
        trigger=HeatDemandEvaluationTrigger.MANUAL,
        status=result_status,
        building_heat_demand=demand(aggregate_status),
        safety_assessment=assessment(HeatDemandSafetyPhase.DETERMINATE),
        command=command(action),
        scheduled_for=None,
        next_evaluation_at=LATER,
    )

    assert result.command.action is action
    with pytest.raises(ValueError, match="matching command"):
        HeatDemandEvaluationResult(
            trigger=result.trigger,
            status=result.status,
            building_heat_demand=result.building_heat_demand,
            safety_assessment=result.safety_assessment,
            command=command(
                HeatingAction.DISABLE_HEATING
                if action is HeatingAction.ENABLE_HEATING
                else HeatingAction.ENABLE_HEATING
            ),
            scheduled_for=None,
            next_evaluation_at=LATER,
        )


@pytest.mark.parametrize(
    "result_status",
    [
        HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED,
        HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED,
    ],
)
def test_safety_command_invariants(result_status):
    safety = assessment(
        HeatDemandSafetyPhase.INDETERMINATE_TIMED_OUT,
        action=HeatingAction.DISABLE_HEATING,
    )
    result = HeatDemandEvaluationResult(
        trigger=HeatDemandEvaluationTrigger.MANUAL,
        status=result_status,
        building_heat_demand=demand(BuildingHeatDemandStatus.INDETERMINATE),
        safety_assessment=safety,
        command=command(HeatingAction.DISABLE_HEATING),
        scheduled_for=None,
        next_evaluation_at=None,
    )

    assert result.command.action is safety.action
    with pytest.raises(ValueError, match="safety command"):
        HeatDemandEvaluationResult(
            trigger=result.trigger,
            status=result.status,
            building_heat_demand=result.building_heat_demand,
            safety_assessment=safety,
            command=command(HeatingAction.ENABLE_HEATING),
            scheduled_for=None,
            next_evaluation_at=None,
        )


def test_deadline_awareness_ordering_and_assessment_timestamp_are_exact():
    with pytest.raises(ValueError, match="timezone-aware"):
        grace_result(next_evaluation_at=datetime(2026, 1, 1, 13))
    with pytest.raises(ValueError, match="later"):
        grace_result(next_evaluation_at=NOW)
    with pytest.raises(ValueError, match="times must match"):
        grace_result(
            safety_assessment=assessment(
                HeatDemandSafetyPhase.INDETERMINATE_GRACE,
                evaluated_at=NOW + datetime.resolution,
            )
        )
