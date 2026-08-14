"""Tests for immutable notification domain contracts."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from controlel.domain.notifications import (
    NotificationDeliveryResult,
    NotificationDeliveryStatus,
    NotificationIntent,
    NotificationLevel,
    NotificationParameter,
    NotificationPolicy,
    NotificationRecipient,
)
from controlel.domain.operational_events import OperationalEventCategory
from controlel.domain.user_activities import UserActivityType


def test_notification_contracts_are_immutable_and_localization_neutral() -> None:
    recipient = NotificationRecipient(
        "family_phone",
        "test_transport",
        "endpoint:family_phone",
        categories=(OperationalEventCategory.RUNTIME,),
    )
    policy = NotificationPolicy(enabled=True, recipients=(recipient,))
    intent = NotificationIntent(
        "notification:00000001",
        datetime(2026, 1, 1, tzinfo=UTC),
        NotificationLevel.OPERATIONAL,
        OperationalEventCategory.RUNTIME,
        "notification_title_runtime_recovered",
        "notification_message_runtime_recovered",
        "activity:00000001",
        UserActivityType.RUNTIME_RECOVERED,
        recipient.recipient_id,
        "supervision:1",
        parameters=(NotificationParameter("reason_code", "runtime_recovered"),),
    )
    result = NotificationDeliveryResult(
        intent.created_at,
        NotificationDeliveryStatus.DELIVERED,
        intent.source_activity_id,
        intent.recipient_id,
        intent.notification_id,
    )

    with pytest.raises(FrozenInstanceError):
        policy.enabled = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        intent.title_code = "localized prose"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.status = NotificationDeliveryStatus.FAILED  # type: ignore[misc]


def test_recipient_and_parameter_validation_is_deterministic() -> None:
    with pytest.raises(ValueError, match="unique and sorted"):
        NotificationRecipient(
            "phone",
            "test_transport",
            "endpoint:phone",
            categories=(OperationalEventCategory.RUNTIME, OperationalEventCategory.RUNTIME),
        )
    with pytest.raises(ValueError, match="finite"):
        NotificationParameter("temperature", float("nan"))

    with pytest.raises(ValueError, match="zone_ids must be unique and sorted"):
        NotificationIntent(
            "notification:1",
            datetime(2026, 1, 1, tzinfo=UTC),
            NotificationLevel.OPERATIONAL,
            OperationalEventCategory.RUNTIME,
            "title",
            "message",
            "activity:1",
            UserActivityType.RUNTIME_RECOVERED,
            "phone",
            "supervision:1",
            zone_ids=("zone:2", "zone:1"),
        )


def test_policy_rejects_duplicate_enabled_transport_targets() -> None:
    recipients = (
        NotificationRecipient("phone_a", "test_transport", "endpoint:phone"),
        NotificationRecipient("phone_b", "test_transport", "endpoint:phone"),
    )

    with pytest.raises(ValueError, match="transport and target bindings must be unique"):
        NotificationPolicy(enabled=True, recipients=recipients)


def test_policy_rejects_duplicate_recipient_ids_independently_from_targets() -> None:
    recipients = (
        NotificationRecipient("phone", "test_transport", "endpoint:phone"),
        NotificationRecipient("phone", "test_transport", "endpoint:tablet"),
    )

    with pytest.raises(ValueError, match="recipient IDs must be unique"):
        NotificationPolicy(enabled=True, recipients=recipients)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("maximum_per_window", 0),
        ("maximum_per_window", 101),
        ("rate_window", timedelta(0)),
        ("rate_window", timedelta(days=1, seconds=1)),
        ("critical_maximum_per_window", 0),
        ("critical_maximum_per_window", 201),
        ("critical_rate_window", timedelta(0)),
        ("critical_rate_window", timedelta(days=1, seconds=1)),
        ("history_capacity", 0),
        ("history_capacity", 1_001),
    ],
)
def test_policy_rejects_out_of_range_bounded_configuration(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="must be between"):
        NotificationPolicy(**{field: value})  # type: ignore[arg-type]


def test_policy_accepts_all_hard_boundaries() -> None:
    policy = NotificationPolicy(
        maximum_per_window=100,
        rate_window=timedelta(days=1),
        critical_maximum_per_window=200,
        critical_rate_window=timedelta(days=1),
        history_capacity=1_000,
    )

    assert policy.maximum_per_window == 100
    assert policy.critical_maximum_per_window == 200
    assert policy.history_capacity == 1_000
