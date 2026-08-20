"""Bounded passive monitoring for live heating-performance assessment."""

from collections import deque
from dataclasses import replace
from datetime import datetime
from threading import Lock
from typing import Any, Protocol

from controlel.domain.heat_delivery import (
    HeatingAnomalyCategory,
    HeatingAnomalyConfidence,
    HeatingAnomalyEvidence,
    HeatingAnomalyEvidenceItem,
    HeatingAnomalyLifecycle,
    HeatingAnomalyObservation,
    HeatingAnomalySeverity,
    HeatingEpisode,
    HeatingPerformanceAssessmentCriteria,
    HeatingPerformanceAssessmentErrorEvidence,
    HeatingPerformanceAssessmentReason,
    HeatingPerformanceSnapshot,
    HeatingPerformanceStatus,
    HeatingPerformanceWindowAssessment,
    ZoneHeatingPerformanceState,
    heating_anomaly_id,
    heating_episode_id,
)
from controlel.domain.value_objects.zone_id import ZoneId

from .heating_performance_assessor import HeatingPerformanceAssessor

DEFAULT_HEATING_PERFORMANCE_ASSESSMENT_CAPACITY = 20
MAX_HEATING_PERFORMANCE_ASSESSMENT_CAPACITY = 200
DEFAULT_HEATING_PERFORMANCE_PENDING_ZONE_CAPACITY = 64
MAX_HEATING_PERFORMANCE_PENDING_ZONE_CAPACITY = 64
MAX_HEATING_PERFORMANCE_ERRORS = 32


class ProgressAssessor(Protocol):
    """Structural boundary for deterministic live-window assessment."""

    criteria: HeatingPerformanceAssessmentCriteria

    def assess_progress(self, episode: HeatingEpisode) -> HeatingPerformanceWindowAssessment: ...


class HeatingAnomalyEventRecorder(Protocol):
    """Optional diagnostics-only sink for anomaly lifecycle transitions."""

    def heating_anomaly(self, anomaly: HeatingAnomalyObservation) -> None: ...


class HeatingPerformanceMonitor:
    """Coalesce immutable episode snapshots and assess them outside control execution."""

    def __init__(
        self,
        *,
        criteria: HeatingPerformanceAssessmentCriteria | None = None,
        assessment_capacity: int = DEFAULT_HEATING_PERFORMANCE_ASSESSMENT_CAPACITY,
        pending_zone_capacity: int = DEFAULT_HEATING_PERFORMANCE_PENDING_ZONE_CAPACITY,
        assessor: ProgressAssessor | None = None,
        anomaly_event_recorder: HeatingAnomalyEventRecorder | None = None,
    ) -> None:
        if not 1 <= assessment_capacity <= MAX_HEATING_PERFORMANCE_ASSESSMENT_CAPACITY:
            raise ValueError(f"assessment_capacity must be between 1 and {MAX_HEATING_PERFORMANCE_ASSESSMENT_CAPACITY}")
        if not 1 <= pending_zone_capacity <= MAX_HEATING_PERFORMANCE_PENDING_ZONE_CAPACITY:
            raise ValueError(
                f"pending_zone_capacity must be between 1 and {MAX_HEATING_PERFORMANCE_PENDING_ZONE_CAPACITY}"
            )
        selected_criteria = criteria or HeatingPerformanceAssessmentCriteria()
        self._assessor = assessor or HeatingPerformanceAssessor(selected_criteria)
        self._anomaly_event_recorder = anomaly_event_recorder
        self.criteria = self._assessor.criteria
        self._assessment_capacity = assessment_capacity
        self._pending_zone_capacity = pending_zone_capacity
        self._pending: dict[ZoneId, HeatingEpisode] = {}
        self._pending_dropped = 0
        self._assessments: deque[HeatingPerformanceWindowAssessment] = deque(maxlen=assessment_capacity)
        self._total_assessments = 0
        self._zones: dict[ZoneId, ZoneHeatingPerformanceState] = {}
        self._problem_status: dict[ZoneId, tuple[str, HeatingPerformanceStatus]] = {}
        self._recovery_counts: dict[ZoneId, int] = {}
        self._last_recovery_assessment_id: dict[ZoneId, str] = {}
        self._errors: dict[ZoneId, HeatingPerformanceAssessmentErrorEvidence] = {}
        self._active_anomalies: dict[ZoneId, HeatingAnomalyObservation] = {}
        self._anomaly_transitions: deque[HeatingAnomalyObservation] = deque(maxlen=assessment_capacity)
        self._total_anomaly_transitions = 0
        self._lock = Lock()
        self._drain_lock = Lock()

    def submit(self, episode: HeatingEpisode) -> None:
        """Coalesce the latest immutable episode snapshot for one zone."""

        with self._lock:
            if episode.zone_id not in self._pending and len(self._pending) == self._pending_zone_capacity:
                oldest_zone = next(iter(self._pending))
                del self._pending[oldest_zone]
                self._pending_dropped += 1
            self._pending[episode.zone_id] = episode

    def assess_pending(self) -> tuple[HeatingPerformanceWindowAssessment, ...]:
        """Assess all currently pending zones without polling or command access."""

        with self._drain_lock:
            completed = []
            while True:
                with self._lock:
                    if not self._pending:
                        return tuple(completed)
                    zone_id = next(iter(self._pending))
                    episode = self._pending.pop(zone_id)
                try:
                    raw = self._assessor.assess_progress(episode)
                except Exception as error:
                    with self._lock:
                        self._errors[zone_id] = HeatingPerformanceAssessmentErrorEvidence(
                            zone_id=zone_id,
                            heating_episode_id=heating_episode_id(zone_id, episode.started_at),
                            evidence_at=(episode.samples[-1].captured_at if episode.samples else episode.started_at),
                            exception_type=type(error).__name__,
                        )
                        self._trim_errors()
                    continue
                with self._lock:
                    assessment = self._apply_recovery(raw)
                    try:
                        anomaly_transitions = self._observe_anomaly(
                            raw=raw,
                            assessment=assessment,
                            episode_active=episode.ended_at is None,
                        )
                    except Exception:
                        anomaly_transitions = ()
                    self._errors.pop(zone_id, None)
                    self._total_assessments += 1
                    self._assessments.append(assessment)
                    self._zones[zone_id] = ZoneHeatingPerformanceState(
                        zone_id=zone_id,
                        heating_episode_id=assessment.heating_episode_id,
                        active_heating_episode_id=(assessment.heating_episode_id if episode.ended_at is None else None),
                        current=assessment,
                        recovery_confirmation_count=self._recovery_counts.get(zone_id, 0),
                    )
                for transition in anomaly_transitions:
                    self._record_anomaly_transition(transition)
                completed.append(assessment)

    def snapshot(self) -> HeatingPerformanceSnapshot:
        """Return one immutable bounded diagnostics/read snapshot."""

        with self._lock:
            assessments = tuple(self._assessments)
            return HeatingPerformanceSnapshot(
                schema_version=1,
                assessment_capacity=self._assessment_capacity,
                total_assessments_emitted=self._total_assessments,
                dropped_assessment_count=max(0, self._total_assessments - len(assessments)),
                pending_zone_capacity=self._pending_zone_capacity,
                pending_observation_count=len(self._pending),
                pending_observations_dropped=self._pending_dropped,
                zones=tuple(self._zones[zone_id] for zone_id in sorted(self._zones, key=lambda item: item.value)),
                assessments=assessments,
                errors=tuple(self._errors[zone_id] for zone_id in sorted(self._errors, key=lambda item: item.value)),
                total_anomaly_transitions_emitted=self._total_anomaly_transitions,
                dropped_anomaly_transition_count=max(
                    0,
                    self._total_anomaly_transitions - len(self._anomaly_transitions),
                ),
                active_anomalies=tuple(sorted(self._active_anomalies.values(), key=lambda item: item.anomaly_id)),
                anomaly_transitions=tuple(self._anomaly_transitions),
            )

    @property
    def pending_observation_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def _apply_recovery(self, raw: HeatingPerformanceWindowAssessment) -> HeatingPerformanceWindowAssessment:
        zone_id = raw.zone_id
        previous = self._problem_status.get(zone_id)
        if previous is not None and previous[0] != raw.heating_episode_id:
            self._problem_status.pop(zone_id, None)
            self._recovery_counts.pop(zone_id, None)
            self._last_recovery_assessment_id.pop(zone_id, None)
            previous = None
        if raw.status in {HeatingPerformanceStatus.DEGRADED, HeatingPerformanceStatus.ANOMALOUS}:
            self._problem_status[zone_id] = (raw.heating_episode_id, raw.status)
            self._recovery_counts[zone_id] = 0
            self._last_recovery_assessment_id.pop(zone_id, None)
            return raw
        if raw.status is HeatingPerformanceStatus.INSUFFICIENT_EVIDENCE:
            self._recovery_counts[zone_id] = 0
            self._last_recovery_assessment_id.pop(zone_id, None)
            return raw
        if raw.status is not HeatingPerformanceStatus.NORMAL or previous is None:
            self._recovery_counts[zone_id] = 0
            return raw

        confirmations = self._recovery_counts.get(zone_id, 0)
        if self._last_recovery_assessment_id.get(zone_id) != raw.assessment_id:
            confirmations += 1
            self._last_recovery_assessment_id[zone_id] = raw.assessment_id
        self._recovery_counts[zone_id] = confirmations
        if confirmations < self.criteria.recovery_confirmation_count:
            return replace(
                raw,
                status=previous[1],
                reason=HeatingPerformanceAssessmentReason.RECOVERY_CONFIRMATION_PENDING,
            )
        self._problem_status.pop(zone_id, None)
        self._recovery_counts[zone_id] = 0
        self._last_recovery_assessment_id.pop(zone_id, None)
        return replace(
            raw,
            status=HeatingPerformanceStatus.RECOVERED,
            reason=HeatingPerformanceAssessmentReason.PERFORMANCE_RECOVERED,
        )

    def _trim_errors(self) -> None:
        while len(self._errors) > MAX_HEATING_PERFORMANCE_ERRORS:
            del self._errors[next(iter(self._errors))]

    def _observe_anomaly(
        self,
        *,
        raw: HeatingPerformanceWindowAssessment,
        assessment: HeatingPerformanceWindowAssessment,
        episode_active: bool,
    ) -> tuple[HeatingAnomalyObservation, ...]:
        """Update passive anomaly lifecycle state from one completed assessment."""

        zone_id = raw.zone_id
        current = self._active_anomalies.get(zone_id)
        transitions: list[HeatingAnomalyObservation] = []
        if current is not None and current.heating_episode_id != raw.heating_episode_id:
            observation_ended = _observation_ended_anomaly(
                current,
                ended_at=raw.assessed_at,
                lifecycle_reason_code="heating_episode_replaced",
            )
            transitions.append(observation_ended)
            self._retain_anomaly_transition(observation_ended)
            del self._active_anomalies[zone_id]
            current = None

        if current is not None:
            if assessment.status is HeatingPerformanceStatus.RECOVERED:
                cleared = _cleared_anomaly(
                    current,
                    assessment=raw,
                    lifecycle_reason_code=assessment.reason.value,
                )
                transitions.append(cleared)
                self._retain_anomaly_transition(cleared)
                del self._active_anomalies[zone_id]
                return tuple(transitions)
            if not episode_active:
                observation_ended = _observation_ended_anomaly(
                    current,
                    ended_at=raw.assessed_at,
                    lifecycle_reason_code="heating_episode_ended",
                    assessment=raw,
                    anomaly_observed=_is_configured_performance_anomaly(raw),
                )
                transitions.append(observation_ended)
                self._retain_anomaly_transition(observation_ended)
                del self._active_anomalies[zone_id]
                return tuple(transitions)
            if _is_configured_performance_anomaly(raw) and raw.assessment_id != current.assessment_id:
                updated = replace(
                    current,
                    lifecycle=HeatingAnomalyLifecycle.ACTIVE,
                    last_observed_at=raw.assessed_at,
                    updated_at=raw.assessed_at,
                    assessment_id=raw.assessment_id,
                    lifecycle_reason_code="condition_continues",
                    evidence=_anomaly_evidence(raw, self.criteria),
                )
                self._active_anomalies[zone_id] = updated
            return tuple(transitions)

        if not episode_active or not _is_configured_performance_anomaly(raw):
            return tuple(transitions)
        started = _started_anomaly(raw, self.criteria)
        self._active_anomalies[zone_id] = started
        transitions.append(started)
        self._retain_anomaly_transition(started)
        return tuple(transitions)

    def _retain_anomaly_transition(self, transition: HeatingAnomalyObservation) -> None:
        self._total_anomaly_transitions += 1
        self._anomaly_transitions.append(transition)

    def _record_anomaly_transition(self, transition: HeatingAnomalyObservation) -> None:
        recorder = self._anomaly_event_recorder
        if recorder is None:
            return
        try:
            recorder.heating_anomaly(transition)
        except Exception:
            # Operational observations are best-effort and never fail assessment or control.
            pass


def heating_performance_snapshot_to_dict(snapshot: HeatingPerformanceSnapshot) -> dict[str, Any]:
    """Project the bounded read model into localization-neutral JSON primitives."""

    return {
        "schema_version": snapshot.schema_version,
        "assessment_capacity": snapshot.assessment_capacity,
        "total_assessments_emitted": snapshot.total_assessments_emitted,
        "dropped_assessment_count": snapshot.dropped_assessment_count,
        "pending_zone_capacity": snapshot.pending_zone_capacity,
        "pending_observation_count": snapshot.pending_observation_count,
        "pending_observations_dropped": snapshot.pending_observations_dropped,
        "zones": [
            {
                "zone_id": zone.zone_id.value,
                "heating_episode_id": zone.heating_episode_id,
                "active_heating_episode_id": zone.active_heating_episode_id,
                "recovery_confirmation_count": zone.recovery_confirmation_count,
                "current": _assessment_to_dict(zone.current),
            }
            for zone in snapshot.zones
        ],
        "assessments": [_assessment_to_dict(assessment) for assessment in snapshot.assessments],
        "errors": [
            {
                "zone_id": error.zone_id.value,
                "heating_episode_id": error.heating_episode_id,
                "evidence_at": error.evidence_at.isoformat(),
                "exception_type": error.exception_type,
            }
            for error in snapshot.errors
        ],
        "total_anomaly_transitions_emitted": snapshot.total_anomaly_transitions_emitted,
        "dropped_anomaly_transition_count": snapshot.dropped_anomaly_transition_count,
        "active_anomalies": [_anomaly_to_dict(anomaly) for anomaly in snapshot.active_anomalies],
        "anomaly_transitions": [_anomaly_to_dict(anomaly) for anomaly in snapshot.anomaly_transitions],
    }


def _assessment_to_dict(assessment: HeatingPerformanceWindowAssessment) -> dict[str, Any]:
    evidence = assessment.evidence
    return {
        "assessment_id": assessment.assessment_id,
        "assessment_type": assessment.assessment_type.value,
        "status": assessment.status.value,
        "assessed_at": assessment.assessed_at.isoformat(),
        "heating_episode_id": assessment.heating_episode_id,
        "zone_id": assessment.zone_id.value,
        "source_id": assessment.source_id,
        "reason_code": assessment.reason.value,
        "evidence": {
            "observation_window_started_at": evidence.observation_window_started_at.isoformat(),
            "observation_window_ended_at": evidence.observation_window_ended_at.isoformat(),
            "elapsed_duration_seconds": evidence.elapsed_duration.total_seconds(),
            "starting_temperature": evidence.starting_temperature,
            "latest_temperature": evidence.latest_temperature,
            "temperature_delta": evidence.temperature_delta,
            "target_temperature": evidence.target_temperature,
            "distance_to_target_at_start": evidence.distance_to_target_at_start,
            "distance_to_target_now": evidence.distance_to_target_now,
            "sample_count": evidence.sample_count,
            "duplicate_sample_count": evidence.duplicate_sample_count,
            "evidence_quality": evidence.evidence_quality.value,
            "source_observation_timestamps": [item.isoformat() for item in evidence.source_observation_timestamps],
            "history_truncated": evidence.history_truncated,
        },
        "parameters": {parameter.key: parameter.value for parameter in assessment.parameters},
    }


def _is_configured_performance_anomaly(assessment: HeatingPerformanceWindowAssessment) -> bool:
    return (
        assessment.status is HeatingPerformanceStatus.ANOMALOUS
        and assessment.reason is HeatingPerformanceAssessmentReason.TEMPERATURE_FALLING
    )


def _started_anomaly(
    assessment: HeatingPerformanceWindowAssessment,
    criteria: HeatingPerformanceAssessmentCriteria,
) -> HeatingAnomalyObservation:
    reason_code = assessment.reason.value
    return HeatingAnomalyObservation(
        anomaly_id=heating_anomaly_id(
            category=HeatingAnomalyCategory.PERFORMANCE,
            reason_code=reason_code,
            zone_id=assessment.zone_id,
            source_id=assessment.source_id,
            heating_episode_id=assessment.heating_episode_id,
        ),
        category=HeatingAnomalyCategory.PERFORMANCE,
        severity=HeatingAnomalySeverity.WARNING,
        confidence=HeatingAnomalyConfidence.HIGH,
        reason_code=reason_code,
        lifecycle=HeatingAnomalyLifecycle.STARTED,
        first_observed_at=assessment.assessed_at,
        last_observed_at=assessment.assessed_at,
        updated_at=assessment.assessed_at,
        cleared_at=None,
        zone_id=assessment.zone_id,
        source_id=assessment.source_id,
        heating_episode_id=assessment.heating_episode_id,
        assessment_id=assessment.assessment_id,
        lifecycle_reason_code="condition_detected",
        evidence=_anomaly_evidence(assessment, criteria),
    )


def _cleared_anomaly(
    current: HeatingAnomalyObservation,
    *,
    assessment: HeatingPerformanceWindowAssessment,
    lifecycle_reason_code: str,
) -> HeatingAnomalyObservation:
    return replace(
        current,
        lifecycle=HeatingAnomalyLifecycle.CLEARED,
        updated_at=assessment.assessed_at,
        cleared_at=assessment.assessed_at,
        assessment_id=assessment.assessment_id,
        lifecycle_reason_code=lifecycle_reason_code,
        evidence=_anomaly_evidence(assessment, None),
    )


def _observation_ended_anomaly(
    current: HeatingAnomalyObservation,
    *,
    ended_at: datetime,
    lifecycle_reason_code: str,
    assessment: HeatingPerformanceWindowAssessment | None = None,
    anomaly_observed: bool = False,
) -> HeatingAnomalyObservation:
    """End observation without asserting that the anomaly recovered."""

    return replace(
        current,
        lifecycle=HeatingAnomalyLifecycle.OBSERVATION_ENDED,
        last_observed_at=(ended_at if anomaly_observed else current.last_observed_at),
        updated_at=ended_at,
        cleared_at=None,
        assessment_id=(assessment.assessment_id if assessment is not None else current.assessment_id),
        lifecycle_reason_code=lifecycle_reason_code,
        evidence=(_anomaly_evidence(assessment, None) if assessment is not None else current.evidence),
    )


def _anomaly_evidence(
    assessment: HeatingPerformanceWindowAssessment,
    criteria: HeatingPerformanceAssessmentCriteria | None,
) -> HeatingAnomalyEvidence:
    evidence = assessment.evidence
    parameters = {parameter.key: parameter.value for parameter in assessment.parameters}
    values: dict[str, str | int | float | bool | None] = {
        "assessment_status": assessment.status.value,
        "assessment_type": assessment.assessment_type.value,
        "distance_to_target_at_start": evidence.distance_to_target_at_start,
        "distance_to_target_now": evidence.distance_to_target_now,
        "duplicate_sample_count": evidence.duplicate_sample_count,
        "elapsed_duration_seconds": evidence.elapsed_duration.total_seconds(),
        "evidence_quality": evidence.evidence_quality.value,
        "heating_permission_dispatch_at": parameters.get("permission_enabled_at"),
        "history_truncated": evidence.history_truncated,
        "latest_temperature": evidence.latest_temperature,
        "sample_count": evidence.sample_count,
        "starting_temperature": evidence.starting_temperature,
        "target_rebased": parameters.get("target_rebased"),
        "target_temperature": evidence.target_temperature,
        "temperature_delta": evidence.temperature_delta,
    }
    if criteria is not None:
        values.update(
            {
                "meaningful_temperature_change": criteria.meaningful_temperature_change,
                "minimum_observation_duration_seconds": criteria.minimum_observation_duration.total_seconds(),
                "minimum_valid_sample_count": criteria.minimum_valid_sample_count,
            }
        )
    return HeatingAnomalyEvidence(
        items=tuple(HeatingAnomalyEvidenceItem(key, value) for key, value in sorted(values.items())),
        source_observation_timestamps=evidence.source_observation_timestamps,
    )


def _anomaly_to_dict(anomaly: HeatingAnomalyObservation) -> dict[str, Any]:
    return {
        "anomaly_id": anomaly.anomaly_id,
        "category": anomaly.category.value,
        "severity": anomaly.severity.value,
        "confidence": anomaly.confidence.value,
        "reason_code": anomaly.reason_code,
        "lifecycle": anomaly.lifecycle.value,
        "first_observed_at": anomaly.first_observed_at.isoformat(),
        "last_observed_at": anomaly.last_observed_at.isoformat(),
        "updated_at": anomaly.updated_at.isoformat(),
        "cleared_at": anomaly.cleared_at.isoformat() if anomaly.cleared_at is not None else None,
        "zone_id": anomaly.zone_id.value if anomaly.zone_id is not None else None,
        "source_id": anomaly.source_id,
        "heating_episode_id": anomaly.heating_episode_id,
        "assessment_id": anomaly.assessment_id,
        "lifecycle_reason_code": anomaly.lifecycle_reason_code,
        "evidence": {
            "items": {item.key: item.value for item in anomaly.evidence.items},
            "source_observation_timestamps": [
                timestamp.isoformat() for timestamp in anomaly.evidence.source_observation_timestamps
            ],
        },
    }
