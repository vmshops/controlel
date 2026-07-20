from datetime import UTC, datetime

from pydantic import BaseModel, Field

from controlel.domain.value_objects.temperature import Temperature


class Measurement(BaseModel):
    value: Temperature
    source: str | None = None

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    target: Temperature | None = None
