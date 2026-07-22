from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


class Decision(BaseModel):
    """
    Represents a regulation decision.
    """

    sensor_id: SensorId

    zone_id: ZoneId

    observed_at: datetime

    action: DecisionAction

    reason: str | None = None

    metadata: dict[str, Any] | None = None

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

        return value
