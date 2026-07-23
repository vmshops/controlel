from datetime import datetime

from controlel.application.state.zone_demand_store import ZoneDemandStore
from controlel.domain.demands.building_heat_demand import BuildingHeatDemand
from controlel.domain.repositories.zone_repository import ZoneRepository


class HeatDemandDeadlineCalculator:
    def __init__(
        self,
        demand_store: ZoneDemandStore,
        zone_repository: ZoneRepository,
    ) -> None:
        self.demand_store = demand_store
        self.zone_repository = zone_repository

    def next_eligibility_change_at(
        self,
        evaluation: BuildingHeatDemand,
    ) -> datetime | None:
        evaluated_at = evaluation.evaluated_at
        deadlines: list[datetime] = []

        for zone in self.zone_repository.list_all():
            demand = self.demand_store.get(zone.zone_id)
            if demand is None:
                continue

            if demand.observed_at > evaluated_at:
                deadlines.append(demand.observed_at)
                continue

            expiry_boundary = demand.observed_at + zone.primary_measurement_max_age
            first_expired_at = expiry_boundary + datetime.resolution
            if first_expired_at > evaluated_at:
                deadlines.append(first_expired_at)

        return min(deadlines) if deadlines else None
