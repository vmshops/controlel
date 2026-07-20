from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class Decision(BaseModel):
    """
    Represents a regulation decision.
    """

    action: str

    reason: str | None = None

    metadata: dict[str, Any] | None = None

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
