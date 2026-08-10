from controlel.application.services.demand_arbitrator import MultiZoneDemandArbitrator
from controlel.application.state.zone_demand_store import ZoneDemandStore
from controlel.application.time.clock import Clock
from controlel.domain.demands.building_heat_demand import BuildingHeatDemand
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.demands.zone_heat_demand_input import (
    ZoneHeatDemandInput,
    ZoneHeatDemandInputReason,
)
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


class ZoneDemandPrimarySensorMismatchError(ValueError):
    def __init__(
        self,
        zone_id: ZoneId,
        expected_sensor_id: SensorId,
        actual_sensor_id: SensorId,
    ) -> None:
        self.zone_id = zone_id
        self.expected_sensor_id = expected_sensor_id
        self.actual_sensor_id = actual_sensor_id
        super().__init__(
            f"Zone '{zone_id.value}' expects primary sensor "
            f"'{expected_sensor_id.value}', but demand came from "
            f"'{actual_sensor_id.value}'"
        )


class HeatDemandAggregator:
    def __init__(
        self,
        demand_store: ZoneDemandStore,
        zone_repository: ZoneRepository,
        clock: Clock,
    ) -> None:
        self.demand_store = demand_store
        self.zone_repository = zone_repository
        self.clock = clock
        self._arbitrator = MultiZoneDemandArbitrator()

    def evaluate(self) -> BuildingHeatDemand:
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Clock.now() must return a timezone-aware datetime")

        zones = sorted(self.zone_repository.list_all(), key=lambda zone: zone.zone_id.value)
        eligible_demands: list[ZoneDemand] = []
        zone_inputs: list[ZoneHeatDemandInput] = []
        missing_zone_ids: list[ZoneId] = []
        expired_zone_ids: list[ZoneId] = []
        future_dated_zone_ids: list[ZoneId] = []

        for zone in zones:
            demand = self.demand_store.get(zone.zone_id)
            if demand is None:
                missing_zone_ids.append(zone.zone_id)
                zone_inputs.append(
                    ZoneHeatDemandInput(
                        zone_id=zone.zone_id,
                        demand=BuildingHeatDemandStatus.INDETERMINATE,
                        reason=ZoneHeatDemandInputReason.MISSING,
                    )
                )
                continue

            if demand.source_sensor_id != zone.primary_sensor_id:
                raise ZoneDemandPrimarySensorMismatchError(
                    zone_id=zone.zone_id,
                    expected_sensor_id=zone.primary_sensor_id,
                    actual_sensor_id=demand.source_sensor_id,
                )

            cutoff = now - zone.primary_measurement_max_age
            if demand.observed_at < cutoff:
                expired_zone_ids.append(zone.zone_id)
                zone_inputs.append(
                    ZoneHeatDemandInput(
                        zone_id=zone.zone_id,
                        demand=BuildingHeatDemandStatus.INDETERMINATE,
                        reason=ZoneHeatDemandInputReason.EXPIRED,
                        evidence=demand,
                    )
                )
            elif demand.observed_at > now:
                future_dated_zone_ids.append(zone.zone_id)
                zone_inputs.append(
                    ZoneHeatDemandInput(
                        zone_id=zone.zone_id,
                        demand=BuildingHeatDemandStatus.INDETERMINATE,
                        reason=ZoneHeatDemandInputReason.FUTURE_DATED,
                        evidence=demand,
                    )
                )
            else:
                eligible_demands.append(demand)
                zone_inputs.append(
                    ZoneHeatDemandInput(
                        zone_id=zone.zone_id,
                        demand=(
                            BuildingHeatDemandStatus.HEAT_REQUIRED
                            if demand.requires_heat
                            else BuildingHeatDemandStatus.NO_HEAT_REQUIRED
                        ),
                        reason=ZoneHeatDemandInputReason.ELIGIBLE,
                        evidence=demand,
                    )
                )

        initial = BuildingHeatDemand(
            status=BuildingHeatDemandStatus.INDETERMINATE,
            evaluated_at=now,
            eligible_demands=tuple(eligible_demands),
            missing_zone_ids=tuple(missing_zone_ids),
            expired_zone_ids=tuple(expired_zone_ids),
            future_dated_zone_ids=tuple(future_dated_zone_ids),
            zone_inputs=tuple(zone_inputs),
            zone_count=len(zone_inputs),
        )
        return self._arbitrator.resolve(initial)
