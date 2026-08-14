"""Public immutable user-activity contracts."""

from .model import (
    MAX_ACTIVITY_PARAMETERS,
    MAX_ACTIVITY_SOURCE_EVENTS,
    MAX_ACTIVITY_SOURCES,
    MAX_ACTIVITY_ZONES,
    UserActivity,
    UserActivityLevel,
    UserActivityParameter,
    UserActivityScalar,
    UserActivitySnapshot,
    UserActivityStatus,
    UserActivityType,
    user_activity_id,
)

__all__ = [
    "MAX_ACTIVITY_PARAMETERS",
    "MAX_ACTIVITY_SOURCE_EVENTS",
    "MAX_ACTIVITY_SOURCES",
    "MAX_ACTIVITY_ZONES",
    "UserActivity",
    "UserActivityLevel",
    "UserActivityParameter",
    "UserActivityScalar",
    "UserActivitySnapshot",
    "UserActivityStatus",
    "UserActivityType",
    "user_activity_id",
]
