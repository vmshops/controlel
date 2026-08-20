"""Immutable observational heating-anomaly contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from controlel.domain.value_objects.zone_id import ZoneId

type HeatingAnomalyScalar = str | int | float | bool | None

MAX_HEATING_ANOMALY_EVIDENCE_ITEMS = 32


class HeatingAnomalyCategory(StrEnum):
    """Broad observation category; it is not a control classification."""

    MEASUREMENT = "measurement"
    BEHAVIOR = "behavior"
    ACTUATION = "actuation"
    PERFORMANCE = "performance"
    CONTEXTUAL = "contextual"
    UNKNOWN = "unknown"


class HeatingAnomalySeverity(StrEnum):
    """Observed significance, independent from notification preferences."""

    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    CRITICAL = "critical"


class HeatingAnomalyConfidence(StrEnum):
    """Qualitative confidence without invented statistical precision."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class HeatingAnomalyLifecycle(StrEnum):
    """Lifecycle of one stable anomaly identity."""

    STARTED = "started"
    ACTIVE = "active"
    CLEARED = "cleared"
    OBSERVATION_ENDED = "observation_ended"


@dataclass(frozen=True, slots=True)
class HeatingAnomalyEvidenceItem:
    """One bounded JSON-safe evidence value retained with an anomaly."""

    key: str
    value: HeatingAnomalyScalar

    def __post_init__(self) -> None:
        _identifier(self.key, "evidence key")
        if isinstance(self.value, float) and not isfinite(self.value):
            raise ValueError("evidence float values must be finite")
        if not isinstance(self.value, str | int | float | bool | type(None)):
            raise TypeError("evidence value must be a JSON-safe scalar")


@dataclass(frozen=True, slots=True)
class HeatingAnomalyEvidence:
    """Structured values plus the complete retained observation timestamps."""

    items: tuple[HeatingAnomalyEvidenceItem, ...]
    source_observation_timestamps: tuple[datetime, ...] = ()

    def __post_init__(self) -> None:
        keys = tuple(item.key for item in self.items)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("evidence items must have unique keys in deterministic sorted order")
        if len(self.items) > MAX_HEATING_ANOMALY_EVIDENCE_ITEMS:
            raise ValueError(f"evidence must contain at most {MAX_HEATING_ANOMALY_EVIDENCE_ITEMS} items")
        if not self.items and not self.source_observation_timestamps:
            raise ValueError("anomaly evidence must not be empty")
        if self.source_observation_timestamps != tuple(sorted(set(self.source_observation_timestamps))):
            raise ValueError("source observation timestamps must be unique and sorted")
        for timestamp in self.source_observation_timestamps:
            _aware(timestamp, "source_observation_timestamp")


@dataclass(frozen=True, slots=True)
class HeatingAnomalyObservation:
    """One passive anomaly lifecycle observation with retained evidence."""

    anomaly_id: str
    category: HeatingAnomalyCategory
    severity: HeatingAnomalySeverity
    confidence: HeatingAnomalyConfidence
    reason_code: str
    lifecycle: HeatingAnomalyLifecycle
    first_observed_at: datetime
    last_observed_at: datetime
    updated_at: datetime
    cleared_at: datetime | None
    zone_id: ZoneId | None
    source_id: str | None
    heating_episode_id: str | None
    assessment_id: str | None
    lifecycle_reason_code: str
    evidence: HeatingAnomalyEvidence

    def __post_init__(self) -> None:
        if not self.anomaly_id:
            raise ValueError("anomaly_id must not be empty")
        if self.assessment_id == "":
            raise ValueError("assessment_id must not be empty when present")
        if not isinstance(self.category, HeatingAnomalyCategory):
            raise TypeError("category must be a HeatingAnomalyCategory")
        if not isinstance(self.severity, HeatingAnomalySeverity):
            raise TypeError("severity must be a HeatingAnomalySeverity")
        if not isinstance(self.confidence, HeatingAnomalyConfidence):
            raise TypeError("confidence must be a HeatingAnomalyConfidence")
        if not isinstance(self.lifecycle, HeatingAnomalyLifecycle):
            raise TypeError("lifecycle must be a HeatingAnomalyLifecycle")
        _identifier(self.reason_code, "reason_code")
        _identifier(self.lifecycle_reason_code, "lifecycle_reason_code")
        for value, label in (
            (self.first_observed_at, "first_observed_at"),
            (self.last_observed_at, "last_observed_at"),
            (self.updated_at, "updated_at"),
        ):
            _aware(value, label)
        if self.last_observed_at < self.first_observed_at:
            raise ValueError("last_observed_at cannot precede first_observed_at")
        if self.updated_at < self.last_observed_at:
            raise ValueError("updated_at cannot precede last_observed_at")
        if self.lifecycle is HeatingAnomalyLifecycle.CLEARED:
            if self.cleared_at is None:
                raise ValueError("cleared anomaly requires cleared_at")
            _aware(self.cleared_at, "cleared_at")
            if self.cleared_at != self.updated_at:
                raise ValueError("cleared_at must equal updated_at")
        elif self.cleared_at is not None:
            raise ValueError("non-cleared anomaly cannot contain cleared_at")
        if self.lifecycle is HeatingAnomalyLifecycle.STARTED and not (
            self.first_observed_at == self.last_observed_at == self.updated_at
        ):
            raise ValueError("started anomaly timestamps must be equal")
        if self.lifecycle is HeatingAnomalyLifecycle.ACTIVE and self.last_observed_at != self.updated_at:
            raise ValueError("active anomaly last_observed_at must equal updated_at")
        if self.zone_id is None and self.source_id is None and self.heating_episode_id is None:
            raise ValueError("anomaly requires a zone, source, or episode subject")
        if self.source_id == "":
            raise ValueError("source_id must not be empty when present")
        if self.heating_episode_id == "":
            raise ValueError("heating_episode_id must not be empty when present")
        if self.heating_episode_id is not None and self.zone_id is None:
            raise ValueError("episode-correlated anomaly requires zone_id")

    @property
    def is_active(self) -> bool:
        return self.lifecycle in {
            HeatingAnomalyLifecycle.STARTED,
            HeatingAnomalyLifecycle.ACTIVE,
        }


def heating_anomaly_id(
    *,
    category: HeatingAnomalyCategory,
    reason_code: str,
    zone_id: ZoneId | None = None,
    source_id: str | None = None,
    heating_episode_id: str | None = None,
) -> str:
    """Return a deterministic identity scoped to explicit subject evidence."""

    _identifier(reason_code, "reason_code")
    subject = heating_episode_id or source_id or (zone_id.value if zone_id is not None else None)
    if not subject:
        raise ValueError("anomaly identity requires a zone, source, or episode subject")
    return f"heating_anomaly:{category.value}:{reason_code}:{subject}"


def _identifier(value: str, label: str) -> None:
    if not value or not value.isascii() or not value.replace("_", "").isalnum():
        raise ValueError(f"{label} must be a non-empty ASCII identifier")


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
