"""Application boundary for passive heating diagnostics projection."""

from dataclasses import dataclass, replace
from threading import Lock
from typing import Protocol

from controlel.application.services.heating_diagnostics_projector import (
    HeatingDiagnosticsProjector,
)
from controlel.application.services.heating_episode_observer import (
    HeatingEpisodeObservationErrorEvidence,
)
from controlel.application.services.shadow_heating_performance_monitor import (
    ShadowPerformanceMonitorSnapshot,
)
from controlel.application.state.heating_diagnostics import (
    DiagnosticErrorEvidenceV1,
    HeatingDiagnosticsSnapshotV1,
)
from controlel.domain.heat_delivery import HeatingEpisode
from controlel.domain.value_objects.zone_id import ZoneId


class DiagnosticsProjector(Protocol):
    """Structural contract used by the diagnostics boundary."""

    def project(self, **kwargs: object) -> HeatingDiagnosticsSnapshotV1: ...


@dataclass(frozen=True)
class HeatingDiagnosticsProjectionResult:
    """Normalized application result safe for adapter consumption."""

    snapshot: HeatingDiagnosticsSnapshotV1
    failure_exception_type: str | None = None


class HeatingDiagnosticsBoundary:
    """Collect and project runtime evidence without exposing domain episodes."""

    def __init__(self, projector: DiagnosticsProjector | None = None) -> None:
        self._projector = projector or HeatingDiagnosticsProjector()
        self._active_episodes: tuple[HeatingEpisode, ...] = ()
        self._completed_episodes: tuple[HeatingEpisode, ...] = ()
        self._observation_errors: tuple[HeatingEpisodeObservationErrorEvidence, ...] = ()
        self._lock = Lock()

    def project(
        self,
        *,
        runtime: object,
        zone_ids: tuple[ZoneId, ...],
        current: HeatingDiagnosticsSnapshotV1,
        refresh_runtime_evidence: bool,
    ) -> HeatingDiagnosticsProjectionResult:
        """Return one immutable snapshot, containing projection failures."""

        monitor = _empty_monitor_snapshot()
        active: tuple[HeatingEpisode, ...] = ()
        completed: tuple[HeatingEpisode, ...] = ()
        observation_errors: tuple[HeatingEpisodeObservationErrorEvidence, ...] = ()
        try:
            with self._lock:
                if refresh_runtime_evidence:
                    observer = getattr(runtime, "heating_episode_observer", None)
                    captured_active = tuple(getattr(observer, "active_episodes", ()))
                    captured_completed = tuple(getattr(observer, "completed_episodes", ()))
                    per_zone = getattr(runtime, "heating_episode_observation_error_evidence", {})
                    global_error = getattr(runtime, "heating_episode_observation_global_error_evidence", None)
                    captured_errors = tuple(
                        per_zone[zone_id] for zone_id in sorted(per_zone, key=lambda item: item.value)
                    )
                    if global_error is not None:
                        captured_errors = (*captured_errors, global_error)
                    self._active_episodes = captured_active
                    self._completed_episodes = captured_completed
                    self._observation_errors = captured_errors
                active = self._active_episodes
                completed = self._completed_episodes
                observation_errors = self._observation_errors
            monitor = _monitor_snapshot(runtime)
            snapshot = self._projector.project(
                zone_ids=zone_ids,
                active_episodes=active,
                completed_episodes=completed,
                monitor=monitor,
                observation_errors=observation_errors,
            )
        except Exception as error:
            exception_type = type(error).__name__
            evidence_at = (
                _evidence_timestamp(
                    active=active,
                    completed=completed,
                    monitor=monitor,
                    observation_errors=observation_errors,
                )
                or current.updated_at
            )
            projection_error = DiagnosticErrorEvidenceV1(
                component="diagnostic_projection",
                reason_code="diagnostic_projection_failed",
                exception_type=exception_type,
                zone_id=None,
                evidence_at=evidence_at,
            )
            snapshot = replace(
                current,
                updated_at=evidence_at,
                pipeline=replace(
                    current.pipeline,
                    health_code="unavailable",
                    projection_error=projection_error,
                ),
            )
            return HeatingDiagnosticsProjectionResult(
                snapshot=snapshot,
                failure_exception_type=exception_type,
            )
        return HeatingDiagnosticsProjectionResult(snapshot=snapshot)


def _monitor_snapshot(runtime: object) -> ShadowPerformanceMonitorSnapshot:
    monitor = getattr(runtime, "heating_performance_monitor", None)
    diagnostic_snapshot = getattr(monitor, "diagnostic_snapshot", None)
    if callable(diagnostic_snapshot):
        return diagnostic_snapshot()
    return _empty_monitor_snapshot()


def _empty_monitor_snapshot() -> ShadowPerformanceMonitorSnapshot:
    return ShadowPerformanceMonitorSnapshot(
        enabled=False,
        pending_assessment_count=0,
        assessments=(),
        assessment_capacity=0,
        dropped_pending_assessment_count=0,
        latest_drop=None,
        errors=(),
    )


def _evidence_timestamp(
    *,
    active: tuple[HeatingEpisode, ...],
    completed: tuple[HeatingEpisode, ...],
    monitor: ShadowPerformanceMonitorSnapshot,
    observation_errors: tuple[HeatingEpisodeObservationErrorEvidence, ...],
) -> str | None:
    candidates = []
    for episode in (*active, *completed):
        candidates.append(
            episode.ended_at or (episode.samples[-1].captured_at if episode.samples else episode.started_at)
        )
    candidates.extend(assessment.assessed_at for assessment in monitor.assessments)
    candidates.extend(error.evidence_at for error in observation_errors)
    candidates.extend(error.episode_ended_at for error in monitor.errors)
    if monitor.latest_drop is not None:
        candidates.append(monitor.latest_drop.episode_ended_at)
    return max(candidates).isoformat() if candidates else None
