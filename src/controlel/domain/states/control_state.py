from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.value_objects.zone_id import ZoneId


class ControlState(BaseModel):
    """
    Represents the latest successfully applied logical zone action.
    """

    zone_id: ZoneId
    applied_action: HeatingAction
    command_id: UUID
    applied_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = ConfigDict(frozen=True)

    @field_validator("applied_at")
    @classmethod
    def applied_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("applied_at must be timezone-aware")

        return value
