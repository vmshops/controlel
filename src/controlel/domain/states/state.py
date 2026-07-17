from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class State(BaseModel):
    """
    Base domain state.

    State represents the current known condition
    of something in the system.
    """

    id: UUID = Field(default_factory=uuid4)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    state_type: str

    model_config = {"frozen": True}
