from typing import Protocol

from controlel.domain.demands.building_heat_demand import BuildingHeatDemand, BuildingHeatDemandReason
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)


class DemandArbitrator(Protocol):
    """Resolve aggregate zone demand for one shared heat source."""

    def resolve(
        self,
        aggregate_demand: BuildingHeatDemand,
    ) -> BuildingHeatDemand: ...


class IdentityDemandArbitrator:
    """Frozen one-zone reference used by differential compatibility tests."""

    def resolve(
        self,
        aggregate_demand: BuildingHeatDemand,
    ) -> BuildingHeatDemand:
        if not isinstance(aggregate_demand, BuildingHeatDemand):
            raise TypeError("aggregate_demand must be a BuildingHeatDemand")
        return aggregate_demand


class MultiZoneDemandArbitrator:
    """Aggregate already-established zone demand states for one shared source."""

    def resolve(
        self,
        aggregate_demand: BuildingHeatDemand,
    ) -> BuildingHeatDemand:
        if not isinstance(aggregate_demand, BuildingHeatDemand):
            raise TypeError("aggregate_demand must be a BuildingHeatDemand")

        inputs = tuple(sorted(aggregate_demand.zone_inputs, key=lambda item: item.zone_id.value))
        heat_ids = tuple(item.zone_id for item in inputs if item.demand is BuildingHeatDemandStatus.HEAT_REQUIRED)
        no_heat_ids = tuple(item.zone_id for item in inputs if item.demand is BuildingHeatDemandStatus.NO_HEAT_REQUIRED)
        indeterminate_ids = tuple(
            item.zone_id for item in inputs if item.demand is BuildingHeatDemandStatus.INDETERMINATE
        )
        preserves_active_demand = any(item.preserves_confirmed_heat for item in inputs)

        if heat_ids:
            status = BuildingHeatDemandStatus.HEAT_REQUIRED
            reason = (
                BuildingHeatDemandReason.HEAT_REQUIRED_BY_ZONE
                if len(heat_ids) == 1
                else BuildingHeatDemandReason.HEAT_REQUIRED_BY_MULTIPLE_ZONES
            )
        elif preserves_active_demand:
            status = BuildingHeatDemandStatus.INDETERMINATE
            reason = BuildingHeatDemandReason.INDETERMINATE_ACTIVE_DEMAND_PRESERVED
        elif no_heat_ids:
            status = BuildingHeatDemandStatus.NO_HEAT_REQUIRED
            reason = BuildingHeatDemandReason.NO_ZONE_REQUIRES_HEAT
        elif indeterminate_ids:
            status = BuildingHeatDemandStatus.INDETERMINATE
            reason = BuildingHeatDemandReason.ALL_ZONES_INDETERMINATE
        else:
            status = BuildingHeatDemandStatus.INDETERMINATE
            reason = BuildingHeatDemandReason.NO_ZONES_CONFIGURED

        eligible_demands = tuple(
            item.evidence.model_copy(
                update={
                    "requires_heat": item.demand is BuildingHeatDemandStatus.HEAT_REQUIRED,
                }
            )
            for item in inputs
            if item.evidence is not None and item.demand is not BuildingHeatDemandStatus.INDETERMINATE
        )
        return BuildingHeatDemand(
            status=status,
            evaluated_at=aggregate_demand.evaluated_at,
            eligible_demands=eligible_demands,
            missing_zone_ids=aggregate_demand.missing_zone_ids,
            expired_zone_ids=aggregate_demand.expired_zone_ids,
            future_dated_zone_ids=aggregate_demand.future_dated_zone_ids,
            zone_inputs=inputs,
            contributing_heat_zone_ids=heat_ids,
            no_heat_zone_ids=no_heat_ids,
            indeterminate_zone_ids=indeterminate_ids,
            reason=reason,
            zone_count=len(inputs),
            heat_requesting_zone_count=len(heat_ids),
        )
