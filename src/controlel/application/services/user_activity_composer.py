"""Passive deterministic composition of technical events into user activities."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from controlel.application.services.operational_event_stream import OperationalEventStreamSnapshot
from controlel.application.services.user_activity_stream import (
    UserActivityStream,
    user_activity_snapshot_with_source,
)
from controlel.domain.operational_events import OperationalEvent, OperationalEventCode
from controlel.domain.user_activities import (
    MAX_ACTIVITY_PARAMETERS,
    MAX_ACTIVITY_SOURCE_EVENTS,
    MAX_ACTIVITY_SOURCES,
    MAX_ACTIVITY_ZONES,
    UserActivity,
    UserActivityLevel,
    UserActivityParameter,
    UserActivitySnapshot,
    UserActivityStatus,
    UserActivityType,
    user_activity_id,
)

DEFAULT_OPEN_ACTIVITY_CAPACITY = 64


@dataclass(slots=True)
class _Lifecycle:
    lifecycle_id: str
    started_at: datetime
    source_event_ids: list[str] = field(default_factory=list)
    zone_ids: set[str] = field(default_factory=set)
    source_ids: set[str] = field(default_factory=set)
    requested_action: str | None = None
    command_outcome: str | None = None
    reported_state: str | None = None
    reason_code: str | None = None
    parameters: dict[str, str | int | float | bool | None] = field(default_factory=dict)
    source_events_truncated: int = 0
    heating_started_at: datetime | None = None


class UserActivityComposer:
    """Own a truthful source cursor and bounded, control-independent activity state."""

    def __init__(
        self,
        snapshot_provider: Callable[[], OperationalEventStreamSnapshot],
        *,
        activity_capacity: int = 200,
        open_activity_capacity: int = DEFAULT_OPEN_ACTIVITY_CAPACITY,
        logger: logging.Logger | None = None,
    ) -> None:
        if isinstance(open_activity_capacity, bool) or not isinstance(open_activity_capacity, int):
            raise TypeError("open_activity_capacity must be an integer")
        if open_activity_capacity < 1:
            raise ValueError("open_activity_capacity must be positive")
        self.stream = UserActivityStream(activity_capacity)
        self._snapshot_provider = snapshot_provider
        self._open_activity_capacity = open_activity_capacity
        self._open: dict[str, _Lifecycle] = {}
        self._source_total_observed = 0
        self._source_last_processed_sequence = 0
        self._source_events_missed = 0
        self._source_overflow_occurrences = 0
        self._logger = logger or logging.getLogger(__name__)

    def process_available(self) -> bool:
        """Consume one source snapshot without polling or control feedback."""

        snapshot = self._snapshot_provider()
        self._source_total_observed = max(self._source_total_observed, snapshot.total_emitted)
        first_retained_sequence = snapshot.total_emitted - len(snapshot.events) + 1
        next_sequence = self._source_last_processed_sequence + 1
        if snapshot.events and next_sequence < first_retained_sequence:
            self._source_events_missed += first_retained_sequence - next_sequence
            self._source_overflow_occurrences += 1
            self._source_last_processed_sequence = first_retained_sequence - 1
            self.stream.discard_correlations(set(self._open))
            self._open.clear()

        for offset, event in enumerate(snapshot.events):
            sequence = first_retained_sequence + offset
            if sequence <= self._source_last_processed_sequence:
                continue
            try:
                self._compose_event(event)
            except Exception:
                self._logger.exception("User activity composition failed at source sequence %s", sequence)
                return False
            self._source_last_processed_sequence = sequence
        return self._source_last_processed_sequence >= snapshot.total_emitted

    def snapshot(self) -> UserActivitySnapshot:
        """Return bounded immutable activities with exact source progress."""

        return user_activity_snapshot_with_source(
            self.stream.snapshot(open_activity_count=len(self._open)),
            source_total_observed=self._source_total_observed,
            source_last_processed_sequence=self._source_last_processed_sequence,
            source_events_missed=self._source_events_missed,
            source_overflow_occurrences=self._source_overflow_occurrences,
        )

    def _compose_event(self, event: OperationalEvent) -> None:
        code = event.event_code
        if code is OperationalEventCode.SOURCE_DRIFT_DETECTED:
            context = self._start(event)
            if context is not None:
                self._capture(context, event)
            return
        if code in {
            OperationalEventCode.SOURCE_RECONCILIATION_STARTED,
            OperationalEventCode.CORRECTIVE_ACTION_HELD,
            OperationalEventCode.CORRECTIVE_ACTION_DISPATCHED,
        }:
            self._capture_existing(event)
            return
        if code is OperationalEventCode.SOURCE_RECONCILIATION_COMPLETED:
            self._complete_reconciliation(event)
            return
        if code is OperationalEventCode.SOURCE_COMMAND_FAILED:
            self._command_failed(event)
            return
        if code in {
            OperationalEventCode.SOURCE_ENABLE_REQUESTED,
            OperationalEventCode.SOURCE_DISABLE_REQUESTED,
            OperationalEventCode.SOURCE_COMMAND_DEFERRED_MINIMUM_ON,
            OperationalEventCode.SOURCE_COMMAND_DEFERRED_MINIMUM_OFF,
        }:
            self._capture_existing(event)
            return
        if code is OperationalEventCode.SOURCE_COMMAND_DISPATCHED:
            self._command_dispatched(event)
            return
        if code is OperationalEventCode.REPORTED_SOURCE_STATE_CHANGED:
            self._capture_existing(event)
            return
        if code in {
            OperationalEventCode.MEASUREMENT_BECAME_STALE,
            OperationalEventCode.MEASUREMENT_BECAME_UNAVAILABLE,
        }:
            self._measurement_degraded(event)
            return
        if code in {OperationalEventCode.SAFETY_GRACE_STARTED, OperationalEventCode.SAFETY_GRACE_EXPIRED}:
            self._measurement_evidence(event)
            return
        if code is OperationalEventCode.SAFETY_DISABLE_REQUESTED:
            self._safety_fallback(event)
            return
        if code is OperationalEventCode.MEASUREMENT_RECOVERED:
            self._measurement_recovered(event)
            return
        if code in {OperationalEventCode.HEAT_DEMAND_STARTED, OperationalEventCode.HEAT_DEMAND_CONFIRMED}:
            self._capture_existing_or_start(event)
            return
        if code is OperationalEventCode.HEAT_DEMAND_CANCELLED:
            self._demand_cancelled(event)
            return
        if code is OperationalEventCode.FAILSAFE_ENTERED:
            self._runtime_failsafe(event)
            return
        if code is OperationalEventCode.RUNTIME_RECOVERED:
            self._runtime_recovered(event)
            return
        if code is OperationalEventCode.RESTART_BUDGET_EXHAUSTED:
            self._restart_exhausted(event)

    def _start(self, event: OperationalEvent) -> _Lifecycle | None:
        if event.activity_id is None:
            return None
        existing = self._open.get(event.activity_id)
        if existing is not None:
            return existing
        if len(self._open) >= self._open_activity_capacity:
            return None
        context = _Lifecycle(event.activity_id, event.timestamp)
        self._open[event.activity_id] = context
        return context

    def _capture_existing_or_start(self, event: OperationalEvent) -> None:
        context = self._start(event)
        if context is not None:
            self._capture(context, event)

    def _capture_existing(self, event: OperationalEvent) -> None:
        if event.activity_id is None:
            return
        context = self._open.get(event.activity_id)
        if context is not None:
            self._capture(context, event)

    def _capture(self, context: _Lifecycle, event: OperationalEvent) -> None:
        if event.event_id not in context.source_event_ids:
            if len(context.source_event_ids) < MAX_ACTIVITY_SOURCE_EVENTS:
                context.source_event_ids.append(event.event_id)
            else:
                context.source_events_truncated += 1
        if event.zone_id is not None and len(context.zone_ids) < MAX_ACTIVITY_ZONES:
            context.zone_ids.add(event.zone_id)
        if event.source_id is not None and len(context.source_ids) < MAX_ACTIVITY_SOURCES:
            context.source_ids.add(event.source_id)
        context.requested_action = event.requested_command or context.requested_action
        context.command_outcome = event.command_outcome or context.command_outcome
        context.reported_state = event.new_state or context.reported_state
        context.reason_code = event.reason_code or context.reason_code
        if event.event_code in {
            OperationalEventCode.SOURCE_COMMAND_DEFERRED_MINIMUM_ON,
            OperationalEventCode.SOURCE_COMMAND_DEFERRED_MINIMUM_OFF,
        }:
            context.parameters["protection_reason"] = event.reason_code
        for detail in event.details:
            if len(context.parameters) < MAX_ACTIVITY_PARAMETERS or detail.key in context.parameters:
                context.parameters[detail.key] = detail.value

    def _complete_reconciliation(self, event: OperationalEvent) -> None:
        context = self._pop_context(event)
        if context is None:
            return
        self._capture(context, event)
        outcome = _detail(event, "completion_outcome")
        if outcome != "reported_agreement" or context.command_outcome != "dispatched":
            return
        self._publish(
            context,
            UserActivityType.SOURCE_STATE_CORRECTED,
            UserActivityStatus.COMPLETED,
            UserActivityLevel.OPERATIONAL,
            event.timestamp,
            completion_outcome=outcome,
        )

    def _command_failed(self, event: OperationalEvent) -> None:
        reconciliation = event.activity_id is not None and event.activity_id.startswith("source-reconciliation:")
        context = self._pop_context(event) if reconciliation else self._context(event)
        if context is None:
            if event.activity_id is None:
                return
            context = _Lifecycle(event.activity_id, event.timestamp)
        self._capture(context, event)
        activity_type = (
            UserActivityType.SOURCE_CORRECTION_FAILED
            if context.lifecycle_id.startswith("source-reconciliation:")
            else UserActivityType.SOURCE_COMMAND_FAILED
        )
        self._publish(
            context,
            activity_type,
            UserActivityStatus.FAILED,
            UserActivityLevel.OPERATIONAL,
            event.timestamp,
            discriminator=None if reconciliation else event.event_id,
            completion_outcome="command_failed",
        )

    def _command_dispatched(self, event: OperationalEvent) -> None:
        if event.activity_id is None:
            return
        context = self._open.get(event.activity_id)
        if context is None and event.activity_id.startswith("heating-episode:"):
            context = self._start(event)
        if context is None:
            return
        self._capture(context, event)
        if not context.lifecycle_id.startswith("heating-episode:"):
            return
        if event.requested_command == "enable_heating":
            context.heating_started_at = event.timestamp
            self._publish(
                context,
                UserActivityType.HEATING_STARTED,
                UserActivityStatus.COMPLETED,
                UserActivityLevel.DETAILED,
                event.timestamp,
                started_at=event.timestamp,
                completion_outcome="permission_enable_dispatched",
            )
        elif event.requested_command == "disable_heating" and context.heating_started_at is not None:
            duration = (event.timestamp - context.heating_started_at).total_seconds()
            context.parameters["duration_seconds"] = duration
            self._publish(
                context,
                UserActivityType.HEATING_STOPPED,
                UserActivityStatus.COMPLETED,
                UserActivityLevel.DETAILED,
                event.timestamp,
                started_at=event.timestamp,
                completion_outcome="permission_disable_dispatched",
            )
            self._open.pop(context.lifecycle_id, None)

    def _measurement_degraded(self, event: OperationalEvent) -> None:
        context = self._start(event)
        if context is None:
            return
        self._capture(context, event)
        self._publish(
            context,
            UserActivityType.MEASUREMENT_DEGRADED,
            UserActivityStatus.OPEN,
            UserActivityLevel.OPERATIONAL,
            event.timestamp,
        )

    def _measurement_evidence(self, event: OperationalEvent) -> None:
        if event.activity_id is None:
            return
        context = self._open.get(event.activity_id)
        if context is None:
            return
        self._capture(context, event)
        self._publish(
            context,
            UserActivityType.MEASUREMENT_DEGRADED,
            UserActivityStatus.OPEN,
            UserActivityLevel.OPERATIONAL,
            event.timestamp,
        )

    def _safety_fallback(self, event: OperationalEvent) -> None:
        if event.activity_id is None:
            return
        context = self._open.get(event.activity_id)
        if context is None:
            return
        self._capture(context, event)
        self._publish(
            context,
            UserActivityType.SAFETY_FALLBACK_APPLIED,
            UserActivityStatus.COMPLETED,
            UserActivityLevel.OPERATIONAL,
            event.timestamp,
            completion_outcome="safety_action_requested",
        )

    def _measurement_recovered(self, event: OperationalEvent) -> None:
        context = self._pop_context(event)
        if context is None:
            return
        self._capture(context, event)
        degraded_id = user_activity_id(UserActivityType.MEASUREMENT_DEGRADED, context.lifecycle_id)
        self._publish(
            context,
            UserActivityType.MEASUREMENT_DEGRADED,
            UserActivityStatus.RECOVERED,
            UserActivityLevel.OPERATIONAL,
            event.timestamp,
            activity_id=degraded_id,
            completion_outcome="measurement_recovered",
        )
        self._publish(
            context,
            UserActivityType.MEASUREMENT_RECOVERED,
            UserActivityStatus.RECOVERED,
            UserActivityLevel.OPERATIONAL,
            event.timestamp,
            completion_outcome="valid_measurement_restored",
        )

    def _demand_cancelled(self, event: OperationalEvent) -> None:
        if event.activity_id is None:
            return
        context = self._open.get(event.activity_id)
        if context is None:
            return
        self._capture(context, event)
        if context.heating_started_at is None:
            self._publish(
                context,
                UserActivityType.HEAT_DEMAND_CANCELLED,
                UserActivityStatus.CANCELLED,
                UserActivityLevel.DEBUG,
                event.timestamp,
                discriminator=event.zone_id,
                completion_outcome="demand_cancelled",
            )
        if _detail(event, "building_episode_cancelled") is True:
            self._open.pop(context.lifecycle_id, None)

    def _runtime_failsafe(self, event: OperationalEvent) -> None:
        context = self._start(event)
        if context is None:
            return
        self._capture(context, event)
        self._publish(
            context,
            UserActivityType.RUNTIME_FAILSAFE_ENTERED,
            UserActivityStatus.OPEN,
            UserActivityLevel.OPERATIONAL,
            event.timestamp,
        )

    def _runtime_recovered(self, event: OperationalEvent) -> None:
        context = self._pop_context(event)
        if context is None:
            return
        self._capture(context, event)
        self._publish(
            context,
            UserActivityType.RUNTIME_FAILSAFE_ENTERED,
            UserActivityStatus.RECOVERED,
            UserActivityLevel.OPERATIONAL,
            event.timestamp,
            completion_outcome="normal_runtime_restored",
        )
        self._publish(
            context,
            UserActivityType.RUNTIME_RECOVERED,
            UserActivityStatus.RECOVERED,
            UserActivityLevel.OPERATIONAL,
            event.timestamp,
            completion_outcome="normal_runtime_restored",
        )

    def _restart_exhausted(self, event: OperationalEvent) -> None:
        context = self._start(event)
        if context is None:
            return
        self._capture(context, event)
        self._publish(
            context,
            UserActivityType.RUNTIME_RESTART_EXHAUSTED,
            UserActivityStatus.FAILED,
            UserActivityLevel.CRITICAL,
            event.timestamp,
            completion_outcome="restart_budget_exhausted",
        )

    def _pop_context(self, event: OperationalEvent) -> _Lifecycle | None:
        if event.activity_id is None:
            return None
        return self._open.pop(event.activity_id, None)

    def _context(self, event: OperationalEvent) -> _Lifecycle | None:
        if event.activity_id is None:
            return None
        return self._open.get(event.activity_id)

    def _publish(
        self,
        context: _Lifecycle,
        activity_type: UserActivityType,
        status: UserActivityStatus,
        level: UserActivityLevel,
        timestamp: datetime,
        *,
        started_at: datetime | None = None,
        activity_id: str | None = None,
        discriminator: str | None = None,
        completion_outcome: str | None = None,
    ) -> None:
        parameters = dict(context.parameters)
        if context.source_events_truncated:
            parameters["source_events_truncated"] = context.source_events_truncated
        bounded_parameters = tuple(
            UserActivityParameter(key, value) for key, value in sorted(parameters.items())[:MAX_ACTIVITY_PARAMETERS]
        )
        self.stream.publish(
            UserActivity(
                activity_id=activity_id
                or user_activity_id(activity_type, context.lifecycle_id, discriminator=discriminator),
                activity_type=activity_type,
                status=status,
                level=level,
                started_at=started_at or context.started_at,
                updated_at=timestamp,
                completed_at=None if status is UserActivityStatus.OPEN else timestamp,
                source_event_ids=tuple(sorted(context.source_event_ids)),
                correlation_id=context.lifecycle_id,
                zone_ids=tuple(sorted(context.zone_ids)),
                source_ids=tuple(sorted(context.source_ids)),
                requested_action=context.requested_action,
                command_outcome=context.command_outcome,
                reported_state=context.reported_state,
                reason_code=context.reason_code,
                completion_outcome=completion_outcome,
                parameters=bounded_parameters,
            )
        )


def _detail(event: OperationalEvent, key: str) -> str | int | float | bool | None:
    return next((detail.value for detail in event.details if detail.key == key), None)
