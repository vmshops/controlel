from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)


class HeatDemandSafetyState(BaseModel):
    indeterminate_since: datetime | None = None
    last_determinate_status: BuildingHeatDemandStatus | None = None
    last_evaluated_at: datetime

    model_config = ConfigDict(frozen=True)

    @field_validator("indeterminate_since", "last_evaluated_at")
    @classmethod
    def timestamps_must_be_timezone_aware(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")
        return value

    @field_validator("last_determinate_status")
    @classmethod
    def last_determinate_status_must_be_determinate(
        cls,
        value: BuildingHeatDemandStatus | None,
    ) -> BuildingHeatDemandStatus | None:
        if value is BuildingHeatDemandStatus.INDETERMINATE:
            raise ValueError("last_determinate_status must be determinate or None")
        return value

    @model_validator(mode="after")
    def indeterminate_period_must_not_start_after_evaluation(
        self,
    ) -> "HeatDemandSafetyState":
        if self.indeterminate_since is not None and self.indeterminate_since > self.last_evaluated_at:
            raise ValueError("indeterminate_since must not be later than last_evaluated_at")
        return self
