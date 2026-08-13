"""Immutable, presentation-neutral operational-event contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

type OperationalEventScalar = str | int | float | bool | None


class OperationalEventCategory(StrEnum):
    """Small stable taxonomy for meaningful runtime events."""

    RUNTIME = "runtime"
    MEASUREMENT = "measurement"
    DEMAND = "demand"
    SAFETY = "safety"
    SOURCE_CONTROL = "source_control"
    SOURCE_RESILIENCE = "source_resilience"
    SUPERVISION = "supervision"
    HEAT_DELIVERY = "heat_delivery"
    PERFORMANCE = "performance"


class OperationalEventSeverity(StrEnum):
    """Meaning of an event, independent from future delivery preferences."""

    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    CRITICAL = "critical"


class MeasurementEventCondition(StrEnum):
    """Explicit current measurement condition used for transition events."""

    VALID = "valid"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class OperationalEventCode(StrEnum):
    """Initial stable M31A operational-event vocabulary."""

    RUNTIME_STARTED = "runtime_started"
    RUNTIME_STOPPED = "runtime_stopped"
    RUNTIME_FATAL = "runtime_fatal"
    RUNTIME_RECOVERED = "runtime_recovered"
    MEASUREMENT_BECAME_VALID = "measurement_became_valid"
    MEASUREMENT_BECAME_STALE = "measurement_became_stale"
    MEASUREMENT_BECAME_UNAVAILABLE = "measurement_became_unavailable"
    MEASUREMENT_RECOVERED = "measurement_recovered"
    HEAT_DEMAND_STARTED = "heat_demand_started"
    HEAT_DEMAND_CONFIRMED = "heat_demand_confirmed"
    HEAT_DEMAND_CANCELLED = "heat_demand_cancelled"
    HEAT_DEMAND_SATISFIED = "heat_demand_satisfied"
    SAFETY_GRACE_STARTED = "safety_grace_started"
    SAFETY_GRACE_EXPIRED = "safety_grace_expired"
    SAFETY_DISABLE_REQUESTED = "safety_disable_requested"
    EMERGENCY_DISABLE_REQUESTED = "emergency_disable_requested"
    SOURCE_ENABLE_REQUESTED = "source_enable_requested"
    SOURCE_DISABLE_REQUESTED = "source_disable_requested"
    SOURCE_COMMAND_DISPATCHED = "source_command_dispatched"
    SOURCE_COMMAND_FAILED = "source_command_failed"
    SOURCE_COMMAND_DEFERRED_MINIMUM_ON = "source_command_deferred_minimum_on"
    SOURCE_COMMAND_DEFERRED_MINIMUM_OFF = "source_command_deferred_minimum_off"
    REPORTED_SOURCE_STATE_CHANGED = "reported_source_state_changed"
    SOURCE_DRIFT_DETECTED = "source_drift_detected"
    SOURCE_RECONCILIATION_STARTED = "source_reconciliation_started"
    SOURCE_RECONCILIATION_COMPLETED = "source_reconciliation_completed"
    CORRECTIVE_ACTION_HELD = "corrective_action_held"
    CORRECTIVE_ACTION_DISPATCHED = "corrective_action_dispatched"
    FAILSAFE_ENTERED = "failsafe_entered"
    FAILSAFE_EXITED = "failsafe_exited"
    RESTART_ATTEMPT_STARTED = "restart_attempt_started"
    RESTART_ATTEMPT_FAILED = "restart_attempt_failed"
    RESTART_BUDGET_EXHAUSTED = "restart_budget_exhausted"
    COMMAND_AUTHORITY_CHANGED = "command_authority_changed"


@dataclass(frozen=True, slots=True)
class OperationalEventDetail:
    """One allowlisted JSON-safe evidence item."""

    key: str
    value: OperationalEventScalar

    def __post_init__(self) -> None:
        if not self.key or not self.key.isascii() or not self.key.replace("_", "").isalnum():
            raise ValueError("detail key must be a non-empty ASCII identifier")
        if isinstance(self.value, float) and not isfinite(self.value):
            raise ValueError("detail float values must be finite")
        if not isinstance(self.value, str | int | float | bool | type(None)):
            raise TypeError("detail value must be a JSON-safe scalar")


@dataclass(frozen=True, slots=True)
class OperationalEvent:
    """One immutable semantic event; it never claims unobserved physical state."""

    event_id: str
    timestamp: datetime
    category: OperationalEventCategory
    severity: OperationalEventSeverity
    event_code: OperationalEventCode
    reason_code: str | None
    summary_code: str
    zone_id: str | None = None
    source_id: str | None = None
    correlation_id: str | None = None
    previous_state: str | None = None
    new_state: str | None = None
    requested_command: str | None = None
    command_outcome: str | None = None
    details: tuple[OperationalEventDetail, ...] = ()

    def __post_init__(self) -> None:
        if not self.event_id or not self.summary_code:
            raise ValueError("event_id and summary_code must not be empty")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if not isinstance(self.category, OperationalEventCategory):
            raise TypeError("category must be an OperationalEventCategory")
        if not isinstance(self.severity, OperationalEventSeverity):
            raise TypeError("severity must be an OperationalEventSeverity")
        if not isinstance(self.event_code, OperationalEventCode):
            raise TypeError("event_code must be an OperationalEventCode")
        keys = tuple(detail.key for detail in self.details)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("details must have unique keys in deterministic sorted order")
