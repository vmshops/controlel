from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Event(BaseModel):
    """
    Base domain event.

    Events represent something that happened in the system.
    They are immutable facts.
    """

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: str

    model_config = {"frozen": True}
