"""Immutable, presentation-neutral user-activity contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

type UserActivityScalar = str | int | float | bool | None

MAX_ACTIVITY_SOURCE_EVENTS = 64
MAX_ACTIVITY_ZONES = 64
MAX_ACTIVITY_SOURCES = 16
MAX_ACTIVITY_PARAMETERS = 32


class UserActivityType(StrEnum):
    """Small user-facing taxonomy composed from technical evidence."""

    HEATING_STARTED = "heating_started"
    HEATING_STOPPED = "heating_stopped"
    HEAT_DEMAND_CANCELLED = "heat_demand_cancelled"
    SOURCE_STATE_CORRECTED = "source_state_corrected"
    SOURCE_CORRECTION_FAILED = "source_correction_failed"
    SOURCE_COMMAND_FAILED = "source_command_failed"
    MEASUREMENT_DEGRADED = "measurement_degraded"
    MEASUREMENT_RECOVERED = "measurement_recovered"
    SAFETY_FALLBACK_APPLIED = "safety_fallback_applied"
    RUNTIME_FAILSAFE_ENTERED = "runtime_failsafe_entered"
    RUNTIME_RECOVERED = "runtime_recovered"
    RUNTIME_RESTART_EXHAUSTED = "runtime_restart_exhausted"


class UserActivityStatus(StrEnum):
    """Explicit lifecycle status for one human-meaningful occurrence."""

    OPEN = "open"
    COMPLETED = "completed"
    FAILED = "failed"
    RECOVERED = "recovered"
    CANCELLED = "cancelled"


class UserActivityLevel(StrEnum):
    """User attention level, independent from technical event severity."""

    CRITICAL = "critical"
    OPERATIONAL = "operational"
    DETAILED = "detailed"
    DEBUG = "debug"


@dataclass(frozen=True, slots=True)
class UserActivityParameter:
    """One bounded JSON-safe scalar item of directly available evidence."""

    key: str
    value: UserActivityScalar

    def __post_init__(self) -> None:
        if not self.key or not self.key.isascii() or not self.key.replace("_", "").isalnum():
            raise ValueError("parameter key must be a non-empty ASCII identifier")
        if isinstance(self.value, float) and not isfinite(self.value):
            raise ValueError("parameter float values must be finite")
        if not isinstance(self.value, str | int | float | bool | type(None)):
            raise TypeError("parameter value must be a JSON-safe scalar")


@dataclass(frozen=True, slots=True)
class UserActivity:
    """One immutable human-meaningful occurrence composed from explicit evidence."""

    activity_id: str
    activity_type: UserActivityType
    status: UserActivityStatus
    level: UserActivityLevel
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    source_event_ids: tuple[str, ...]
    correlation_id: str
    parent_activity_id: str | None = None
    zone_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    requested_action: str | None = None
    command_outcome: str | None = None
    reported_state: str | None = None
    reason_code: str | None = None
    completion_outcome: str | None = None
    parameters: tuple[UserActivityParameter, ...] = ()

    def __post_init__(self) -> None:
        if not self.activity_id or not self.correlation_id:
            raise ValueError("activity_id and correlation_id must not be empty")
        if not isinstance(self.activity_type, UserActivityType):
            raise TypeError("activity_type must be a UserActivityType")
        if not isinstance(self.status, UserActivityStatus):
            raise TypeError("status must be a UserActivityStatus")
        if not isinstance(self.level, UserActivityLevel):
            raise TypeError("level must be a UserActivityLevel")
        for label, value in (
            ("started_at", self.started_at),
            ("updated_at", self.updated_at),
            ("completed_at", self.completed_at),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{label} must be timezone-aware")
        if self.updated_at < self.started_at:
            raise ValueError("updated_at must not precede started_at")
        if self.status is UserActivityStatus.OPEN:
            if self.completed_at is not None:
                raise ValueError("OPEN activity requires completed_at=None")
        elif self.completed_at is None:
            raise ValueError("completed_at is required for a closed activity")
        elif self.completed_at < self.updated_at:
            raise ValueError("completed_at must not precede updated_at")
        _sorted_bounded(self.source_event_ids, MAX_ACTIVITY_SOURCE_EVENTS, "source_event_ids", required=True)
        _sorted_bounded(self.zone_ids, MAX_ACTIVITY_ZONES, "zone_ids")
        _sorted_bounded(self.source_ids, MAX_ACTIVITY_SOURCES, "source_ids")
        keys = tuple(parameter.key for parameter in self.parameters)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("parameters must have unique keys in deterministic sorted order")
        if len(self.parameters) > MAX_ACTIVITY_PARAMETERS:
            raise ValueError(f"parameters must contain at most {MAX_ACTIVITY_PARAMETERS} items")


@dataclass(frozen=True, slots=True)
class UserActivitySnapshot:
    """Immutable bounded read boundary for activities and source progress."""

    schema_version: int
    capacity: int
    activities: tuple[UserActivity, ...]
    activity_sequences: tuple[int, ...]
    total_activities_emitted: int
    total_activity_revisions_emitted: int
    dropped_count: int
    source_total_observed: int
    source_last_processed_sequence: int
    source_events_missed: int
    source_overflow_occurrences: int
    open_activity_count: int
    latest_activity_timestamp: datetime | None

    def __post_init__(self) -> None:
        if self.schema_version != 2:
            raise ValueError("schema_version must be 2")
        if len(self.activity_sequences) != len(self.activities):
            raise ValueError("activity_sequences must align with activities")
        if len(set(self.activity_sequences)) != len(self.activity_sequences):
            raise ValueError("activity_sequences must be unique")
        if any(
            sequence < 1 or sequence > self.total_activity_revisions_emitted for sequence in self.activity_sequences
        ):
            raise ValueError("activity_sequences must identify emitted revisions")


def user_activity_id(activity_type: UserActivityType, correlation_id: str, *, discriminator: str | None = None) -> str:
    """Return a deterministic identifier without using wall-clock proximity."""

    if not correlation_id:
        raise ValueError("correlation_id must not be empty")
    suffix = activity_type.value if discriminator is None else f"{activity_type.value}:{discriminator}"
    return f"{correlation_id}/{suffix}"


def _sorted_bounded(values: tuple[str, ...], maximum: int, label: str, *, required: bool = False) -> None:
    if required and not values:
        raise ValueError(f"{label} must not be empty")
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique and sorted")
    if len(values) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} items")
