"""Bounded passive monitoring for live heating-performance assessment."""

from collections import deque
from dataclasses import replace
from threading import Lock
from typing import Any, Protocol

from controlel.domain.heat_delivery import (
    HeatingEpisode,
    HeatingPerformanceAssessmentCriteria,
    HeatingPerformanceAssessmentErrorEvidence,
    HeatingPerformanceAssessmentReason,
    HeatingPerformanceSnapshot,
    HeatingPerformanceStatus,
    HeatingPerformanceWindowAssessment,
    ZoneHeatingPerformanceState,
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


class HeatingPerformanceMonitor:
    """Coalesce immutable episode snapshots and assess them outside control execution."""

    def __init__(
        self,
        *,
        criteria: HeatingPerformanceAssessmentCriteria | None = None,
        assessment_capacity: int = DEFAULT_HEATING_PERFORMANCE_ASSESSMENT_CAPACITY,
        pending_zone_capacity: int = DEFAULT_HEATING_PERFORMANCE_PENDING_ZONE_CAPACITY,
        assessor: ProgressAssessor | None = None,
    ) -> None:
        if not 1 <= assessment_capacity <= MAX_HEATING_PERFORMANCE_ASSESSMENT_CAPACITY:
            raise ValueError(f"assessment_capacity must be between 1 and {MAX_HEATING_PERFORMANCE_ASSESSMENT_CAPACITY}")
        if not 1 <= pending_zone_capacity <= MAX_HEATING_PERFORMANCE_PENDING_ZONE_CAPACITY:
            raise ValueError(
                f"pending_zone_capacity must be between 1 and {MAX_HEATING_PERFORMANCE_PENDING_ZONE_CAPACITY}"
            )
        selected_criteria = criteria or HeatingPerformanceAssessmentCriteria()
        self._assessor = assessor or HeatingPerformanceAssessor(selected_criteria)
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
