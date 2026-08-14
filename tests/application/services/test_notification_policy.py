"""Tests for the explicit M31B event notification mapping."""

from controlel.application.services.notification_policy import (
    NOTIFICATION_LEVEL_BY_EVENT_CODE,
    notification_level_for_event,
)
from controlel.domain.notifications import NotificationLevel
from controlel.domain.operational_events import OperationalEventCode


def test_every_operational_event_code_has_one_explicit_notification_level() -> None:
    assert set(NOTIFICATION_LEVEL_BY_EVENT_CODE) == set(OperationalEventCode)
    assert all(notification_level_for_event(code) is level for code, level in NOTIFICATION_LEVEL_BY_EVENT_CODE.items())


def test_required_initial_mapping() -> None:
    assert notification_level_for_event(OperationalEventCode.RUNTIME_FATAL) is NotificationLevel.CRITICAL
    assert notification_level_for_event(OperationalEventCode.RESTART_BUDGET_EXHAUSTED) is NotificationLevel.CRITICAL
    assert notification_level_for_event(OperationalEventCode.FAILSAFE_ENTERED) is NotificationLevel.OPERATIONAL
    assert notification_level_for_event(OperationalEventCode.MEASUREMENT_RECOVERED) is NotificationLevel.OPERATIONAL
    assert notification_level_for_event(OperationalEventCode.HEAT_DEMAND_CONFIRMED) is NotificationLevel.DETAILED
    assert (
        notification_level_for_event(OperationalEventCode.REPORTED_SOURCE_STATE_CHANGED) is NotificationLevel.DETAILED
    )
    assert notification_level_for_event(OperationalEventCode.MEASUREMENT_BECAME_VALID) is NotificationLevel.DEBUG
