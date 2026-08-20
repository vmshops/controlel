import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.services.heating_diagnostics_projector import HeatingDiagnosticsProjector
from controlel.application.services.heating_performance_assessor import HeatingPerformanceAssessor
from controlel.application.services.shadow_heating_performance_monitor import (
    ShadowAssessmentErrorEvidence,
    ShadowPerformanceMonitorSnapshot,
)
from controlel.application.state.heating_diagnostics import (
    HEATING_DIAGNOSTICS_SCHEMA_VERSION,
    MAX_PROJECTED_ACTUATORS,
    MAX_PROJECTED_PIPELINE_ERRORS,
    MAX_PROJECTED_ZONES,
    heating_diagnostics_to_dict,
)
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.heat_delivery import (
    HeatDeliveryActuatorId,
    HeatDeliveryCapabilities,
    HeatDeliveryCommand,
    HeatDeliveryCommandKind,
    HeatDeliveryCommandOutcome,
    HeatDeliveryMode,
    HeatDeliveryObservation,
    HeatingAnomalyCategory,
    HeatingAnomalyConfidence,
    HeatingAnomalyEvidence,
    HeatingAnomalyEvidenceItem,
    HeatingAnomalyLifecycle,
    HeatingAnomalyObservation,
    HeatingAnomalySeverity,
    HeatingDemandTransition,
    HeatingEpisode,
    HeatingEpisodeSample,
    HeatingEpisodeTerminationReason,
    HeatingPerformanceAssessmentCriteria,
    HeatingPerformanceSnapshot,
    HeatSourceObservation,
    ObservationQuality,
    ObservedValue,
    heating_anomaly_id,
)
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def actuator_observation(actuator_id: str) -> HeatDeliveryObservation:
    requested = HeatDeliveryCommand(
        actuator_id=HeatDeliveryActuatorId(actuator_id),
        zone_id=ZoneId("zone"),
        kind=HeatDeliveryCommandKind.SET_POSITION,
        value=30.0,
        requested_at=NOW + timedelta(minutes=1),
    )
    successful = HeatDeliveryCommand(
        actuator_id=HeatDeliveryActuatorId(actuator_id),
        zone_id=ZoneId("zone"),
        kind=HeatDeliveryCommandKind.SET_POSITION,
        value=25.0,
        requested_at=NOW,
    )
    return HeatDeliveryObservation(
        zone_id=ZoneId("zone"),
        actuator_id=HeatDeliveryActuatorId(actuator_id),
        captured_at=NOW + timedelta(hours=1),
        mode=HeatDeliveryMode.DIRECT_POSITION,
        capabilities=HeatDeliveryCapabilities(
            can_read_valve_position=True,
            can_write_valve_position=True,
        ),
        commanded_position=30.0,
        last_requested_command=requested,
        last_successful_command=successful,
        last_command_outcome=HeatDeliveryCommandOutcome.DISPATCHED,
        last_command_timestamp=NOW + timedelta(minutes=1),
        reported_position=ObservedValue.valid(42.0, NOW + timedelta(minutes=59)),
    )


def episode(
    zone: str = "zone",
    *,
    active: bool = False,
    terminal_valid: bool = True,
    termination_reason: HeatingEpisodeTerminationReason = HeatingEpisodeTerminationReason.DEMAND_CLEARED,
    actuators: tuple[HeatDeliveryObservation, ...] = (),
    total_sample_count: int = 2,
) -> HeatingEpisode:
    ended_at = None if active else NOW + timedelta(hours=1)
    terminal_temperature = (
        ObservedValue.valid(21.0, NOW + timedelta(hours=1))
        if terminal_valid
        else ObservedValue.unknown("terminal measurement unavailable")
    )
    samples = (
        HeatingEpisodeSample(
            captured_at=NOW,
            zone_temperature=ObservedValue.valid(20.0, NOW),
            target_temperature=22.0,
            actuator_observations=(),
            source_observation=HeatSourceObservation(
                captured_at=NOW,
                last_requested_action=HeatingAction.ENABLE_HEATING,
            ),
        ),
        HeatingEpisodeSample(
            captured_at=NOW + timedelta(hours=1),
            zone_temperature=terminal_temperature,
            target_temperature=22.0,
            actuator_observations=actuators,
            source_observation=HeatSourceObservation(
                captured_at=NOW + timedelta(hours=1),
                last_requested_action=HeatingAction.ENABLE_HEATING,
                last_successful_dispatch_action=HeatingAction.ENABLE_HEATING,
                last_successful_dispatch_at=NOW + timedelta(minutes=1),
            ),
        ),
    )
    return HeatingEpisode(
        zone_id=ZoneId(zone),
        started_at=NOW,
        ended_at=ended_at,
        termination_reason=None if active else termination_reason,
        initial_target_temperature=22.0,
        current_target_temperature=22.0,
        initial_temperature=20.0,
        current_temperature=21.0 if terminal_valid else 20.0,
        demand_transitions=(
            HeatingDemandTransition(demand=BuildingHeatDemandStatus.HEAT_REQUIRED, changed_at=NOW),
            *(
                ()
                if active
                else (
                    HeatingDemandTransition(
                        demand=(
                            BuildingHeatDemandStatus.NO_HEAT_REQUIRED
                            if termination_reason is HeatingEpisodeTerminationReason.DEMAND_CLEARED
                            else BuildingHeatDemandStatus.INDETERMINATE
                        ),
                        changed_at=NOW + timedelta(hours=1),
                    ),
                )
            ),
        ),
        total_sample_count=total_sample_count,
        samples_truncated=total_sample_count > len(samples),
        samples=samples,
    )


def monitor_snapshot(
    *,
    assessments=(),
    pending: int = 0,
    errors=(),
) -> ShadowPerformanceMonitorSnapshot:
    return ShadowPerformanceMonitorSnapshot(
        enabled=True,
        pending_assessment_count=pending,
        assessments=tuple(assessments),
        assessment_capacity=20,
        dropped_pending_assessment_count=0,
        latest_drop=None,
        errors=tuple(errors),
    )


def test_projection_is_immutable_deterministic_json_safe_and_canonically_ordered() -> None:
    first_episode = episode("zone")
    second_episode = episode("another")
    projector = HeatingDiagnosticsProjector()

    first = projector.project(
        zone_ids=(ZoneId("zone"), ZoneId("another")),
        active_episodes=(),
        completed_episodes=(first_episode, second_episode),
        monitor=monitor_snapshot(pending=2),
    )
    second = projector.project(
        zone_ids=(ZoneId("another"), ZoneId("zone")),
        active_episodes=(),
        completed_episodes=(second_episode, first_episode),
        monitor=monitor_snapshot(pending=2),
    )

    assert first == second
    assert first.schema_version == HEATING_DIAGNOSTICS_SCHEMA_VERSION == 1
    assert first.updated_at == (NOW + timedelta(hours=1)).isoformat()
    assert [item.zone_id for item in first.zones] == ["another", "zone"]
    json.dumps(heating_diagnostics_to_dict(first), sort_keys=True)
    with pytest.raises(FrozenInstanceError):
        first.updated_at = None  # type: ignore[misc]


def test_requested_dispatched_reported_and_physical_source_evidence_remain_distinct() -> None:
    candidate = episode(actuators=(actuator_observation("valve"),))
    snapshot = HeatingDiagnosticsProjector().project(
        zone_ids=(ZoneId("zone"),),
        active_episodes=(),
        completed_episodes=(candidate,),
        monitor=monitor_snapshot(pending=1),
    )

    projected = snapshot.zones[0].latest_completed_episode
    assert projected is not None
    actuator = projected.actuators[0]
    assert actuator.requested_command is not None
    assert actuator.requested_command.value == 30.0
    assert actuator.successfully_dispatched_command is not None
    assert actuator.successfully_dispatched_command.value == 25.0
    assert actuator.reported_position.value == 42.0
    assert actuator.reported_position.quality == ObservationQuality.VALID.value
    assert projected.source.requested_permission == HeatingAction.ENABLE_HEATING.value
    assert projected.source.successfully_dispatched_permission == HeatingAction.ENABLE_HEATING.value
    assert projected.source.physical_heat_available.value is None
    assert projected.source.physical_heat_available.quality == ObservationQuality.UNKNOWN.value


def test_truncation_criteria_and_terminal_temperature_semantics_are_truthful() -> None:
    candidate = episode(terminal_valid=False, total_sample_count=5)
    criteria = HeatingPerformanceAssessmentCriteria(
        stable_temperature_tolerance=0.125,
        target_change_tolerance=0.25,
    )
    assessment = HeatingPerformanceAssessor(criteria).assess(candidate)
    snapshot = HeatingDiagnosticsProjector().project(
        zone_ids=(ZoneId("zone"),),
        active_episodes=(),
        completed_episodes=(candidate,),
        monitor=monitor_snapshot(assessments=(assessment,)),
    )

    projected = snapshot.zones[0].latest_completed_episode
    projected_assessment = snapshot.zones[0].latest_assessment
    assert projected is not None and projected_assessment is not None
    assert projected.total_sample_count == 5
    assert projected.retained_sample_count == 2
    assert projected.samples_truncated is True
    assert projected.temperature.latest_valid_temperature == 20.0
    assert projected.temperature.terminal_temperature is None
    assert projected.target.end_target_relative_error.value is None
    assert projected.target.end_target_relative_error.quality == ObservationQuality.UNKNOWN.value
    assert projected_assessment.criteria.stable_temperature_tolerance == 0.125
    assert projected_assessment.criteria.target_change_tolerance == 0.25
    assert projected_assessment.history_truncated is True


def test_actuator_projection_has_a_hard_deterministic_cap() -> None:
    observations = tuple(
        actuator_observation(f"valve_{index:02d}") for index in reversed(range(MAX_PROJECTED_ACTUATORS + 3))
    )
    candidate = episode(actuators=observations)

    projected = (
        HeatingDiagnosticsProjector()
        .project(
            zone_ids=(ZoneId("zone"),),
            active_episodes=(),
            completed_episodes=(candidate,),
            monitor=monitor_snapshot(pending=1),
        )
        .zones[0]
        .latest_completed_episode
    )

    assert projected is not None
    assert len(projected.actuators) == MAX_PROJECTED_ACTUATORS
    assert projected.actuator_count_truncated is True
    assert [item.actuator_id for item in projected.actuators] == sorted(
        item.actuator_id for item in projected.actuators
    )


@pytest.mark.parametrize(
    "termination_reason",
    [
        HeatingEpisodeTerminationReason.RUNTIME_STOPPED,
        HeatingEpisodeTerminationReason.FATAL_SHUTDOWN,
    ],
)
def test_runtime_and_fatal_episode_termination_remain_explicit(termination_reason) -> None:
    candidate = episode(termination_reason=termination_reason)
    projected = (
        HeatingDiagnosticsProjector()
        .project(
            zone_ids=(ZoneId("zone"),),
            active_episodes=(),
            completed_episodes=(candidate,),
            monitor=monitor_snapshot(pending=1),
        )
        .zones[0]
        .latest_completed_episode
    )

    assert projected is not None
    assert projected.termination_reason == termination_reason.value


def test_reload_projection_starts_empty_without_fabricated_continuity_or_timestamp() -> None:
    snapshot = HeatingDiagnosticsProjector().project(
        zone_ids=(ZoneId("zone"),),
        active_episodes=(),
        completed_episodes=(),
        monitor=monitor_snapshot(),
    )

    assert snapshot.updated_at is None
    assert snapshot.zones[0].active_episode is None
    assert snapshot.zones[0].latest_completed_episode is None
    assert snapshot.zones[0].latest_assessment is None


def test_active_episode_start_and_new_evidence_update_are_explicit() -> None:
    started = episode(active=True)
    extra_time = NOW + timedelta(hours=2)
    extra_sample = HeatingEpisodeSample(
        captured_at=extra_time,
        zone_temperature=ObservedValue.valid(21.5, extra_time),
        target_temperature=22.0,
        actuator_observations=(),
        source_observation=HeatSourceObservation(captured_at=extra_time),
    )
    updated = replace(
        started,
        current_temperature=21.5,
        total_sample_count=3,
        samples=(*started.samples, extra_sample),
    )
    projector = HeatingDiagnosticsProjector()

    first = projector.project(
        zone_ids=(ZoneId("zone"),),
        active_episodes=(started,),
        completed_episodes=(),
        monitor=monitor_snapshot(),
    )
    second = projector.project(
        zone_ids=(ZoneId("zone"),),
        active_episodes=(updated,),
        completed_episodes=(),
        monitor=monitor_snapshot(),
    )

    assert first.zones[0].active_episode is not None
    assert first.zones[0].active_episode.lifecycle == "active"
    assert first.zones[0].latest_completed_episode is None
    assert second.updated_at == extra_time.isoformat()
    assert second.zones[0].active_episode is not None
    assert second.zones[0].active_episode.total_sample_count == 3
    assert second.zones[0].active_episode.temperature.latest_valid_temperature == 21.5


def test_anomaly_is_projected_with_lifecycle_scope_and_structured_evidence() -> None:
    episode_id = "heating_episode:zone:2026-01-01T00:00:00+00:00"
    anomaly = HeatingAnomalyObservation(
        anomaly_id=heating_anomaly_id(
            category=HeatingAnomalyCategory.PERFORMANCE,
            reason_code="temperature_falling",
            zone_id=ZoneId("zone"),
            heating_episode_id=episode_id,
        ),
        category=HeatingAnomalyCategory.PERFORMANCE,
        severity=HeatingAnomalySeverity.WARNING,
        confidence=HeatingAnomalyConfidence.HIGH,
        reason_code="temperature_falling",
        lifecycle=HeatingAnomalyLifecycle.STARTED,
        first_observed_at=NOW + timedelta(minutes=30),
        last_observed_at=NOW + timedelta(minutes=30),
        updated_at=NOW + timedelta(minutes=30),
        cleared_at=None,
        zone_id=ZoneId("zone"),
        source_id=None,
        heating_episode_id=episode_id,
        assessment_id="performance_assessment:1",
        lifecycle_reason_code="condition_detected",
        evidence=HeatingAnomalyEvidence(
            items=(
                HeatingAnomalyEvidenceItem("sample_count", 3),
                HeatingAnomalyEvidenceItem("temperature_delta", -0.4),
            ),
            source_observation_timestamps=(NOW, NOW + timedelta(minutes=30)),
        ),
    )
    performance = HeatingPerformanceSnapshot(
        schema_version=1,
        assessment_capacity=20,
        total_assessments_emitted=0,
        dropped_assessment_count=0,
        pending_zone_capacity=64,
        pending_observation_count=0,
        pending_observations_dropped=0,
        zones=(),
        assessments=(),
        errors=(),
        total_anomaly_transitions_emitted=1,
        dropped_anomaly_transition_count=0,
        active_anomalies=(anomaly,),
        anomaly_transitions=(anomaly,),
    )

    snapshot = HeatingDiagnosticsProjector().project(
        zone_ids=(),
        active_episodes=(),
        completed_episodes=(),
        monitor=monitor_snapshot(),
        performance=performance,
    )

    projected = snapshot.zones[0].latest_anomaly
    assert projected is not None
    assert projected.lifecycle == "started"
    assert projected.zone_id == "zone"
    assert projected.source_id is None
    assert projected.heating_episode_id == episode_id
    assert {item.key: item.value for item in projected.evidence_items} == {
        "sample_count": 3,
        "temperature_delta": -0.4,
    }
    assert projected.source_observation_timestamps == (
        NOW.isoformat(),
        (NOW + timedelta(minutes=30)).isoformat(),
    )
    assert snapshot.pipeline.active_anomaly_count == 1
    assert snapshot.pipeline.total_anomaly_transitions_emitted == 1


def test_assessment_failure_uses_safe_normalized_error_evidence() -> None:
    candidate = episode()
    error = ShadowAssessmentErrorEvidence(
        zone_id=ZoneId("zone"),
        episode_started_at=candidate.started_at,
        episode_ended_at=candidate.ended_at,
        exception_type="RuntimeError",
    )
    snapshot = HeatingDiagnosticsProjector().project(
        zone_ids=(ZoneId("zone"),),
        active_episodes=(),
        completed_episodes=(candidate,),
        monitor=monitor_snapshot(errors=(error,)),
    )

    assert snapshot.pipeline.health_code == "degraded"
    assert snapshot.pipeline.assessment_errors[0].reason_code == "assessment_failed"
    assert snapshot.pipeline.assessment_errors[0].exception_type == "RuntimeError"
    assert "password=secret" not in json.dumps(heating_diagnostics_to_dict(snapshot)).lower()


def test_pipeline_error_evidence_has_a_hard_canonical_cap() -> None:
    errors = tuple(
        ShadowAssessmentErrorEvidence(
            zone_id=ZoneId(f"zone_{index:02d}"),
            episode_started_at=NOW,
            episode_ended_at=NOW + timedelta(hours=1),
            exception_type="RuntimeError",
        )
        for index in reversed(range(MAX_PROJECTED_PIPELINE_ERRORS + 5))
    )

    snapshot = HeatingDiagnosticsProjector().project(
        zone_ids=(),
        active_episodes=(),
        completed_episodes=(),
        monitor=monitor_snapshot(errors=errors),
    )

    assert snapshot.pipeline.assessment_error_count == MAX_PROJECTED_PIPELINE_ERRORS + 5
    assert len(snapshot.pipeline.assessment_errors) == MAX_PROJECTED_PIPELINE_ERRORS
    assert snapshot.pipeline.error_evidence_truncated is True
    assert [item.zone_id for item in snapshot.pipeline.assessment_errors] == sorted(
        item.zone_id for item in snapshot.pipeline.assessment_errors
    )


def test_zone_projection_has_a_hard_canonical_cap() -> None:
    snapshot = HeatingDiagnosticsProjector().project(
        zone_ids=tuple(ZoneId(f"zone_{index:03d}") for index in reversed(range(MAX_PROJECTED_ZONES + 4))),
        active_episodes=(),
        completed_episodes=(),
        monitor=monitor_snapshot(),
    )

    assert snapshot.total_zone_count == MAX_PROJECTED_ZONES + 4
    assert len(snapshot.zones) == MAX_PROJECTED_ZONES
    assert snapshot.zones_truncated is True
    assert [item.zone_id for item in snapshot.zones] == sorted(item.zone_id for item in snapshot.zones)
