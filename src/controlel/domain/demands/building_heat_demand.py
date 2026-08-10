from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.demands.zone_heat_demand_input import ZoneHeatDemandInput
from controlel.domain.value_objects.zone_id import ZoneId


class BuildingHeatDemandReason(StrEnum):
    HEAT_REQUIRED_BY_ZONE = "heat_required_by_zone"
    HEAT_REQUIRED_BY_MULTIPLE_ZONES = "heat_required_by_multiple_zones"
    NO_ZONE_REQUIRES_HEAT = "no_zone_requires_heat"
    ALL_ZONES_INDETERMINATE = "all_zones_indeterminate"
    INDETERMINATE_ACTIVE_DEMAND_PRESERVED = "indeterminate_active_demand_preserved"
    NO_ZONES_CONFIGURED = "no_zones_configured"


class BuildingHeatDemand(BaseModel):
    status: BuildingHeatDemandStatus
    evaluated_at: datetime
    eligible_demands: tuple[ZoneDemand, ...]
    missing_zone_ids: tuple[ZoneId, ...]
    expired_zone_ids: tuple[ZoneId, ...]
    future_dated_zone_ids: tuple[ZoneId, ...]
    zone_inputs: tuple[ZoneHeatDemandInput, ...] = ()
    contributing_heat_zone_ids: tuple[ZoneId, ...] = ()
    no_heat_zone_ids: tuple[ZoneId, ...] = ()
    indeterminate_zone_ids: tuple[ZoneId, ...] = ()
    reason: BuildingHeatDemandReason = BuildingHeatDemandReason.NO_ZONES_CONFIGURED
    zone_count: int = 0
    heat_requesting_zone_count: int = 0

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

        aggregate_categories = (
            self.contributing_heat_zone_ids,
            self.no_heat_zone_ids,
            self.indeterminate_zone_ids,
        )
        aggregate_seen: set[ZoneId] = set()
        for category in aggregate_categories:
            if category != tuple(sorted(category, key=lambda zone_id: zone_id.value)):
                raise ValueError("aggregate zone IDs must be sorted by stable zone_id")
            for zone_id in category:
                if zone_id in aggregate_seen:
                    raise ValueError(f"ZoneId '{zone_id.value}' appears in multiple aggregate categories")
                aggregate_seen.add(zone_id)
        if self.zone_inputs != tuple(sorted(self.zone_inputs, key=lambda item: item.zone_id.value)):
            raise ValueError("zone_inputs must be sorted by stable zone_id")
        if self.zone_count != len(self.zone_inputs):
            raise ValueError("zone_count must match zone_inputs")
        if self.heat_requesting_zone_count != len(self.contributing_heat_zone_ids):
            raise ValueError("heat_requesting_zone_count must match contributing_heat_zone_ids")

        return self
