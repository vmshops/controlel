from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.value_objects.zone_id import ZoneId


class BuildingHeatDemand(BaseModel):
    status: BuildingHeatDemandStatus
    evaluated_at: datetime
    eligible_demands: tuple[ZoneDemand, ...]
    missing_zone_ids: tuple[ZoneId, ...]
    expired_zone_ids: tuple[ZoneId, ...]
    future_dated_zone_ids: tuple[ZoneId, ...]

    model_config = ConfigDict(frozen=True)

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")

        return value

    @model_validator(mode="after")
    def uncertainty_categories_must_be_disjoint(self) -> "BuildingHeatDemand":
        categories = (
            self.missing_zone_ids,
            self.expired_zone_ids,
            self.future_dated_zone_ids,
        )
        seen: set[ZoneId] = set()
        for category in categories:
            for zone_id in category:
                if zone_id in seen:
                    raise ValueError(f"ZoneId '{zone_id.value}' appears in multiple uncertainty categories")
                seen.add(zone_id)

        return self
