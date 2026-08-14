"""Deterministic notification policy over canonical operational events."""

from controlel.domain.notifications import NotificationLevel
from controlel.domain.operational_events import OperationalEventCode

CRITICAL = NotificationLevel.CRITICAL
OPERATIONAL = NotificationLevel.OPERATIONAL
DETAILED = NotificationLevel.DETAILED
DEBUG = NotificationLevel.DEBUG

NOTIFICATION_LEVEL_BY_EVENT_CODE: dict[OperationalEventCode, NotificationLevel] = {
    OperationalEventCode.RUNTIME_STARTED: DETAILED,
    OperationalEventCode.RUNTIME_STOPPED: DETAILED,
    OperationalEventCode.RUNTIME_FATAL: CRITICAL,
    OperationalEventCode.RUNTIME_RECOVERED: OPERATIONAL,
    OperationalEventCode.MEASUREMENT_BECAME_VALID: DEBUG,
    OperationalEventCode.MEASUREMENT_BECAME_STALE: OPERATIONAL,
    OperationalEventCode.MEASUREMENT_BECAME_UNAVAILABLE: OPERATIONAL,
    OperationalEventCode.MEASUREMENT_RECOVERED: OPERATIONAL,
    OperationalEventCode.HEAT_DEMAND_STARTED: DETAILED,
    OperationalEventCode.HEAT_DEMAND_CONFIRMED: DETAILED,
    OperationalEventCode.HEAT_DEMAND_CANCELLED: DETAILED,
    OperationalEventCode.HEAT_DEMAND_SATISFIED: DETAILED,
    OperationalEventCode.SAFETY_GRACE_STARTED: OPERATIONAL,
    OperationalEventCode.SAFETY_GRACE_EXPIRED: CRITICAL,
    OperationalEventCode.SAFETY_DISABLE_REQUESTED: CRITICAL,
    OperationalEventCode.EMERGENCY_DISABLE_REQUESTED: CRITICAL,
    OperationalEventCode.SOURCE_ENABLE_REQUESTED: DETAILED,
    OperationalEventCode.SOURCE_DISABLE_REQUESTED: DETAILED,
    OperationalEventCode.SOURCE_COMMAND_DISPATCHED: DETAILED,
    OperationalEventCode.SOURCE_COMMAND_FAILED: OPERATIONAL,
    OperationalEventCode.SOURCE_COMMAND_DEFERRED_MINIMUM_ON: DETAILED,
    OperationalEventCode.SOURCE_COMMAND_DEFERRED_MINIMUM_OFF: DETAILED,
    OperationalEventCode.REPORTED_SOURCE_STATE_CHANGED: DETAILED,
    OperationalEventCode.SOURCE_DRIFT_DETECTED: DETAILED,
    OperationalEventCode.SOURCE_RECONCILIATION_STARTED: DETAILED,
    OperationalEventCode.SOURCE_RECONCILIATION_COMPLETED: DETAILED,
    OperationalEventCode.CORRECTIVE_ACTION_HELD: DETAILED,
    OperationalEventCode.CORRECTIVE_ACTION_DISPATCHED: OPERATIONAL,
    OperationalEventCode.FAILSAFE_ENTERED: OPERATIONAL,
    OperationalEventCode.FAILSAFE_EXITED: OPERATIONAL,
    OperationalEventCode.RESTART_ATTEMPT_STARTED: DETAILED,
    OperationalEventCode.RESTART_ATTEMPT_FAILED: OPERATIONAL,
    OperationalEventCode.RESTART_BUDGET_EXHAUSTED: CRITICAL,
    OperationalEventCode.COMMAND_AUTHORITY_CHANGED: DETAILED,
}

if set(NOTIFICATION_LEVEL_BY_EVENT_CODE) != set(OperationalEventCode):
    raise RuntimeError("every OperationalEventCode must have an explicit notification level")


def notification_level_for_event(code: OperationalEventCode) -> NotificationLevel:
    """Return the documented initial notification level for one event code."""

    return NOTIFICATION_LEVEL_BY_EVENT_CODE[code]
