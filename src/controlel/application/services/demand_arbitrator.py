from typing import Protocol

from controlel.domain.demands.building_heat_demand import BuildingHeatDemand


class DemandArbitrator(Protocol):
    """Resolve aggregate zone demand for one shared heat source."""

    def resolve(
        self,
        aggregate_demand: BuildingHeatDemand,
    ) -> BuildingHeatDemand: ...


class IdentityDemandArbitrator:
    """One-zone seam whose source demand is the existing aggregate demand."""

    def resolve(
        self,
        aggregate_demand: BuildingHeatDemand,
    ) -> BuildingHeatDemand:
        if not isinstance(aggregate_demand, BuildingHeatDemand):
            raise TypeError("aggregate_demand must be a BuildingHeatDemand")
        return aggregate_demand
