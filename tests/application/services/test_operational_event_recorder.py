"""Transition, correlation, and de-duplication tests for M31A."""

from dataclasses import replace
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
from controlel.application.services.operational_event_recorder import OperationalEventRecorder
from controlel.application.services.operational_event_stream import OperationalEventStream
from controlel.application.services.source_control_policy import (
    SourceControlAssessment,
    SourceControlOutcome,
    SourceControlPolicy,
)
from controlel.application.services.source_reconciliation_policy import SourceReconciliationPolicy
from controlel.application.services.zone_heat_demand_confirmation_policy import ZoneHeatDemandConfirmationPolicy
from controlel.application.state.heat_demand_safety_state import HeatDemandSafetyState
from controlel.application.state.source_control_state import ActiveLockoutType, SourceControlReason
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand import BuildingHeatDemand
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.demands.zone_heat_demand_input import ZoneHeatDemandInput, ZoneHeatDemandInputReason
from controlel.domain.operational_events import MeasurementEventCondition, OperationalEventCode
from controlel.domain.source_control import ReportedSourceEvidence, ReportedSourceState, SourceOwnership
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 8, 13, tzinfo=UTC)
ZONE = ZoneId("living_room")
SENSOR = SensorId("living_room_temperature")


def _result(status: BuildingHeatDemandStatus, at: datetime = NOW) -> HeatDemandEvaluationResult:
    evidence = (
        None
        if status is BuildingHeatDemandStatus.INDETERMINATE
        else ZoneDemand(
            zone_id=ZONE,
            requires_heat=status is BuildingHeatDemandStatus.HEAT_REQUIRED,
            source_sensor_id=SENSOR,
            observed_at=at,
        )
    )
    demand = BuildingHeatDemand(
        status=status,
        zone_inputs=(
            ZoneHeatDemandInput(
                zone_id=ZONE,
                demand=status,
                reason=(
                    ZoneHeatDemandInputReason.MISSING
                    if status is BuildingHeatDemandStatus.INDETERMINATE
                    else ZoneHeatDemandInputReason.ELIGIBLE
                ),
                evidence=evidence,
            ),
        ),
        evaluated_at=at,
        eligible_demands=(evidence,) if evidence is not None else (),
        missing_zone_ids=(ZONE,) if evidence is None else (),
        expired_zone_ids=(),
        future_dated_zone_ids=(),
        contributing_heat_zone_ids=(ZONE,) if status is BuildingHeatDemandStatus.HEAT_REQUIRED else (),
        no_heat_zone_ids=(ZONE,) if status is BuildingHeatDemandStatus.NO_HEAT_REQUIRED else (),
        indeterminate_zone_ids=(ZONE,) if status is BuildingHeatDemandStatus.INDETERMINATE else (),
        zone_count=1,
        heat_requesting_zone_count=1 if status is BuildingHeatDemandStatus.HEAT_REQUIRED else 0,
    )
    safety = HeatDemandSafetyAssessment(
        state=HeatDemandSafetyState(
            indeterminate_since=at if status is BuildingHeatDemandStatus.INDETERMINATE else None,
            last_determinate_status=(None if status is BuildingHeatDemandStatus.INDETERMINATE else status),
            last_evaluated_at=at,
        ),
        phase=(
            HeatDemandSafetyPhase.INDETERMINATE_GRACE
            if status is BuildingHeatDemandStatus.INDETERMINATE
            else HeatDemandSafetyPhase.DETERMINATE
        ),
        timeout_at=at + timedelta(minutes=1) if status is BuildingHeatDemandStatus.INDETERMINATE else None,
        action=None,
    )
    return HeatDemandEvaluationResult(
        trigger=HeatDemandEvaluationTrigger.MANUAL,
        status=(
            HeatDemandEvaluationStatus.INDETERMINATE_GRACE
            if status is BuildingHeatDemandStatus.INDETERMINATE
            else HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED
        ),
        building_heat_demand=demand,
        safety_assessment=safety,
        command=(
            None
            if status is BuildingHeatDemandStatus.INDETERMINATE
            else HeatSourceCommand(
                command_type=CommandFamily.HEATING,
                action=(
                    HeatingAction.ENABLE_HEATING
                    if status is BuildingHeatDemandStatus.HEAT_REQUIRED
                    else HeatingAction.DISABLE_HEATING
                ),
            )
        ),
        scheduled_for=None,
        next_evaluation_at=safety.timeout_at,
    )


def test_repeated_demand_and_source_states_do_not_emit_duplicates() -> None:
    recorder = OperationalEventRecorder(OperationalEventStream())
    recorder.evaluation(_result(BuildingHeatDemandStatus.NO_HEAT_REQUIRED))
    recorder.evaluation(_result(BuildingHeatDemandStatus.NO_HEAT_REQUIRED, NOW + timedelta(seconds=1)))
    recorder.reported_source(ReportedSourceEvidence(ReportedSourceState.DISABLED, NOW))
    recorder.reported_source(ReportedSourceEvidence(ReportedSourceState.DISABLED, NOW + timedelta(seconds=1)))

    assert [event.event_code for event in recorder.stream.snapshot().events] == []


def test_stale_then_valid_emits_explicit_recovery_once() -> None:
    recorder = OperationalEventRecorder()
    recorder.measurement(MeasurementEventCondition.STALE, NOW)
    recorder.measurement(MeasurementEventCondition.STALE, NOW + timedelta(seconds=1))
    recorder.measurement(MeasurementEventCondition.VALID, NOW + timedelta(seconds=2))

    assert [event.event_code for event in recorder.stream.snapshot().events] == [
        OperationalEventCode.MEASUREMENT_BECAME_STALE,
        OperationalEventCode.MEASUREMENT_RECOVERED,
    ]


def test_demand_start_and_confirmation_share_only_their_zone_correlation() -> None:
    recorder = OperationalEventRecorder()
    policy = ZoneHeatDemandConfirmationPolicy(confirmation_duration=timedelta(seconds=1))
    pending = policy.evaluate(
        hysteresis_demand=BuildingHeatDemandStatus.HEAT_REQUIRED,
        now=NOW,
        current_state=None,
    )
    confirmed = policy.evaluate(
        hysteresis_demand=BuildingHeatDemandStatus.HEAT_REQUIRED,
        now=NOW + timedelta(seconds=1),
        current_state=pending.state,
        deadline_reevaluation=True,
    )
    recorder.evaluation(
        replace(_result(BuildingHeatDemandStatus.HEAT_REQUIRED), confirmation_assessment=pending),
        confirmation_assessments={ZONE: pending},
    )
    recorder.evaluation(
        replace(
            _result(BuildingHeatDemandStatus.HEAT_REQUIRED, NOW + timedelta(seconds=1)),
            confirmation_assessment=confirmed,
        ),
        confirmation_assessments={ZONE: confirmed},
    )
    recorder.measurement(MeasurementEventCondition.STALE, NOW + timedelta(seconds=2))

    started, confirmed_event, measurement = recorder.stream.snapshot().events
    assert started.event_code is OperationalEventCode.HEAT_DEMAND_STARTED
    assert confirmed_event.event_code is OperationalEventCode.HEAT_DEMAND_CONFIRMED
    assert started.correlation_id == confirmed_event.correlation_id
    assert measurement.correlation_id is None


def test_one_active_minimum_on_hold_emits_once() -> None:
    recorder = OperationalEventRecorder()
    command = HeatSourceCommand(
        command_type=CommandFamily.HEATING,
        action=HeatingAction.DISABLE_HEATING,
    )
    deadline = NOW + timedelta(minutes=5)
    assessment = SourceControlAssessment(
        state=SourceControlPolicy(minimum_on_time=timedelta(), minimum_off_time=timedelta()).initial_state(NOW),
        outcome=SourceControlOutcome.DEFER,
        reason=SourceControlReason.MINIMUM_ON_TIME_ACTIVE,
        active_lockout=ActiveLockoutType.MINIMUM_ON,
        lockout_deadline=deadline,
        safety_bypassed_lockout=False,
    )
    result = replace(
        _result(BuildingHeatDemandStatus.NO_HEAT_REQUIRED),
        status=HeatDemandEvaluationStatus.DEMAND_COMMAND_DEFERRED,
        command=command,
        source_control_assessment=assessment,
    )

    recorder.evaluation(result)
    recorder.evaluation(result)

    assert [event.event_code for event in recorder.stream.snapshot().events] == [
        OperationalEventCode.SOURCE_COMMAND_DEFERRED_MINIMUM_ON
    ]


@pytest.mark.parametrize(
    ("action", "initial_state", "reported_state"),
    (
        (HeatingAction.ENABLE_HEATING, ReportedSourceState.DISABLED, ReportedSourceState.ENABLED),
        (HeatingAction.DISABLE_HEATING, ReportedSourceState.ENABLED, ReportedSourceState.DISABLED),
    ),
)
@pytest.mark.parametrize("command_succeeded", (False, True))
def test_reported_transition_never_inherits_command_correlation_without_causal_evidence(
    action,
    initial_state,
    reported_state,
    command_succeeded,
) -> None:
    recorder = OperationalEventRecorder()
    correlation = recorder.command_requested(action, NOW)
    if command_succeeded:
        recorder.command_dispatched(action, NOW, correlation_id=correlation)
    else:
        recorder.command_failed(action, NOW, reason_code="service_call_failed", correlation_id=correlation)
    recorder.reported_source(ReportedSourceEvidence(initial_state, NOW))
    recorder.reported_source(ReportedSourceEvidence(reported_state, NOW + timedelta(seconds=1), NOW))

    requested, outcome, reported = recorder.stream.snapshot().events
    expected_request = (
        OperationalEventCode.SOURCE_ENABLE_REQUESTED
        if action is HeatingAction.ENABLE_HEATING
        else OperationalEventCode.SOURCE_DISABLE_REQUESTED
    )
    assert requested.event_code is expected_request
    assert requested.command_outcome == "requested"
    assert outcome.event_code is (
        OperationalEventCode.SOURCE_COMMAND_DISPATCHED
        if command_succeeded
        else OperationalEventCode.SOURCE_COMMAND_FAILED
    )
    assert outcome.command_outcome == ("dispatched" if command_succeeded else "failed")
    assert requested.correlation_id == outcome.correlation_id == correlation
    assert reported.event_code is OperationalEventCode.REPORTED_SOURCE_STATE_CHANGED
    assert reported.command_outcome is None
    assert reported.new_state == reported_state.value
    assert reported.correlation_id is None


def test_dispatcher_suppressed_duplicate_emits_no_source_request() -> None:
    recorder = OperationalEventRecorder()
    assessment = SourceControlAssessment(
        state=SourceControlPolicy(minimum_on_time=timedelta(), minimum_off_time=timedelta()).initial_state(NOW),
        outcome=SourceControlOutcome.DISPATCH,
        reason=SourceControlReason.NORMAL_DEMAND,
        active_lockout=None,
        lockout_deadline=None,
        safety_bypassed_lockout=False,
    )
    suppressed = replace(
        _result(BuildingHeatDemandStatus.HEAT_REQUIRED),
        source_control_assessment=assessment,
    )

    recorder.evaluation(suppressed)
    recorder.evaluation(suppressed)

    assert recorder.stream.snapshot().events == ()


def test_measurement_and_safety_events_share_a_distinct_incident_activity_id() -> None:
    recorder = OperationalEventRecorder()
    recorder.measurement(MeasurementEventCondition.STALE, NOW)
    recorder.evaluation(_result(BuildingHeatDemandStatus.INDETERMINATE, NOW + timedelta(seconds=1)))
    recorder.measurement(MeasurementEventCondition.VALID, NOW + timedelta(seconds=2))

    events = recorder.stream.snapshot().events
    assert [event.event_code for event in events] == [
        OperationalEventCode.MEASUREMENT_BECAME_STALE,
        OperationalEventCode.SAFETY_GRACE_STARTED,
        OperationalEventCode.MEASUREMENT_RECOVERED,
    ]
    assert len({event.activity_id for event in events}) == 1
    assert events[0].activity_id is not None
    assert events[0].activity_id.startswith("measurement-incident:")
    assert all(event.correlation_id is None for event in events)


def test_reconciliation_campaign_has_explicit_activity_id_and_truthful_completion() -> None:
    recorder = OperationalEventRecorder()
    policy = SourceReconciliationPolicy(unknown_transition_hold=timedelta())
    reported_on = ReportedSourceEvidence(
        ReportedSourceState.ENABLED,
        NOW,
        NOW - timedelta(minutes=1),
    )
    drift = policy.evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.DISABLE_HEATING,
        last_successful_command=HeatingAction.DISABLE_HEATING,
        reported=reported_on,
        current_state=None,
        now=NOW,
    )
    recorder.evaluation(
        replace(_result(BuildingHeatDemandStatus.NO_HEAT_REQUIRED), source_reconciliation_assessment=drift)
    )
    reported_off = ReportedSourceEvidence(ReportedSourceState.DISABLED, NOW + timedelta(seconds=1))
    agreed = policy.evaluate(
        ownership=SourceOwnership.CONTROLEL_OWNED,
        desired_command=HeatingAction.DISABLE_HEATING,
        last_successful_command=HeatingAction.DISABLE_HEATING,
        reported=reported_off,
        current_state=drift.state,
        now=NOW + timedelta(seconds=1),
    )
    recorder.evaluation(
        replace(
            _result(BuildingHeatDemandStatus.NO_HEAT_REQUIRED, NOW + timedelta(seconds=1)),
            source_reconciliation_assessment=agreed,
        )
    )

    drift_event, started_event, completed_event = recorder.stream.snapshot().events
    assert drift_event.activity_id == started_event.activity_id == completed_event.activity_id
    assert drift_event.activity_id is not None
    assert drift_event.activity_id.startswith("source-reconciliation:")
    assert {detail.key: detail.value for detail in drift_event.details} == {
        "desired_state": "disable_heating",
        "reported_state": "enabled",
    }
    assert {detail.key: detail.value for detail in completed_event.details}["completion_outcome"] == (
        "reported_agreement"
    )


def test_successful_building_source_commands_share_episode_but_keep_command_correlations() -> None:
    recorder = OperationalEventRecorder()
    policy = SourceControlPolicy(minimum_on_time=timedelta(), minimum_off_time=timedelta())
    initial = policy.initial_state(NOW)
    dispatch = SourceControlAssessment(
        state=initial,
        outcome=SourceControlOutcome.DISPATCH,
        reason=SourceControlReason.NORMAL_DEMAND,
        active_lockout=None,
        lockout_deadline=None,
        safety_bypassed_lockout=False,
    )
    recorder.evaluation(
        replace(
            _result(BuildingHeatDemandStatus.HEAT_REQUIRED),
            status=HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED,
            source_control_assessment=dispatch,
        )
    )
    recorder.evaluation(
        replace(
            _result(BuildingHeatDemandStatus.NO_HEAT_REQUIRED, NOW + timedelta(minutes=1)),
            status=HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED,
            source_control_assessment=dispatch,
        )
    )

    command_events = [
        event
        for event in recorder.stream.snapshot().events
        if event.event_code
        in {
            OperationalEventCode.SOURCE_ENABLE_REQUESTED,
            OperationalEventCode.SOURCE_DISABLE_REQUESTED,
            OperationalEventCode.SOURCE_COMMAND_DISPATCHED,
        }
    ]
    assert len({event.activity_id for event in command_events}) == 1
    assert command_events[0].activity_id is not None
    assert command_events[0].activity_id.startswith("heating-episode:")
    assert len({event.correlation_id for event in command_events}) == 2
