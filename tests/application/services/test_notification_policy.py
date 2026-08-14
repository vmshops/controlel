"""Tests for exhaustive activity-driven notification policy."""

from controlel.application.services.notification_policy import ACTIVITY_NOTIFICATION_RULES
from controlel.domain.user_activities import UserActivityStatus, UserActivityType


def test_every_activity_type_has_an_explicit_nonempty_policy() -> None:
    assert set(ACTIVITY_NOTIFICATION_RULES) == set(UserActivityType)
    assert all(rule.notifiable_statuses for rule in ACTIVITY_NOTIFICATION_RULES.values())


def test_lifecycle_stages_are_explicit() -> None:
    assert ACTIVITY_NOTIFICATION_RULES[UserActivityType.MEASUREMENT_DEGRADED].notifiable_statuses == {
        UserActivityStatus.OPEN
    }
    assert ACTIVITY_NOTIFICATION_RULES[UserActivityType.MEASUREMENT_RECOVERED].notifiable_statuses == {
        UserActivityStatus.RECOVERED
    }
    assert ACTIVITY_NOTIFICATION_RULES[UserActivityType.RUNTIME_RESTART_EXHAUSTED].notifiable_statuses == {
        UserActivityStatus.FAILED
    }
