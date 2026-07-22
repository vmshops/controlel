from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heating_action import HeatingAction


class HeatSourceCommand(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    command_type: CommandFamily
    action: HeatingAction

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")

        return value

    @field_validator("command_type")
    @classmethod
    def command_type_must_be_heating(
        cls,
        value: CommandFamily,
    ) -> CommandFamily:
        if value is not CommandFamily.HEATING:
            raise ValueError("command_type must be CommandFamily.HEATING")

        return value
