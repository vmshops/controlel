from datetime import UTC, datetime, timedelta

from controlel.application.services.heat_demand_deadline_calculator import (
    HeatDemandDeadlineCalculator,
)
from controlel.application.state.zone_demand_store import ZoneDemandStore
from controlel.domain.demands.building_heat_demand import BuildingHeatDemand
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.entities.zone import Zone
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
MAX_AGE = timedelta(minutes=5)


def zone(name: str, max_age: timedelta = MAX_AGE) -> Zone:
    return Zone(
        zone_id=ZoneId(value=name),
        primary_sensor_id=SensorId(value=f"{name}_temperature"),
        primary_measurement_max_age=max_age,
        name=name,
        target_temperature=Temperature(22),
    )


def demand(configured_zone: Zone, observed_at: datetime) -> ZoneDemand:
    return ZoneDemand(
        zone_id=configured_zone.zone_id,
        requires_heat=False,
        source_sensor_id=configured_zone.primary_sensor_id,
        observed_at=observed_at,
    )


def evaluation(evaluated_at: datetime = NOW) -> BuildingHeatDemand:
    return BuildingHeatDemand(
        status=BuildingHeatDemandStatus.INDETERMINATE,
        evaluated_at=evaluated_at,
        eligible_demands=(),
        missing_zone_ids=(),
        expired_zone_ids=(),
        future_dated_zone_ids=(),
    )


def calculator(
    zones: list[Zone],
    demands: list[ZoneDemand],
) -> HeatDemandDeadlineCalculator:
    repository = ZoneRepository()
    store = ZoneDemandStore()
    for configured_zone in zones:
        repository.add(configured_zone)
    for current_demand in demands:
        store.record(current_demand)
    return HeatDemandDeadlineCalculator(store, repository)


def test_exact_expiry_boundary_schedules_first_expired_microsecond():
    configured_zone = zone("living_room")
    observed_at = NOW - MAX_AGE

    deadline = calculator(
        [configured_zone],
        [demand(configured_zone, observed_at)],
    ).next_eligibility_change_at(evaluation())

    assert deadline == NOW + datetime.resolution
    assert deadline > NOW


def test_earliest_of_multiple_expiries_is_returned():
    first = zone("first")
    second = zone("second")
    result = calculator(
        [first, second],
        [
            demand(first, NOW - timedelta(minutes=1)),
            demand(second, NOW),
        ],
    ).next_eligibility_change_at(evaluation())

    assert result == NOW + timedelta(minutes=4) + datetime.resolution


def test_future_activation_is_exact_and_competes_with_expiry():
    expiring = zone("expiring")
    future = zone("future")
    activation = NOW + timedelta(seconds=10)
    result = calculator(
        [expiring, future],
        [
            demand(expiring, NOW - MAX_AGE + timedelta(seconds=20)),
            demand(future, activation),
        ],
    ).next_eligibility_change_at(evaluation())

    assert result == activation


def test_missing_and_expired_demands_have_no_time_only_deadline():
    missing = zone("missing")
    expired = zone("expired")
    result = calculator(
        [missing, expired],
        [demand(expired, NOW - MAX_AGE - datetime.resolution)],
    ).next_eligibility_change_at(evaluation())

    assert result is None
