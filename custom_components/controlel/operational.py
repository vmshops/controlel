"""Immutable operational observation model for the Home Assistant adapter."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Any

TRACE_LIMIT = 20
LOGGER = logging.getLogger(__name__)


class RuntimeStatus(StrEnum):
    STARTING = "starting"
    ACTIVE = "active"
    STOPPED = "stopped"
    FATAL_ERROR = "fatal_error"


class MeasurementStatus(StrEnum):
    VALID = "valid"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    INVALID_VALUE = "invalid_value"
    STALE = "stale"
    FUTURE_TIMESTAMP = "future_timestamp"
    NOT_RECEIVED = "not_received"


class HeatDemandState(StrEnum):
    HEAT_REQUIRED = "heat_required"
    NO_HEAT_REQUIRED = "no_heat_required"
    INDETERMINATE = "indeterminate"


class SafetyState(StrEnum):
    NORMAL = "normal"
    INDETERMINATE_GRACE = "indeterminate_grace"
    TIMEOUT_ACTION_APPLIED = "timeout_action_applied"
    STOPPED = "stopped"
    FATAL_ERROR = "fatal_error"


class SourceControlState(StrEnum):
    IDLE = "idle"
    HEATING_REQUESTED = "heating_requested"
    HEATING_NOT_REQUESTED = "heating_not_requested"
    DEFERRED_ENABLE = "deferred_enable"
    DEFERRED_DISABLE = "deferred_disable"
    STOPPED = "stopped"
    FATAL_ERROR = "fatal_error"


class ActiveLockoutType(StrEnum):
    MINIMUM_ON = "minimum_on"
    MINIMUM_OFF = "minimum_off"


class DecisionCode(StrEnum):
    HEAT_REQUESTED = "heat_requested"
    HEAT_NOT_REQUIRED = "heat_not_required"
    INDETERMINATE_PRESERVE_PREVIOUS = "indeterminate_preserve_previous"
    TIMEOUT_DISABLE_HEATING = "timeout_disable_heating"
    TIMEOUT_ENABLE_HEATING = "timeout_enable_heating"
    COMMAND_SUPPRESSED_DUPLICATE = "command_suppressed_duplicate"
    COMMAND_DISPATCHED = "command_dispatched"
    COMMAND_DEFERRED = "command_deferred"
    COMMAND_FAILED = "command_failed"
    FATAL_SHUTDOWN_DISABLE_DISPATCHED = "fatal_shutdown_disable_dispatched"
    FATAL_SHUTDOWN_DISABLE_FAILED = "fatal_shutdown_disable_failed"
    FATAL_SHUTDOWN_DISABLE_SKIPPED_ALREADY_FAILED = "fatal_shutdown_disable_skipped_already_failed"
    FATAL_SHUTDOWN_NO_COMMAND_PATH_AVAILABLE = "fatal_shutdown_no_command_path_available"
    RUNTIME_STARTED = "runtime_started"
    RUNTIME_STOPPED = "runtime_stopped"


class DecisionReason(StrEnum):
    TEMPERATURE_BELOW_TARGET = "temperature_below_target"
    TEMPERATURE_AT_OR_ABOVE_TARGET = "temperature_at_or_above_target"
    BELOW_ENABLE_THRESHOLD = "below_enable_threshold"
    ABOVE_DISABLE_THRESHOLD = "above_disable_threshold"
    INSIDE_HYSTERESIS_DEADBAND = "inside_hysteresis_deadband"
    PRESERVED_PREVIOUS_DEMAND = "preserved_previous_demand"
    LEGACY_EXACT_THRESHOLD = "legacy_exact_threshold"
    STARTUP_FROM_RAW_DEMAND = "startup_from_raw_demand"
    MINIMUM_ON_TIME_ACTIVE = "minimum_on_time_active"
    MINIMUM_OFF_TIME_ACTIVE = "minimum_off_time_active"
    DEFERRED_COMMAND_CANCELLED = "deferred_command_cancelled"
    LOCKOUT_EXPIRED_REEVALUATION = "lockout_expired_reevaluation"
    SAFETY_DISABLE_BYPASSED_LOCKOUT = "safety_disable_bypassed_lockout"
    MEASUREMENT_UNAVAILABLE = "measurement_unavailable"
    MEASUREMENT_UNKNOWN = "measurement_unknown"
    MEASUREMENT_STALE = "measurement_stale"
    MEASUREMENT_INVALID = "measurement_invalid"
    MEASUREMENT_FUTURE_TIMESTAMP = "measurement_future_timestamp"
    WAITING_FOR_FIRST_MEASUREMENT = "waiting_for_first_measurement"
    SAFETY_GRACE_EXPIRED = "safety_grace_expired"
    DUPLICATE_COMMAND = "duplicate_command"
    SERVICE_CALL_FAILED = "service_call_failed"
    FATAL_RUNTIME_FAILURE = "fatal_runtime_failure"
    RUNTIME_LIFECYCLE = "runtime_lifecycle"


class CommandOutcome(StrEnum):
    NONE = "none"
    DISPATCHED = "dispatched"
    SUPPRESSED_DUPLICATE = "suppressed_duplicate"
    FAILED_RECOVERABLE = "failed_recoverable"
    FAILED_FATAL = "failed_fatal"
    DEFERRED = "deferred"


class EmergencyDisableOutcome(StrEnum):
    NONE = "none"
    REQUESTED = "emergency_heating_off_requested"
    DISPATCHED = "fatal_shutdown_disable_dispatched"
    FAILED = "fatal_shutdown_disable_failed"
    SKIPPED_ALREADY_FAILED = "fatal_shutdown_disable_skipped_already_failed"
    NO_COMMAND_PATH_AVAILABLE = "fatal_shutdown_no_command_path_available"


@dataclass(frozen=True)
class DecisionTraceRecord:
    decision_code: DecisionCode
    reason_code: DecisionReason
    timestamp: datetime
    measured_temperature: float | None
    target_temperature: float
    resulting_demand: HeatDemandState
    requested_command: str | None
    command_outcome: CommandOutcome
    safety_state: SafetyState
    raw_demand: HeatDemandState | None = None
    hysteresis_demand: HeatDemandState | None = None
    source_control_state: SourceControlState | None = None
    deferred_reason: str | None = None
    safety_bypassed_lockout: bool = False
    emergency_disable_outcome: EmergencyDisableOutcome = EmergencyDisableOutcome.NONE
    sequence: int = 0

    def __post_init__(self) -> None:
        _validate_aware(self.timestamp, "decision timestamp")


@dataclass(frozen=True)
class OperationalSnapshot:
    revision: int
    updated_at: datetime
    runtime_status: RuntimeStatus
    zone_name: str
    zone_id: str
    sensor_name: str
    sensor_id: str
    temperature_entity_id: str
    current_temperature: float | None
    target_temperature: float
    heating_turn_on_differential: float
    heating_turn_off_differential: float
    heating_enable_threshold: float
    heating_disable_threshold: float
    measurement_status: MeasurementStatus
    latest_input_status: MeasurementStatus
    measurement_timestamp: datetime | None
    measurement_age_seconds: float | None
    zone_heat_demand: HeatDemandState
    raw_zone_heat_demand: HeatDemandState
    hysteresis_demand: HeatDemandState
    demand_reason: DecisionReason
    active_demand_cause: DecisionReason
    safety_state: SafetyState
    grace_deadline: datetime | None
    grace_remaining_seconds: float | None
    source_control_state: SourceControlState
    minimum_on_deadline: datetime | None
    minimum_off_deadline: datetime | None
    active_lockout_type: ActiveLockoutType | None
    lockout_remaining_seconds: float | None
    deferred_command: str | None
    deferred_reason: str | None
    last_normal_command_dispatch: datetime | None
    safety_bypassed_lockout: bool
    timeout_action: str
    last_decision: DecisionCode | None
    last_decision_reason: DecisionReason | None
    last_decision_timestamp: datetime | None
    last_requested_command: str | None
    last_command_outcome: CommandOutcome
    last_command_timestamp: datetime | None
    last_command_failure_type: str | None
    duplicate_commands_suppressed: int
    recoverable_failure_active: bool
    fatal_failure_active: bool
    emergency_disable_attempted: bool
    emergency_disable_outcome: EmergencyDisableOutcome
    emergency_disable_timestamp: datetime | None
    original_fatal_cause: str | None
    integration_version: str
    core_version: str
    last_meaningful_event_at: datetime | None

    def __post_init__(self) -> None:
        _validate_aware(self.updated_at, "snapshot update timestamp")
        for label, value in (
            ("measurement timestamp", self.measurement_timestamp),
            ("grace deadline", self.grace_deadline),
            ("minimum-on deadline", self.minimum_on_deadline),
            ("minimum-off deadline", self.minimum_off_deadline),
            ("normal command dispatch", self.last_normal_command_dispatch),
            ("decision timestamp", self.last_decision_timestamp),
            ("command timestamp", self.last_command_timestamp),
            ("emergency disable timestamp", self.emergency_disable_timestamp),
            ("meaningful event timestamp", self.last_meaningful_event_at),
        ):
            if value is not None:
                _validate_aware(value, label)
        if self.revision < 0:
            raise ValueError("snapshot revision must not be negative")
        if self.duplicate_commands_suppressed < 0:
            raise ValueError("duplicate suppression count must not be negative")


type SnapshotSubscriber = Callable[[OperationalSnapshot], None]


class OperationalSnapshotSource:
    """Own one current snapshot, bounded trace, and read-only subscribers."""

    def __init__(self, initial: OperationalSnapshot) -> None:
        self._snapshot = initial
        self._trace: deque[DecisionTraceRecord] = deque(maxlen=TRACE_LIMIT)
        self._subscribers: dict[int, SnapshotSubscriber] = {}
        self._next_subscriber = 0
        self._closed = False
        self._lock = Lock()

    @property
    def current(self) -> OperationalSnapshot:
        with self._lock:
            return self._snapshot

    @property
    def trace(self) -> tuple[DecisionTraceRecord, ...]:
        with self._lock:
            return tuple(self._trace)

    def subscribe(self, subscriber: SnapshotSubscriber) -> Callable[[], None]:
        """Subscribe and immediately receive the latest consistent snapshot."""

        with self._lock:
            if self._closed:
                snapshot = self._snapshot
                token: int | None = None
            else:
                token = self._next_subscriber
                self._next_subscriber += 1
                self._subscribers[token] = subscriber
                snapshot = self._snapshot
        subscriber(snapshot)
        unsubscribed = False

        def unsubscribe() -> None:
            nonlocal unsubscribed
            if unsubscribed:
                return
            unsubscribed = True
            if token is not None:
                with self._lock:
                    self._subscribers.pop(token, None)

        return unsubscribe

    def update(
        self,
        *,
        now: datetime,
        trace_record: DecisionTraceRecord | None = None,
        **changes: Any,
    ) -> OperationalSnapshot:
        """Atomically replace the snapshot and notify current subscribers."""

        _validate_aware(now, "snapshot update timestamp")
        with self._lock:
            if self._closed:
                return self._snapshot
            revision = self._snapshot.revision + 1
            if trace_record is not None:
                trace_record = replace(trace_record, sequence=revision)
                self._trace.append(trace_record)
                changes.setdefault("last_decision", trace_record.decision_code)
                changes.setdefault("last_decision_reason", trace_record.reason_code)
                changes.setdefault("last_decision_timestamp", trace_record.timestamp)
                changes.setdefault("last_meaningful_event_at", trace_record.timestamp)
            snapshot = replace(
                self._snapshot,
                revision=revision,
                updated_at=now,
                **changes,
            )
            snapshot = _with_elapsed(snapshot, now)
            self._snapshot = snapshot
            subscribers = tuple(self._subscribers.values())
        for subscriber in subscribers:
            subscriber(snapshot)
        LOGGER.debug(
            "Controlel operational snapshot revision=%s trace_record=%s",
            snapshot.revision,
            trace_record is not None,
        )
        return snapshot

    def refresh_elapsed(self, now: datetime) -> OperationalSnapshot:
        """Refresh only derived age/countdown values at a modest cadence."""

        return self.update(now=now)

    def close(self) -> None:
        """Prevent all future updates and detach every subscriber."""

        with self._lock:
            self._closed = True
            self._subscribers.clear()

    def snapshot_at(self, now: datetime) -> OperationalSnapshot:
        """Return a read-only view with elapsed values calculated at ``now``."""

        _validate_aware(now, "snapshot view timestamp")
        with self._lock:
            return _with_elapsed(self._snapshot, now)


def initial_snapshot(
    *,
    now: datetime | None = None,
    zone_name: str,
    zone_id: str,
    sensor_name: str,
    sensor_id: str,
    temperature_entity_id: str,
    target_temperature: float,
    heating_turn_on_differential: float,
    heating_turn_off_differential: float,
    timeout_action: str,
    integration_version: str,
    core_version: str,
) -> OperationalSnapshot:
    timestamp = now or datetime.now(UTC)
    return OperationalSnapshot(
        revision=0,
        updated_at=timestamp,
        runtime_status=RuntimeStatus.STARTING,
        zone_name=zone_name,
        zone_id=zone_id,
        sensor_name=sensor_name,
        sensor_id=sensor_id,
        temperature_entity_id=temperature_entity_id,
        current_temperature=None,
        target_temperature=target_temperature,
        heating_turn_on_differential=heating_turn_on_differential,
        heating_turn_off_differential=heating_turn_off_differential,
        heating_enable_threshold=target_temperature - heating_turn_on_differential,
        heating_disable_threshold=target_temperature + heating_turn_off_differential,
        measurement_status=MeasurementStatus.NOT_RECEIVED,
        latest_input_status=MeasurementStatus.NOT_RECEIVED,
        measurement_timestamp=None,
        measurement_age_seconds=None,
        zone_heat_demand=HeatDemandState.INDETERMINATE,
        raw_zone_heat_demand=HeatDemandState.INDETERMINATE,
        hysteresis_demand=HeatDemandState.INDETERMINATE,
        demand_reason=DecisionReason.WAITING_FOR_FIRST_MEASUREMENT,
        active_demand_cause=DecisionReason.WAITING_FOR_FIRST_MEASUREMENT,
        safety_state=SafetyState.STOPPED,
        grace_deadline=None,
        grace_remaining_seconds=None,
        source_control_state=SourceControlState.IDLE,
        minimum_on_deadline=None,
        minimum_off_deadline=None,
        active_lockout_type=None,
        lockout_remaining_seconds=None,
        deferred_command=None,
        deferred_reason=None,
        last_normal_command_dispatch=None,
        safety_bypassed_lockout=False,
        timeout_action=timeout_action,
        last_decision=None,
        last_decision_reason=None,
        last_decision_timestamp=None,
        last_requested_command=None,
        last_command_outcome=CommandOutcome.NONE,
        last_command_timestamp=None,
        last_command_failure_type=None,
        duplicate_commands_suppressed=0,
        recoverable_failure_active=False,
        fatal_failure_active=False,
        emergency_disable_attempted=False,
        emergency_disable_outcome=EmergencyDisableOutcome.NONE,
        emergency_disable_timestamp=None,
        original_fatal_cause=None,
        integration_version=integration_version,
        core_version=core_version,
        last_meaningful_event_at=None,
    )


def snapshot_to_dict(snapshot: OperationalSnapshot) -> dict[str, Any]:
    """Convert a snapshot into JSON-serializable diagnostics primitives."""

    return _serialize(asdict(snapshot))


def trace_to_dict(trace: tuple[DecisionTraceRecord, ...]) -> list[dict[str, Any]]:
    return [_serialize(asdict(record)) for record in trace]


def _with_elapsed(
    snapshot: OperationalSnapshot,
    now: datetime,
) -> OperationalSnapshot:
    age = (
        max(0.0, (now - snapshot.measurement_timestamp).total_seconds())
        if snapshot.measurement_timestamp is not None
        else None
    )
    remaining = (
        max(0.0, (snapshot.grace_deadline - now).total_seconds())
        if snapshot.grace_deadline is not None and snapshot.safety_state is SafetyState.INDETERMINATE_GRACE
        else None
    )
    lockout_deadline = {
        ActiveLockoutType.MINIMUM_ON: snapshot.minimum_on_deadline,
        ActiveLockoutType.MINIMUM_OFF: snapshot.minimum_off_deadline,
        None: None,
    }[snapshot.active_lockout_type]
    lockout_remaining = (
        max(0.0, (lockout_deadline - now).total_seconds())
        if lockout_deadline is not None and lockout_deadline > now
        else None
    )
    return replace(
        snapshot,
        measurement_age_seconds=age,
        grace_remaining_seconds=remaining,
        lockout_remaining_seconds=lockout_remaining,
    )


def _serialize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _validate_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
