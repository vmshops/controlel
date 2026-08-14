"""Deterministic notification policy over canonical user activities."""

from dataclasses import dataclass

from controlel.domain.notifications import NotificationLevel
from controlel.domain.operational_events import OperationalEventCategory, OperationalEventCode
from controlel.domain.user_activities import UserActivityStatus, UserActivityType


@dataclass(frozen=True, slots=True)
class ActivityNotificationRule:
    """Explicit category and notifiable lifecycle stages for one activity type."""

    category: OperationalEventCategory
    notifiable_statuses: frozenset[UserActivityStatus]


ACTIVITY_NOTIFICATION_RULES: dict[UserActivityType, ActivityNotificationRule] = {
    UserActivityType.HEATING_STARTED: ActivityNotificationRule(
        OperationalEventCategory.DEMAND, frozenset({UserActivityStatus.COMPLETED})
    ),
    UserActivityType.HEATING_STOPPED: ActivityNotificationRule(
        OperationalEventCategory.DEMAND, frozenset({UserActivityStatus.COMPLETED})
    ),
    UserActivityType.HEAT_DEMAND_CANCELLED: ActivityNotificationRule(
        OperationalEventCategory.DEMAND, frozenset({UserActivityStatus.CANCELLED})
    ),
    UserActivityType.SOURCE_STATE_CORRECTED: ActivityNotificationRule(
        OperationalEventCategory.SOURCE_RESILIENCE, frozenset({UserActivityStatus.COMPLETED})
    ),
    UserActivityType.SOURCE_CORRECTION_FAILED: ActivityNotificationRule(
        OperationalEventCategory.SOURCE_RESILIENCE, frozenset({UserActivityStatus.FAILED})
    ),
    UserActivityType.SOURCE_COMMAND_FAILED: ActivityNotificationRule(
        OperationalEventCategory.SOURCE_CONTROL, frozenset({UserActivityStatus.FAILED})
    ),
    UserActivityType.MEASUREMENT_DEGRADED: ActivityNotificationRule(
        OperationalEventCategory.MEASUREMENT, frozenset({UserActivityStatus.OPEN})
    ),
    UserActivityType.MEASUREMENT_RECOVERED: ActivityNotificationRule(
        OperationalEventCategory.MEASUREMENT, frozenset({UserActivityStatus.RECOVERED})
    ),
    UserActivityType.SAFETY_FALLBACK_APPLIED: ActivityNotificationRule(
        OperationalEventCategory.SAFETY, frozenset({UserActivityStatus.COMPLETED})
    ),
    UserActivityType.RUNTIME_FAILSAFE_ENTERED: ActivityNotificationRule(
        OperationalEventCategory.SUPERVISION, frozenset({UserActivityStatus.OPEN})
    ),
    UserActivityType.RUNTIME_RECOVERED: ActivityNotificationRule(
        OperationalEventCategory.RUNTIME, frozenset({UserActivityStatus.RECOVERED})
    ),
    UserActivityType.RUNTIME_RESTART_EXHAUSTED: ActivityNotificationRule(
        OperationalEventCategory.SUPERVISION, frozenset({UserActivityStatus.FAILED})
    ),
}

if set(ACTIVITY_NOTIFICATION_RULES) != set(UserActivityType):
    raise RuntimeError("every UserActivityType must have an explicit notification rule")


def notification_rule_for_activity(activity_type: UserActivityType) -> ActivityNotificationRule:
    """Return the explicit notification rule for one canonical activity type."""

    return ACTIVITY_NOTIFICATION_RULES[activity_type]


# Deprecated compatibility surface for Core 0.8 consumers. The activity planner
# intentionally does not use this technical-event mapping.
NOTIFICATION_LEVEL_BY_EVENT_CODE: dict[OperationalEventCode, NotificationLevel] = {
    OperationalEventCode.RUNTIME_STARTED: NotificationLevel.DETAILED,
    OperationalEventCode.RUNTIME_STOPPED: NotificationLevel.DETAILED,
    OperationalEventCode.RUNTIME_FATAL: NotificationLevel.CRITICAL,
    OperationalEventCode.RUNTIME_RECOVERED: NotificationLevel.OPERATIONAL,
    OperationalEventCode.MEASUREMENT_BECAME_VALID: NotificationLevel.DEBUG,
    OperationalEventCode.MEASUREMENT_BECAME_STALE: NotificationLevel.OPERATIONAL,
    OperationalEventCode.MEASUREMENT_BECAME_UNAVAILABLE: NotificationLevel.OPERATIONAL,
    OperationalEventCode.MEASUREMENT_RECOVERED: NotificationLevel.OPERATIONAL,
    OperationalEventCode.HEAT_DEMAND_STARTED: NotificationLevel.DETAILED,
    OperationalEventCode.HEAT_DEMAND_CONFIRMED: NotificationLevel.DETAILED,
    OperationalEventCode.HEAT_DEMAND_CANCELLED: NotificationLevel.DETAILED,
    OperationalEventCode.HEAT_DEMAND_SATISFIED: NotificationLevel.DETAILED,
    OperationalEventCode.SAFETY_GRACE_STARTED: NotificationLevel.OPERATIONAL,
    OperationalEventCode.SAFETY_GRACE_EXPIRED: NotificationLevel.CRITICAL,
    OperationalEventCode.SAFETY_DISABLE_REQUESTED: NotificationLevel.CRITICAL,
    OperationalEventCode.EMERGENCY_DISABLE_REQUESTED: NotificationLevel.CRITICAL,
    OperationalEventCode.SOURCE_ENABLE_REQUESTED: NotificationLevel.DETAILED,
    OperationalEventCode.SOURCE_DISABLE_REQUESTED: NotificationLevel.DETAILED,
    OperationalEventCode.SOURCE_COMMAND_DISPATCHED: NotificationLevel.DETAILED,
    OperationalEventCode.SOURCE_COMMAND_FAILED: NotificationLevel.OPERATIONAL,
    OperationalEventCode.SOURCE_COMMAND_DEFERRED_MINIMUM_ON: NotificationLevel.DETAILED,
    OperationalEventCode.SOURCE_COMMAND_DEFERRED_MINIMUM_OFF: NotificationLevel.DETAILED,
    OperationalEventCode.REPORTED_SOURCE_STATE_CHANGED: NotificationLevel.DETAILED,
    OperationalEventCode.SOURCE_DRIFT_DETECTED: NotificationLevel.DETAILED,
    OperationalEventCode.SOURCE_RECONCILIATION_STARTED: NotificationLevel.DETAILED,
    OperationalEventCode.SOURCE_RECONCILIATION_COMPLETED: NotificationLevel.DETAILED,
    OperationalEventCode.CORRECTIVE_ACTION_HELD: NotificationLevel.DETAILED,
    OperationalEventCode.CORRECTIVE_ACTION_DISPATCHED: NotificationLevel.OPERATIONAL,
    OperationalEventCode.FAILSAFE_ENTERED: NotificationLevel.OPERATIONAL,
    OperationalEventCode.FAILSAFE_EXITED: NotificationLevel.OPERATIONAL,
    OperationalEventCode.RESTART_ATTEMPT_STARTED: NotificationLevel.DETAILED,
    OperationalEventCode.RESTART_ATTEMPT_FAILED: NotificationLevel.OPERATIONAL,
    OperationalEventCode.RESTART_BUDGET_EXHAUSTED: NotificationLevel.CRITICAL,
    OperationalEventCode.COMMAND_AUTHORITY_CHANGED: NotificationLevel.DETAILED,
}


def notification_level_for_event(code: OperationalEventCode) -> NotificationLevel:
    """Return the legacy technical-event preference mapping."""

    return NOTIFICATION_LEVEL_BY_EVENT_CODE[code]
