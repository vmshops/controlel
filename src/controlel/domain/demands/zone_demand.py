from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


class ZoneDemand(BaseModel):
    zone_id: ZoneId
    requires_heat: bool
    source_sensor_id: SensorId
    observed_at: datetime

    model_config = ConfigDict(frozen=True)

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

        return value
