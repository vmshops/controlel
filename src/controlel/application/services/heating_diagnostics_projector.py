"""Deterministic projection of heating evidence into presentation-neutral diagnostics."""

from collections import Counter
from dataclasses import fields
from datetime import datetime
from typing import Any

from controlel.application.services.heating_episode_observer import (
    HeatingEpisodeObservationErrorEvidence,
)
from controlel.application.services.shadow_heating_performance_monitor import (
    ShadowPerformanceMonitorSnapshot,
)
from controlel.application.state.heating_diagnostics import (
    HEATING_DIAGNOSTICS_SCHEMA_VERSION,
    MAX_PROJECTED_ACTUATORS,
    MAX_PROJECTED_PIPELINE_ERRORS,
    MAX_PROJECTED_ZONES,
    ActuatorEvidenceV1,
    AssessmentCriteriaV1,
    AssessmentDiagnosticsV1,
    AssessmentEvidenceV1,
    CommandEvidenceV1,
    DerivedValueDiagnosticsV1,
    DiagnosticErrorEvidenceV1,
    EpisodeDiagnosticsV1,
    HeatingDiagnosticsSnapshotV1,
    ObservedValueDiagnosticsV1,
    PendingDropEvidenceV1,
    QualityCountV1,
    ShadowPipelineDiagnosticsV1,
    SourceEvidenceV1,
    TargetEvidenceV1,
    TemperatureEvidenceV1,
    TemperatureResponseV1,
    ZoneHeatingDiagnosticsV1,
)
from controlel.domain.heat_delivery import (
    HeatDeliveryCapabilities,
    HeatDeliveryCommand,
    HeatDeliveryObservation,
    HeatingEpisode,
    HeatingPerformanceAssessment,
    HeatingPerformanceAssessmentReason,
    ObservationQuality,
    ObservedValue,
)
from controlel.domain.value_objects.zone_id import ZoneId


class HeatingDiagnosticsProjector:
    """Build immutable diagnostics without affecting observation or control."""

    def project(
        self,
        *,
        zone_ids: tuple[ZoneId, ...],
        active_episodes: tuple[HeatingEpisode, ...],
        completed_episodes: tuple[HeatingEpisode, ...],
        monitor: ShadowPerformanceMonitorSnapshot,
        observation_errors: tuple[HeatingEpisodeObservationErrorEvidence, ...] = (),
        projection_error: DiagnosticErrorEvidenceV1 | None = None,
    ) -> HeatingDiagnosticsSnapshotV1:
        active_by_zone = _latest_episodes(active_episodes)
        completed_by_zone = _latest_episodes(completed_episodes)
        assessments_by_zone = _latest_assessments(monitor.assessments)
        observation_errors_by_zone = {
            item.zone_id: _observation_error(item) for item in observation_errors if item.zone_id is not None
        }
        all_zone_ids = (
            set(zone_ids)
            | set(active_by_zone)
            | set(completed_by_zone)
            | set(assessments_by_zone)
            | {item.zone_id for item in observation_errors if item.zone_id is not None}
            | {item.zone_id for item in monitor.errors}
        )
        ordered_zone_ids = sorted(all_zone_ids, key=lambda item: item.value)
        zones = []
        for zone_id in ordered_zone_ids[:MAX_PROJECTED_ZONES]:
            assessment = assessments_by_zone.get(zone_id)
            completed = completed_by_zone.get(zone_id)
            matching_assessment = (
                assessment
                if completed is not None
                and assessment is not None
                and assessment.episode_started_at == completed.started_at
                else None
            )
            zones.append(
                ZoneHeatingDiagnosticsV1(
                    zone_id=zone_id.value,
                    active_episode=_episode(active_by_zone.get(zone_id), None),
                    latest_completed_episode=_episode(completed, matching_assessment),
                    latest_assessment=_assessment(assessment),
                    observation_error=observation_errors_by_zone.get(zone_id),
                )
            )

        all_assessment_errors = tuple(
            DiagnosticErrorEvidenceV1(
                component="assessment",
                reason_code="assessment_failed",
                exception_type=item.exception_type,
                zone_id=item.zone_id.value,
                evidence_at=_iso(item.episode_ended_at),
                episode_started_at=_iso(item.episode_started_at),
            )
            for item in sorted(
                monitor.errors,
                key=lambda item: (item.zone_id.value, item.episode_started_at),
            )
        )
        all_observation_errors = tuple(
            sorted(
                (_observation_error(item) for item in observation_errors),
                key=lambda item: (item.zone_id or "", item.evidence_at or ""),
            )
        )
        assessment_errors = all_assessment_errors[:MAX_PROJECTED_PIPELINE_ERRORS]
        remaining_capacity = MAX_PROJECTED_PIPELINE_ERRORS - len(assessment_errors)
        normalized_observation_errors = all_observation_errors[:remaining_capacity]
        latest_drop = (
            PendingDropEvidenceV1(
                zone_id=monitor.latest_drop.zone_id.value,
                episode_started_at=_iso(monitor.latest_drop.episode_started_at),
                episode_ended_at=_iso(monitor.latest_drop.episode_ended_at),
                reason_code=monitor.latest_drop.reason.value,
            )
            if monitor.latest_drop is not None
            else None
        )
        health_code = _pipeline_health_code(
            projection_error=projection_error,
            dropped_count=monitor.dropped_pending_assessment_count,
            assessment_errors=assessment_errors,
            observation_errors=normalized_observation_errors,
            pending_count=monitor.pending_assessment_count,
        )
        pipeline = ShadowPipelineDiagnosticsV1(
            health_code=health_code,
            enabled=monitor.enabled,
            pending_assessment_count=monitor.pending_assessment_count,
            retained_assessment_count=len(monitor.assessments),
            assessment_capacity=monitor.assessment_capacity,
            dropped_pending_assessment_count=monitor.dropped_pending_assessment_count,
            latest_drop=latest_drop,
            assessment_error_count=len(all_assessment_errors),
            observation_error_count=len(all_observation_errors),
            error_evidence_truncated=(
                len(all_assessment_errors) + len(all_observation_errors) > MAX_PROJECTED_PIPELINE_ERRORS
            ),
            assessment_errors=assessment_errors,
            observation_errors=normalized_observation_errors,
            projection_error=projection_error,
        )
        updated_at = _latest_evidence_timestamp(
            active_episodes=active_episodes,
            completed_episodes=completed_episodes,
            assessments=monitor.assessments,
            observation_errors=observation_errors,
            monitor=monitor,
            projection_error=projection_error,
        )
        return HeatingDiagnosticsSnapshotV1(
            schema_version=HEATING_DIAGNOSTICS_SCHEMA_VERSION,
            updated_at=_iso(updated_at) if updated_at is not None else None,
            total_zone_count=len(ordered_zone_ids),
            zones_truncated=len(ordered_zone_ids) > MAX_PROJECTED_ZONES,
            zones=tuple(zones),
            pipeline=pipeline,
        )


def _episode(
    episode: HeatingEpisode | None,
    assessment: HeatingPerformanceAssessment | None,
) -> EpisodeDiagnosticsV1 | None:
    if episode is None:
        return None
    samples = episode.samples
    latest_sample = samples[-1] if samples else None
    temperature = _temperature_evidence(episode, assessment)
    terminal_valid = (
        episode.ended_at is not None
        and latest_sample is not None
        and latest_sample.captured_at == episode.ended_at
        and latest_sample.zone_temperature.quality is ObservationQuality.VALID
        and latest_sample.zone_temperature.observed_at == episode.ended_at
        and latest_sample.zone_temperature.value is not None
    )
    start_error = (
        DerivedValueDiagnosticsV1(
            value=episode.initial_target_temperature - episode.initial_temperature,
            quality=ObservationQuality.VALID.value,
            reason_code=None,
        )
        if episode.initial_temperature is not None
        else DerivedValueDiagnosticsV1(
            value=None,
            quality=ObservationQuality.UNKNOWN.value,
            reason_code="initial_temperature_not_valid",
        )
    )
    end_error = (
        DerivedValueDiagnosticsV1(
            value=episode.current_target_temperature - float(latest_sample.zone_temperature.value),
            quality=ObservationQuality.VALID.value,
            reason_code=None,
        )
        if terminal_valid and latest_sample is not None
        else DerivedValueDiagnosticsV1(
            value=None,
            quality=ObservationQuality.UNKNOWN.value,
            reason_code="terminal_temperature_not_valid" if episode.ended_at is not None else "episode_active",
        )
    )
    actuator_by_id: dict[str, HeatDeliveryObservation] = {}
    for sample in samples:
        for observation in sample.actuator_observations:
            actuator_by_id[observation.actuator_id.value] = observation
    ordered_actuators = sorted(actuator_by_id.items())
    projected_actuators = tuple(_actuator(item) for _, item in ordered_actuators[:MAX_PROJECTED_ACTUATORS])
    observed_through = latest_sample.captured_at if latest_sample is not None else episode.started_at
    return EpisodeDiagnosticsV1(
        zone_id=episode.zone_id.value,
        lifecycle="completed" if episode.ended_at is not None else "active",
        started_at=_iso(episode.started_at),
        ended_at=_iso(episode.ended_at) if episode.ended_at is not None else None,
        completed_duration_seconds=(
            (episode.ended_at - episode.started_at).total_seconds() if episode.ended_at is not None else None
        ),
        observed_duration_through_latest_evidence_seconds=(observed_through - episode.started_at).total_seconds(),
        termination_reason=episode.termination_reason.value if episode.termination_reason is not None else None,
        total_sample_count=episode.total_sample_count,
        retained_sample_count=episode.retained_sample_count,
        samples_truncated=episode.samples_truncated,
        temperature=temperature,
        target=TargetEvidenceV1(
            initial_target_temperature=episode.initial_target_temperature,
            final_target_temperature=episode.current_target_temperature,
            target_changed=assessment.evidence.target_changed if assessment is not None else None,
            start_target_relative_error=start_error,
            end_target_relative_error=end_error,
        ),
        actuators=projected_actuators,
        actuator_count_truncated=len(ordered_actuators) > MAX_PROJECTED_ACTUATORS,
        source=_source(latest_sample.source_observation if latest_sample is not None else None),
    )


def _temperature_evidence(
    episode: HeatingEpisode,
    assessment: HeatingPerformanceAssessment | None,
) -> TemperatureEvidenceV1:
    quality_counts = Counter(sample.zone_temperature.quality for sample in episode.samples)
    valid: list[tuple[datetime, float]] = []
    values_by_timestamp: dict[datetime, float] = {}
    duplicates = 0
    conflicting = False
    non_monotonic = False
    previous: datetime | None = None
    for sample in episode.samples:
        observed = sample.zone_temperature
        if observed.quality is not ObservationQuality.VALID or observed.value is None or observed.observed_at is None:
            continue
        value = float(observed.value)
        if observed.observed_at in values_by_timestamp:
            if values_by_timestamp[observed.observed_at] == value:
                duplicates += 1
            else:
                conflicting = True
            continue
        if previous is not None and observed.observed_at < previous:
            non_monotonic = True
        values_by_timestamp[observed.observed_at] = value
        valid.append((observed.observed_at, value))
        previous = observed.observed_at
    comparable = len(valid) >= 2 and not conflicting and not non_monotonic
    first_at, first_value = valid[0] if valid else (None, None)
    latest_at, latest_value = valid[-1] if valid else (None, None)
    terminal_sample = episode.samples[-1] if episode.samples else None
    terminal_valid = (
        episode.ended_at is not None
        and terminal_sample is not None
        and terminal_sample.captured_at == episode.ended_at
        and terminal_sample.zone_temperature.quality is ObservationQuality.VALID
        and terminal_sample.zone_temperature.observed_at == episode.ended_at
        and terminal_sample.zone_temperature.value is not None
    )
    return TemperatureEvidenceV1(
        first_valid_temperature=first_value,
        first_valid_observed_at=_iso(first_at) if first_at is not None else None,
        latest_valid_temperature=latest_value,
        latest_valid_observed_at=_iso(latest_at) if latest_at is not None else None,
        terminal_temperature=(float(terminal_sample.zone_temperature.value) if terminal_valid else None),
        terminal_temperature_quality=(
            ObservationQuality.VALID.value if terminal_valid else ObservationQuality.UNKNOWN.value
        ),
        terminal_temperature_reason_code=(None if terminal_valid else "terminal_temperature_not_valid"),
        temperature_delta=(latest_value - first_value if comparable else None),
        observation_duration_seconds=((latest_at - first_at).total_seconds() if comparable else None),
        response_trend=(
            assessment.temperature_response.direction.value
            if assessment is not None and assessment.temperature_response is not None
            else "unknown"
        ),
        distinct_valid_measurement_count=len(valid),
        duplicate_valid_measurement_count=duplicates,
        excluded_quality_counts=tuple(
            QualityCountV1(quality=quality.value, count=quality_counts[quality])
            for quality in ObservationQuality
            if quality is not ObservationQuality.VALID
        ),
        conflicting_evidence=conflicting,
        non_monotonic_evidence=non_monotonic,
    )


def _actuator(observation: HeatDeliveryObservation) -> ActuatorEvidenceV1:
    return ActuatorEvidenceV1(
        actuator_id=observation.actuator_id.value,
        mode=observation.mode.value,
        capabilities=tuple(
            field.name for field in fields(HeatDeliveryCapabilities) if getattr(observation.capabilities, field.name)
        ),
        requested_command=_command(observation.last_requested_command),
        successfully_dispatched_command=_command(observation.last_successful_command),
        command_outcome=(observation.last_command_outcome.value if observation.last_command_outcome else None),
        command_evidence_at=(
            _iso(observation.last_command_timestamp) if observation.last_command_timestamp is not None else None
        ),
        reported_target_temperature=_observed(observation.reported_target_temperature),
        reported_local_temperature=_observed(observation.reported_local_temperature),
        reported_position=_observed(observation.reported_position),
        reported_binary_open=_observed(observation.reported_binary_open),
        reported_activity=_observed(observation.reported_activity),
    )


def _source(observation: Any | None) -> SourceEvidenceV1:
    if observation is None:
        return SourceEvidenceV1(
            requested_permission=None,
            successfully_dispatched_permission=None,
            successful_dispatch_at=None,
            physical_heat_available=ObservedValueDiagnosticsV1(
                value=None,
                quality=ObservationQuality.UNKNOWN.value,
                reason_code="physical_source_state_not_reported",
                observed_at=None,
            ),
        )
    return SourceEvidenceV1(
        requested_permission=(
            observation.last_requested_action.value if observation.last_requested_action is not None else None
        ),
        successfully_dispatched_permission=(
            observation.last_successful_dispatch_action.value
            if observation.last_successful_dispatch_action is not None
            else None
        ),
        successful_dispatch_at=(
            _iso(observation.last_successful_dispatch_at)
            if observation.last_successful_dispatch_at is not None
            else None
        ),
        physical_heat_available=_observed(
            observation.reported_heat_available,
            unknown_reason="physical_source_state_not_reported",
        ),
    )


def _assessment(assessment: HeatingPerformanceAssessment | None) -> AssessmentDiagnosticsV1 | None:
    if assessment is None:
        return None
    response = assessment.temperature_response
    reasons = tuple(reason.value for reason in assessment.reasons)
    return AssessmentDiagnosticsV1(
        zone_id=assessment.zone_id.value,
        episode_started_at=_iso(assessment.episode_started_at),
        episode_ended_at=_iso(assessment.episode_ended_at),
        assessed_at=_iso(assessment.assessed_at),
        status=assessment.status.value,
        reason_codes=reasons,
        termination_reason=assessment.termination_reason.value,
        criteria=AssessmentCriteriaV1(
            stable_temperature_tolerance=assessment.criteria.stable_temperature_tolerance,
            target_change_tolerance=assessment.criteria.target_change_tolerance,
        ),
        temperature_response=(
            TemperatureResponseV1(
                first_temperature=response.first_temperature,
                first_observed_at=_iso(response.first_observed_at),
                last_temperature=response.last_temperature,
                last_observed_at=_iso(response.last_observed_at),
                temperature_change=response.temperature_change,
                observation_duration_seconds=response.observation_duration.total_seconds(),
                temperature_change_per_hour=response.temperature_change_per_hour,
                direction=response.direction.value,
            )
            if response is not None
            else None
        ),
        evidence=AssessmentEvidenceV1(
            total_sample_count=assessment.evidence.total_sample_count,
            retained_sample_count=assessment.evidence.retained_sample_count,
            samples_truncated=assessment.evidence.samples_truncated,
            distinct_valid_measurement_count=assessment.evidence.distinct_valid_measurement_count,
            duplicate_valid_measurement_count=assessment.evidence.duplicate_valid_measurement_count,
            zone_temperature_quality_counts=tuple(
                QualityCountV1(quality=item.quality.value, count=item.count)
                for item in assessment.evidence.zone_temperature_quality_counts
            ),
            target_changed=assessment.evidence.target_changed,
            actuator_command_evidence_count=assessment.evidence.actuator_command_evidence_count,
            actuator_reported_value_count=assessment.evidence.actuator_reported_value_count,
            source_permission_evidence_count=assessment.evidence.source_permission_evidence_count,
            source_availability_quality_counts=tuple(
                QualityCountV1(quality=item.quality.value, count=item.count)
                for item in assessment.evidence.source_availability_quality_counts
            ),
        ),
        conflicting_evidence=(HeatingPerformanceAssessmentReason.CONFLICTING_MEASUREMENTS.value in reasons),
        non_monotonic_evidence=(HeatingPerformanceAssessmentReason.NON_MONOTONIC_TIMESTAMPS.value in reasons),
        history_truncated=(HeatingPerformanceAssessmentReason.HISTORY_TRUNCATED.value in reasons),
    )


def _observed(
    observed: ObservedValue[Any],
    *,
    unknown_reason: str = "value_not_reported",
) -> ObservedValueDiagnosticsV1:
    value = observed.value.value if hasattr(observed.value, "value") else observed.value
    reason_by_quality = {
        ObservationQuality.UNKNOWN: unknown_reason,
        ObservationQuality.VALID: None,
        ObservationQuality.STALE: "reported_value_stale",
        ObservationQuality.DEGRADED: "reported_value_degraded",
        ObservationQuality.CONFLICTING: "reported_value_conflicting",
        ObservationQuality.UNSUPPORTED: "capability_unsupported",
    }
    return ObservedValueDiagnosticsV1(
        value=value,
        quality=observed.quality.value,
        reason_code=reason_by_quality[observed.quality],
        observed_at=_iso(observed.observed_at) if observed.observed_at is not None else None,
    )


def _command(command: HeatDeliveryCommand | None) -> CommandEvidenceV1 | None:
    if command is None:
        return None
    return CommandEvidenceV1(
        kind=command.kind.value,
        value=command.value,
        requested_at=_iso(command.requested_at),
    )


def _observation_error(error: HeatingEpisodeObservationErrorEvidence) -> DiagnosticErrorEvidenceV1:
    return DiagnosticErrorEvidenceV1(
        component="observation",
        reason_code="observation_failed",
        exception_type=error.exception_type,
        zone_id=error.zone_id.value if error.zone_id is not None else None,
        evidence_at=_iso(error.evidence_at),
    )


def _latest_episodes(episodes: tuple[HeatingEpisode, ...]) -> dict[ZoneId, HeatingEpisode]:
    latest: dict[ZoneId, HeatingEpisode] = {}
    for episode in episodes:
        current = latest.get(episode.zone_id)
        if current is None or episode.started_at > current.started_at:
            latest[episode.zone_id] = episode
    return latest


def _latest_assessments(
    assessments: tuple[HeatingPerformanceAssessment, ...],
) -> dict[ZoneId, HeatingPerformanceAssessment]:
    latest: dict[ZoneId, HeatingPerformanceAssessment] = {}
    for assessment in assessments:
        current = latest.get(assessment.zone_id)
        if current is None or assessment.episode_started_at > current.episode_started_at:
            latest[assessment.zone_id] = assessment
    return latest


def _pipeline_health_code(
    *,
    projection_error: DiagnosticErrorEvidenceV1 | None,
    dropped_count: int,
    assessment_errors: tuple[DiagnosticErrorEvidenceV1, ...],
    observation_errors: tuple[DiagnosticErrorEvidenceV1, ...],
    pending_count: int,
) -> str:
    if projection_error is not None:
        return "unavailable"
    if dropped_count:
        return "dropping"
    if assessment_errors or observation_errors:
        return "degraded"
    if pending_count:
        return "pending"
    return "healthy"


def _latest_evidence_timestamp(
    *,
    active_episodes: tuple[HeatingEpisode, ...],
    completed_episodes: tuple[HeatingEpisode, ...],
    assessments: tuple[HeatingPerformanceAssessment, ...],
    observation_errors: tuple[HeatingEpisodeObservationErrorEvidence, ...],
    monitor: ShadowPerformanceMonitorSnapshot,
    projection_error: DiagnosticErrorEvidenceV1 | None,
) -> datetime | None:
    candidates: list[datetime] = []
    for episode in (*active_episodes, *completed_episodes):
        latest_episode_evidence = episode.samples[-1].captured_at if episode.samples else episode.started_at
        candidates.append(episode.ended_at or latest_episode_evidence)
    candidates.extend(assessment.assessed_at for assessment in assessments)
    candidates.extend(error.evidence_at for error in observation_errors)
    candidates.extend(error.episode_ended_at for error in monitor.errors)
    if monitor.latest_drop is not None:
        candidates.append(monitor.latest_drop.episode_ended_at)
    if projection_error is not None and projection_error.evidence_at is not None:
        candidates.append(datetime.fromisoformat(projection_error.evidence_at))
    return max(candidates) if candidates else None


def _iso(value: datetime) -> str:
    return value.isoformat()
