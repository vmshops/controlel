from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.value_objects.zone_id import ZoneId


class ZoneHeatDemandInputReason(StrEnum):
    ELIGIBLE = "eligible"
    MISSING = "missing"
    EXPIRED = "expired"
    FUTURE_DATED = "future_dated"


class ZoneHeatDemandInput(BaseModel):
    """Immutable, zone-owned demand presented to building aggregation."""

    zone_id: ZoneId
    demand: BuildingHeatDemandStatus
    reason: ZoneHeatDemandInputReason
    evidence: ZoneDemand | None = None
    preserves_confirmed_heat: bool = False

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def evidence_must_belong_to_zone(self) -> "ZoneHeatDemandInput":
        if self.evidence is not None and self.evidence.zone_id != self.zone_id:
            raise ValueError("evidence must belong to zone_id")
        if self.reason is ZoneHeatDemandInputReason.ELIGIBLE and self.evidence is None:
            raise ValueError("eligible zone demand requires evidence")
        if self.preserves_confirmed_heat and self.demand is not BuildingHeatDemandStatus.INDETERMINATE:
            raise ValueError("only indeterminate input may preserve confirmed heat")
        return self
