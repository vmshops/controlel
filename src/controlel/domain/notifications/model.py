"""Immutable, localization-neutral notification contracts."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite

from controlel.domain.operational_events import OperationalEventCategory
from controlel.domain.operational_events.model import OperationalEventScalar
from controlel.domain.user_activities import MAX_ACTIVITY_SOURCES, MAX_ACTIVITY_ZONES, UserActivityType

DEFAULT_NOTIFICATION_MAXIMUM_PER_WINDOW = 10
DEFAULT_NOTIFICATION_RATE_WINDOW = timedelta(minutes=1)
DEFAULT_CRITICAL_MAXIMUM_PER_WINDOW = 20
DEFAULT_CRITICAL_RATE_WINDOW = timedelta(minutes=1)
DEFAULT_NOTIFICATION_HISTORY_CAPACITY = 100
MAX_NOTIFICATION_RECIPIENTS = 16
MAX_NOTIFICATION_MAXIMUM_PER_WINDOW = 100
MAX_NOTIFICATION_RATE_WINDOW = timedelta(days=1)
MAX_CRITICAL_MAXIMUM_PER_WINDOW = 200
MAX_CRITICAL_RATE_WINDOW = timedelta(days=1)
MAX_NOTIFICATION_HISTORY_CAPACITY = 1_000
MAX_NOTIFICATION_PARAMETERS = 64


class NotificationLevel(StrEnum):
    """User attention preference, intentionally distinct from event severity."""

    CRITICAL = "critical"
    OPERATIONAL = "operational"
    DETAILED = "detailed"
    DEBUG = "debug"


class NotificationDeliveryStatus(StrEnum):
    """Normalized notification planning or transport outcome."""

    DELIVERED = "delivered"
    FAILED = "failed"
    SUPPRESSED_POLICY = "suppressed_policy"
    SUPPRESSED_DUPLICATE = "suppressed_duplicate"
    RATE_LIMITED = "rate_limited"
    NO_RECIPIENT = "no_recipient"


@dataclass(frozen=True, slots=True)
class NotificationParameter:
    """One allowlisted JSON-safe localization parameter."""

    key: str
    value: OperationalEventScalar

    def __post_init__(self) -> None:
        if not self.key or not self.key.isascii() or not self.key.replace("_", "").isalnum():
            raise ValueError("parameter key must be a non-empty ASCII identifier")
        if isinstance(self.value, float) and not isfinite(self.value):
            raise ValueError("parameter float values must be finite")
        if not isinstance(self.value, str | int | float | bool | type(None)):
            raise TypeError("parameter value must be a JSON-safe scalar")


@dataclass(frozen=True, slots=True)
class NotificationRecipient:
    """Stable logical recipient and transport binding."""

    recipient_id: str
    transport: str
    target: str
    enabled: bool = True
    minimum_level: NotificationLevel = NotificationLevel.OPERATIONAL
    categories: tuple[OperationalEventCategory, ...] = ()

    def __post_init__(self) -> None:
        for value, label in (
            (self.recipient_id, "recipient_id"),
            (self.transport, "transport"),
            (self.target, "target"),
        ):
            if not value or not isinstance(value, str):
                raise ValueError(f"{label} must be a non-empty string")
        if not isinstance(self.minimum_level, NotificationLevel):
            raise TypeError("minimum_level must be a NotificationLevel")
        if self.categories != tuple(sorted(set(self.categories), key=lambda item: item.value)):
            raise ValueError("categories must be unique and sorted")


@dataclass(frozen=True, slots=True)
class NotificationPolicy:
    """Deterministic bounded policy configuration."""

    enabled: bool = False
    recipients: tuple[NotificationRecipient, ...] = ()
    maximum_per_window: int = DEFAULT_NOTIFICATION_MAXIMUM_PER_WINDOW
    rate_window: timedelta = DEFAULT_NOTIFICATION_RATE_WINDOW
    critical_maximum_per_window: int = DEFAULT_CRITICAL_MAXIMUM_PER_WINDOW
    critical_rate_window: timedelta = DEFAULT_CRITICAL_RATE_WINDOW
    history_capacity: int = DEFAULT_NOTIFICATION_HISTORY_CAPACITY

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")
        ids = tuple(recipient.recipient_id for recipient in self.recipients)
        if len(ids) != len(set(ids)):
            raise ValueError("recipient IDs must be unique")
        if len(self.recipients) > MAX_NOTIFICATION_RECIPIENTS:
            raise ValueError(f"recipients must not exceed {MAX_NOTIFICATION_RECIPIENTS}")
        enabled_bindings = tuple(
            (recipient.transport, recipient.target) for recipient in self.recipients if recipient.enabled
        )
        if len(enabled_bindings) != len(set(enabled_bindings)):
            raise ValueError("enabled recipient transport and target bindings must be unique")
        _bounded_integer(
            self.maximum_per_window,
            "maximum_per_window",
            MAX_NOTIFICATION_MAXIMUM_PER_WINDOW,
        )
        _bounded_duration(self.rate_window, "rate_window", MAX_NOTIFICATION_RATE_WINDOW)
        _bounded_integer(
            self.critical_maximum_per_window,
            "critical_maximum_per_window",
            MAX_CRITICAL_MAXIMUM_PER_WINDOW,
        )
        _bounded_duration(
            self.critical_rate_window,
            "critical_rate_window",
            MAX_CRITICAL_RATE_WINDOW,
        )
        _bounded_integer(
            self.history_capacity,
            "history_capacity",
            MAX_NOTIFICATION_HISTORY_CAPACITY,
        )


@dataclass(frozen=True, slots=True)
class NotificationIntent:
    """Semantic transport request without localized prose."""

    notification_id: str
    created_at: datetime
    level: NotificationLevel
    category: OperationalEventCategory
    title_code: str
    message_code: str
    source_activity_id: str
    activity_type: UserActivityType
    recipient_id: str
    correlation_id: str = ""
    zone_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    parameters: tuple[NotificationParameter, ...] = ()

    def __post_init__(self) -> None:
        if not self.notification_id or not self.source_activity_id or not self.recipient_id or not self.correlation_id:
            raise ValueError("notification, source-activity, recipient, and correlation IDs must not be empty")
        if not isinstance(self.activity_type, UserActivityType):
            raise TypeError("activity_type must be a UserActivityType")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if not self.title_code or not self.message_code:
            raise ValueError("title_code and message_code must not be empty")
        keys = tuple(parameter.key for parameter in self.parameters)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("parameters must have unique keys in deterministic sorted order")
        if len(self.parameters) > MAX_NOTIFICATION_PARAMETERS:
            raise ValueError(f"parameters must contain at most {MAX_NOTIFICATION_PARAMETERS} items")
        _sorted_strings(self.zone_ids, "zone_ids", MAX_ACTIVITY_ZONES)
        _sorted_strings(self.source_ids, "source_ids", MAX_ACTIVITY_SOURCES)


@dataclass(frozen=True, slots=True)
class NotificationDeliveryResult:
    """One immutable normalized planning or delivery result."""

    occurred_at: datetime
    status: NotificationDeliveryStatus
    source_activity_id: str
    recipient_id: str | None = None
    notification_id: str | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if not self.source_activity_id:
            raise ValueError("source_activity_id must not be empty")
        if self.status is NotificationDeliveryStatus.FAILED and not self.failure_code:
            raise ValueError("failed delivery requires a stable failure code")
        if self.status is not NotificationDeliveryStatus.FAILED and self.failure_code is not None:
            raise ValueError("only failed delivery may include a failure code")


def _bounded_integer(value: int, label: str, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{label} must be between 1 and {maximum}")


def _bounded_duration(value: timedelta, label: str, maximum: timedelta) -> None:
    if not isinstance(value, timedelta) or not timedelta(seconds=1) <= value <= maximum:
        raise ValueError(f"{label} must be between 1 second and {int(maximum.total_seconds())} seconds")


def _sorted_strings(values: tuple[str, ...], label: str, maximum: int) -> None:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{label} must be unique and sorted")
    if len(values) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} items")
