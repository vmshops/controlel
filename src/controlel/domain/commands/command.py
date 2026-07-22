from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.value_objects.zone_id import ZoneId


class Command(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    zone_id: ZoneId
    command_type: CommandFamily
    action: HeatingAction
