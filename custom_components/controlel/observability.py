"""Profile-controlled Home Assistant presentation refresh and diagnostics."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .const import (
    DIAGNOSTIC_PROFILE_BASIC,
    DIAGNOSTIC_PROFILE_DEBUG,
    DIAGNOSTIC_PROFILE_DETAILED,
)
from .operational import (
    TRACE_LIMITS,
    OperationalSnapshot,
    OperationalSnapshotSource,
    active_countdown_names,
)

type Unsubscribe = Callable[[], None]
type IntervalSubscriber = Callable[
    [object, Callable[[datetime], None], timedelta],
    Unsubscribe,
]

PROFILE_REFRESH_CADENCE_SECONDS: dict[str, float | None] = {
    DIAGNOSTIC_PROFILE_BASIC: None,
    DIAGNOSTIC_PROFILE_DETAILED: 10.0,
    DIAGNOSTIC_PROFILE_DEBUG: 1.0,
}

_BASIC_LOG_FIELDS = (
    "safety_state",
    "recoverable_failure_active",
    "fatal_failure_active",
    "emergency_disable_outcome",
)
_DETAILED_LOG_FIELDS = (
    *_BASIC_LOG_FIELDS,
    "raw_zone_heat_demand",
    "hysteresis_demand",
    "zone_heat_demand",
    "source_control_state",
    "active_lockout_type",
    "deferred_command",
    "deferred_reason",
)
_DEBUG_LOG_FIELDS = (
    *_DETAILED_LOG_FIELDS,
    "latest_input_status",
    "active_demand_cause",
    "last_requested_command",
    "last_command_outcome",
    "safety_bypassed_lockout",
)


class HomeAssistantTaskOwner(Protocol):
    """Minimum Home Assistant surface needed by the controller."""


class ObservabilityController:
    """Own exactly one profile refresh subscription for one runtime."""

    def __init__(
        self,
        *,
        hass: HomeAssistantTaskOwner,
        source: OperationalSnapshotSource,
        configured_profile: str,
        profile_before_debug: str,
        debug_duration: timedelta | None,
        interval_subscriber: IntervalSubscriber,
        logger: logging.Logger,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._hass = hass
        self._source = source
        self._active_profile = configured_profile
        self._profile_before_debug = profile_before_debug
        self._debug_duration = debug_duration
        self._interval_subscriber = interval_subscriber
        self._logger = logger
        self._now = now or (lambda: datetime.now(UTC))
        self._unsubscribe_source: Unsubscribe | None = None
        self._unsubscribe_interval: Unsubscribe | None = None
        self._installed_cadence: float | None = None
        self._generation = 0
        self._started = False
        self._stopped = False
        self._last_logged_snapshot: OperationalSnapshot | None = None

    @property
    def active_profile(self) -> str:
        return self._active_profile

    @property
    def refresh_cadence_seconds(self) -> float | None:
        return PROFILE_REFRESH_CADENCE_SECONDS[self._active_profile]

    @property
    def trace_capacity(self) -> int:
        return TRACE_LIMITS[self._active_profile]

    def start(self) -> None:
        """Start profile ownership after the runtime has initialized."""

        if self._started or self._stopped:
            return
        self._started = True
        now = self._now()
        debug_deadline = (
            now + self._debug_duration
            if self._active_profile == DIAGNOSTIC_PROFILE_DEBUG and self._debug_duration is not None
            else None
        )
        self._source.set_trace_capacity(self.trace_capacity)
        self._source.update(
            now=now,
            diagnostic_profile=self._active_profile,
            diagnostic_refresh_cadence_seconds=self.refresh_cadence_seconds,
            debug_expiry_deadline=debug_deadline,
            trace_capacity=self.trace_capacity,
        )
        self._last_logged_snapshot = self._source.current
        self._unsubscribe_source = self._source.subscribe(self._on_snapshot)
        self._schedule_for(self._source.current)
        self._logger.info(
            "Controlel diagnostic profile active profile=%s cadence_seconds=%s trace_capacity=%s",
            self._active_profile,
            self.refresh_cadence_seconds,
            self.trace_capacity,
        )

    def stop(self) -> None:
        """Cancel refresh ownership and reject every stale callback."""

        if self._stopped:
            return
        self._stopped = True
        self._generation += 1
        self._cancel_interval()
        if self._unsubscribe_source is not None:
            self._unsubscribe_source()
            self._unsubscribe_source = None

    def diagnostics(self, now: datetime) -> dict[str, object]:
        """Return the allowlisted profile and countdown evidence."""

        snapshot = self._source.snapshot_at(now)
        return {
            "active_profile": self._active_profile,
            "configured_refresh_cadence_seconds": self.refresh_cadence_seconds,
            "debug_expiry_deadline": (
                snapshot.debug_expiry_deadline.isoformat() if snapshot.debug_expiry_deadline is not None else None
            ),
            "debug_expiry_remaining_seconds": snapshot.debug_expiry_remaining_seconds,
            "trace_capacity": self.trace_capacity,
            "trace_record_count": len(self._source.trace),
            "active_countdown_names": list(active_countdown_names(snapshot)),
            "configured_durations_seconds": {
                "primary_measurement_maximum_age": snapshot.primary_measurement_max_age_seconds,
                "sensor_failure_grace": snapshot.sensor_failure_grace_period_seconds,
                "minimum_heating_on": snapshot.minimum_heating_on_time_seconds,
                "minimum_heating_off": snapshot.minimum_heating_off_time_seconds,
            },
            "deadlines": {
                "measurement_maximum_age": _iso(snapshot.measurement_stale_deadline),
                "sensor_failure_grace": _iso(snapshot.grace_deadline),
                "minimum_heating_on": _iso(snapshot.minimum_on_deadline),
                "minimum_heating_off": _iso(snapshot.minimum_off_deadline),
                "debug_profile_expiry": _iso(snapshot.debug_expiry_deadline),
            },
            "remaining_durations_seconds": {
                "measurement_maximum_age": snapshot.measurement_stale_remaining_seconds,
                "sensor_failure_grace": snapshot.grace_remaining_seconds,
                "minimum_heating_on_or_off": snapshot.lockout_remaining_seconds,
                "debug_profile_expiry": snapshot.debug_expiry_remaining_seconds,
            },
            "countdowns": _countdown_evidence(snapshot),
            "summary": {
                "machine_code": snapshot.operational_summary_code.value,
                "translation_key": snapshot.operational_summary_translation_key,
            },
        }

    def _on_snapshot(self, snapshot: OperationalSnapshot) -> None:
        if self._stopped:
            return
        self._log_transitions(snapshot)
        self._schedule_for(snapshot)

    def _schedule_for(self, snapshot: OperationalSnapshot) -> None:
        cadence = self.refresh_cadence_seconds
        desired = cadence if cadence is not None and active_countdown_names(snapshot) else None
        if desired == self._installed_cadence:
            return
        self._generation += 1
        self._cancel_interval()
        if desired is None or self._stopped:
            return
        generation = self._generation

        def tick(now: datetime) -> None:
            self._on_tick(generation, now)

        self._unsubscribe_interval = self._interval_subscriber(
            self._hass,
            tick,
            timedelta(seconds=desired),
        )
        self._installed_cadence = desired

    def _on_tick(self, generation: int, now: datetime) -> None:
        if self._stopped or generation != self._generation:
            return
        snapshot = self._source.snapshot_at(now)
        if (
            self._active_profile == DIAGNOSTIC_PROFILE_DEBUG
            and snapshot.debug_expiry_deadline is not None
            and now >= snapshot.debug_expiry_deadline
        ):
            self._expire_debug(now)
            return
        refreshed = self._source.refresh_elapsed(now)
        self._schedule_for(refreshed)
        if self._active_profile == DIAGNOSTIC_PROFILE_DEBUG:
            self._logger.debug(
                "Controlel diagnostic countdown refresh active=%s",
                active_countdown_names(refreshed),
            )

    def _expire_debug(self, now: datetime) -> None:
        previous = self._active_profile
        self._active_profile = (
            self._profile_before_debug
            if self._profile_before_debug in {DIAGNOSTIC_PROFILE_BASIC, DIAGNOSTIC_PROFILE_DETAILED}
            else DIAGNOSTIC_PROFILE_DETAILED
        )
        self._generation += 1
        self._cancel_interval()
        self._source.set_trace_capacity(self.trace_capacity)
        self._source.update(
            now=now,
            diagnostic_profile=self._active_profile,
            diagnostic_refresh_cadence_seconds=self.refresh_cadence_seconds,
            debug_expiry_deadline=None,
            debug_expiry_remaining_seconds=None,
            trace_capacity=self.trace_capacity,
        )
        self._logger.info(
            "Controlel diagnostic profile transitioned previous=%s current=%s reason=debug_expired",
            previous,
            self._active_profile,
        )

    def _cancel_interval(self) -> None:
        unsubscribe = self._unsubscribe_interval
        self._unsubscribe_interval = None
        self._installed_cadence = None
        if unsubscribe is not None:
            unsubscribe()

    def _log_transitions(self, snapshot: OperationalSnapshot) -> None:
        previous = self._last_logged_snapshot
        self._last_logged_snapshot = snapshot
        if previous is None:
            return
        fields = {
            DIAGNOSTIC_PROFILE_BASIC: _BASIC_LOG_FIELDS,
            DIAGNOSTIC_PROFILE_DETAILED: _DETAILED_LOG_FIELDS,
            DIAGNOSTIC_PROFILE_DEBUG: _DEBUG_LOG_FIELDS,
        }[self._active_profile]
        changes = [
            f"{field}:{getattr(previous, field)}->{getattr(snapshot, field)}"
            for field in fields
            if getattr(previous, field) != getattr(snapshot, field)
        ]
        if not changes:
            return
        message = "Controlel observable transitions %s"
        if self._active_profile == DIAGNOSTIC_PROFILE_DEBUG:
            self._logger.debug(message, " ".join(changes))
        else:
            self._logger.info(message, " ".join(changes))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _countdown_evidence(snapshot: OperationalSnapshot) -> dict[str, dict[str, object]]:
    minimum_on_active = (
        snapshot.active_lockout_type is not None
        and snapshot.active_lockout_type.value == "minimum_on"
        and snapshot.lockout_remaining_seconds is not None
    )
    minimum_off_active = (
        snapshot.active_lockout_type is not None
        and snapshot.active_lockout_type.value == "minimum_off"
        and snapshot.lockout_remaining_seconds is not None
    )
    return {
        "measurement_maximum_age": _countdown(
            snapshot.primary_measurement_max_age_seconds,
            snapshot.measurement_stale_deadline,
            snapshot.measurement_stale_remaining_seconds,
            reason="fresh_measurement_validity",
            expiry_action="reevaluate_measurement_validity",
        ),
        "sensor_failure_grace": _countdown(
            snapshot.sensor_failure_grace_period_seconds,
            snapshot.grace_deadline,
            snapshot.grace_remaining_seconds,
            reason="indeterminate_primary_measurement",
            expiry_action="apply_configured_timeout_action",
        ),
        "minimum_heating_on": _countdown(
            snapshot.minimum_heating_on_time_seconds,
            snapshot.minimum_on_deadline if minimum_on_active else None,
            snapshot.lockout_remaining_seconds if minimum_on_active else None,
            reason="successful_enable_command",
            expiry_action="reevaluate_current_source_demand",
        ),
        "minimum_heating_off": _countdown(
            snapshot.minimum_heating_off_time_seconds,
            snapshot.minimum_off_deadline if minimum_off_active else None,
            snapshot.lockout_remaining_seconds if minimum_off_active else None,
            reason="successful_disable_command",
            expiry_action="reevaluate_current_source_demand",
        ),
        "deferred_source_command": _countdown(
            None,
            (
                snapshot.minimum_on_deadline
                if minimum_on_active
                else snapshot.minimum_off_deadline
                if minimum_off_active
                else None
            ),
            snapshot.lockout_remaining_seconds,
            reason=snapshot.deferred_reason or "no_deferred_command",
            expiry_action="reevaluate_current_source_demand",
        ),
        "debug_profile_expiry": _countdown(
            snapshot.debug_profile_duration_seconds,
            snapshot.debug_expiry_deadline,
            snapshot.debug_expiry_remaining_seconds,
            reason="automatic_debug_expiry",
            expiry_action="restore_previous_diagnostic_profile",
        ),
    }


def _countdown(
    configured_duration_seconds: float | None,
    deadline: datetime | None,
    remaining_seconds: float | None,
    *,
    reason: str,
    expiry_action: str,
) -> dict[str, object]:
    return {
        "configured_duration_seconds": configured_duration_seconds,
        "active": remaining_seconds is not None,
        "deadline": _iso(deadline) if remaining_seconds is not None else None,
        "remaining_seconds": remaining_seconds,
        "reason": reason,
        "expiry_action": expiry_action,
    }
