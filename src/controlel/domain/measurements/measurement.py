from datetime import UTC, datetime

from pydantic import BaseModel, Field

from controlel.domain.value_objects.temperature import Temperature


class Measurement(BaseModel):
    """
    Represents a measured value from a source.
    """

    value: Temperature

    source: str

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
