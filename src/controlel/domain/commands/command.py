from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from controlel.domain.decisions.decision import Decision


class Command(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    command_type: str | None = None
    action: str | None = None

    @classmethod
    def from_decision(cls, decision: Decision) -> "Command":
        return cls(
            command_type=decision.action,
            action=decision.action,
        )
