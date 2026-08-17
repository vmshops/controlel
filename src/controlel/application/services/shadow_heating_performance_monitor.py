"""Bounded shadow-only storage for deterministic episode assessments."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from threading import Lock
from typing import Protocol

from controlel.domain.heat_delivery import (
    HeatingEpisode,
    HeatingPerformanceAssessment,
    HeatingPerformanceSnapshot,
)
from controlel.domain.value_objects.zone_id import ZoneId

from .heating_performance_assessor import HeatingPerformanceAssessor
from .heating_performance_monitor import HeatingPerformanceMonitor

MAX_RETAINED_HEATING_PERFORMANCE_ASSESSMENTS = 20


class EpisodeAssessor(Protocol):
    def assess(self, episode: HeatingEpisode) -> HeatingPerformanceAssessment: ...


class PendingAssessmentDropReason(StrEnum):
    CAPACITY_REACHED = "capacity_reached"


@dataclass(frozen=True)
class DroppedPendingAssessmentEvidence:
    zone_id: ZoneId
    episode_started_at: datetime
    episode_ended_at: datetime
    reason: PendingAssessmentDropReason


@dataclass(frozen=True)
class ShadowAssessmentErrorEvidence:
    zone_id: ZoneId
    episode_started_at: datetime
    episode_ended_at: datetime
    exception_type: str


@dataclass(frozen=True)
class ShadowPerformanceMonitorSnapshot:
    enabled: bool
    pending_assessment_count: int
    assessments: tuple[HeatingPerformanceAssessment, ...]
    assessment_capacity: int
    dropped_pending_assessment_count: int
    latest_drop: DroppedPendingAssessmentEvidence | None
    errors: tuple[ShadowAssessmentErrorEvidence, ...]


class ShadowHeatingPerformanceMonitor:
    """Assess completed episodes without exposing any control output."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_assessments: int = MAX_RETAINED_HEATING_PERFORMANCE_ASSESSMENTS,
        max_pending_episodes: int = 20,
        assessor: EpisodeAssessor | None = None,
        progress_monitor: HeatingPerformanceMonitor | None = None,
    ) -> None:
        if max_assessments <= 0:
            raise ValueError("max_assessments must be positive")
        if max_assessments > MAX_RETAINED_HEATING_PERFORMANCE_ASSESSMENTS:
            raise ValueError(f"max_assessments must not exceed {MAX_RETAINED_HEATING_PERFORMANCE_ASSESSMENTS}")
        if max_pending_episodes <= 0:
            raise ValueError("max_pending_episodes must be positive")
        self.enabled = enabled
        self._assessor = assessor or HeatingPerformanceAssessor()
        self._progress_monitor = progress_monitor or HeatingPerformanceMonitor()
        self._max_pending_episodes = max_pending_episodes
        self._pending: deque[HeatingEpisode] = deque()
        self._assessments: deque[HeatingPerformanceAssessment] = deque(maxlen=max_assessments)
        self._errors: dict[ZoneId, str] = {}
        self._error_evidence: dict[ZoneId, ShadowAssessmentErrorEvidence] = {}
        self._dropped_pending_assessment_count = 0
        self._last_dropped_pending_assessment: DroppedPendingAssessmentEvidence | None = None
        self._lock = Lock()
        self._drain_lock = Lock()

    def submit_observation(self, episode: HeatingEpisode) -> None:
        """Submit one immutable episode view for passive live-window assessment."""

        if self.enabled:
            self._progress_monitor.submit(episode)

    def submit_episode(self, episode: HeatingEpisode) -> None:
        if not self.enabled:
            return
        if episode.ended_at is None:
            raise ValueError("only completed episodes may enter shadow assessment")
        with self._lock:
            if len(self._pending) == self._max_pending_episodes:
                dropped = self._pending.popleft()
                self._dropped_pending_assessment_count += 1
                self._last_dropped_pending_assessment = DroppedPendingAssessmentEvidence(
                    zone_id=dropped.zone_id,
                    episode_started_at=dropped.started_at,
                    episode_ended_at=dropped.ended_at,
                    reason=PendingAssessmentDropReason.CAPACITY_REACHED,
                )
            self._pending.append(episode)

    def assess_pending(self) -> tuple[HeatingPerformanceAssessment, ...]:
        """Assess queued episodes explicitly, outside control execution."""

        with self._drain_lock:
            self._progress_monitor.assess_pending()
            completed = []
            while True:
                with self._lock:
                    if not self._pending:
                        return tuple(completed)
                    episode = self._pending.popleft()
                try:
                    assessment = self._assessor.assess(episode)
                except Exception as error:
                    with self._lock:
                        self._errors[episode.zone_id] = f"{type(error).__name__}: {error}"
                        self._error_evidence[episode.zone_id] = ShadowAssessmentErrorEvidence(
                            zone_id=episode.zone_id,
                            episode_started_at=episode.started_at,
                            episode_ended_at=episode.ended_at,
                            exception_type=type(error).__name__,
                        )
                    continue
                with self._lock:
                    self._errors.pop(episode.zone_id, None)
                    self._error_evidence.pop(episode.zone_id, None)
                    self._assessments.append(assessment)
                completed.append(assessment)

    @property
    def assessments(self) -> tuple[HeatingPerformanceAssessment, ...]:
        with self._lock:
            return tuple(self._assessments)

    @property
    def errors(self) -> dict[ZoneId, str]:
        with self._lock:
            return dict(self._errors)

    @property
    def error_evidence(self) -> tuple[ShadowAssessmentErrorEvidence, ...]:
        with self._lock:
            return tuple(
                self._error_evidence[zone_id] for zone_id in sorted(self._error_evidence, key=lambda item: item.value)
            )

    @property
    def pending_episode_count(self) -> int:
        with self._lock:
            completed_count = len(self._pending)
        return completed_count + self._progress_monitor.pending_observation_count

    @property
    def performance_snapshot(self) -> HeatingPerformanceSnapshot:
        """Return the bounded M31C.1 diagnostics/read boundary."""

        return self._progress_monitor.snapshot()

    @property
    def retained_assessment_count(self) -> int:
        with self._lock:
            return len(self._assessments)

    @property
    def assessment_capacity(self) -> int:
        with self._lock:
            return self._assessments.maxlen or 0

    @property
    def dropped_pending_assessment_count(self) -> int:
        with self._lock:
            return self._dropped_pending_assessment_count

    @property
    def last_dropped_pending_assessment(self) -> DroppedPendingAssessmentEvidence | None:
        with self._lock:
            return self._last_dropped_pending_assessment

    def diagnostic_snapshot(self) -> ShadowPerformanceMonitorSnapshot:
        """Capture one consistent, immutable, read-only monitor view."""

        with self._lock:
            return ShadowPerformanceMonitorSnapshot(
                enabled=self.enabled,
                pending_assessment_count=len(self._pending),
                assessments=tuple(self._assessments),
                assessment_capacity=self._assessments.maxlen or 0,
                dropped_pending_assessment_count=self._dropped_pending_assessment_count,
                latest_drop=self._last_dropped_pending_assessment,
                errors=tuple(
                    self._error_evidence[zone_id]
                    for zone_id in sorted(self._error_evidence, key=lambda item: item.value)
                ),
            )
