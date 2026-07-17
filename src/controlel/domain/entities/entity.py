from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Entity(BaseModel):
    """
    Base entity for all domain objects.
    """

    id: UUID = Field(default_factory=uuid4)

    name: str

    enabled: bool = True

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {
        "validate_assignment": True,
    }

    def touch(self) -> None:
        """
        Update the modification timestamp.
        """
        self.updated_at = datetime.now(UTC)
