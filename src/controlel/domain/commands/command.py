from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Command(BaseModel):
    """
    Base domain command.

    Commands represent an intention to perform an action.
    """

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    command_type: str

    model_config = {"frozen": True}
