from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.state.heat_demand_aggregator import (
    HeatDemandAggregator,
    ZoneDemandPrimarySensorMismatchError,
)
from controlel.application.state.zone_demand_store import ZoneDemandStore
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


class CountingClock:
    def __init__(self, current_time: datetime = NOW):
        self.current_time = current_time
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.current_time


def create_zone(name: str, *, enabled: bool = True) -> Zone:
    return Zone(
        zone_id=ZoneId(value=name),
        primary_sensor_id=SensorId(value=f"{name}_temperature"),
        primary_measurement_max_age=MAX_AGE,
        name=name,
        target_temperature=Temperature(22),
        enabled=enabled,
    )


def create_demand(
    zone: Zone,
    requires_heat: bool,
    observed_at: datetime = NOW,
    sensor_id: SensorId | None = None,
) -> ZoneDemand:
    return ZoneDemand(
        zone_id=zone.zone_id,
        requires_heat=requires_heat,
        source_sensor_id=sensor_id or zone.primary_sensor_id,
        observed_at=observed_at,
    )


def create_aggregator(
    zones: list[Zone],
    demands: list[ZoneDemand],
    clock: CountingClock | None = None,
) -> tuple[HeatDemandAggregator, ZoneDemandStore, CountingClock]:
    repository = ZoneRepository()
    for zone in zones:
        repository.add(zone)
    store = ZoneDemandStore()
    for demand in demands:
        store.record(demand)
    configured_clock = clock or CountingClock()
    return (
        HeatDemandAggregator(store, repository, configured_clock),
        store,
        configured_clock,
    )


def test_no_zones_and_no_demands_are_indeterminate_and_clock_is_read_once():
    aggregator, _, clock = create_aggregator([], [])

    result = aggregator.evaluate()

    assert result.status is BuildingHeatDemandStatus.INDETERMINATE
    assert result.evaluated_at is NOW
    assert clock.calls == 1


def test_no_demands_and_disabled_zone_are_still_missing_participants():
    living_room = create_zone("living_room", enabled=False)
    bedroom = create_zone("bedroom")
    aggregator, _, _ = create_aggregator([living_room, bedroom], [])

    result = aggregator.evaluate()

    assert result.status is BuildingHeatDemandStatus.INDETERMINATE
    assert result.missing_zone_ids == (bedroom.zone_id, living_room.zone_id)


def test_eligible_true_overrides_missing_expired_future_and_false_demands():
    true_zone = create_zone("true_zone")
    missing_zone = create_zone("missing_zone")
    expired_zone = create_zone("expired_zone")
    future_zone = create_zone("future_zone")
    false_zone = create_zone("false_zone")
    demands = [
        create_demand(true_zone, True),
        create_demand(expired_zone, False, NOW - MAX_AGE - timedelta(microseconds=1)),
        create_demand(future_zone, False, NOW + timedelta(microseconds=1)),
        create_demand(false_zone, False),
    ]
    aggregator, _, _ = create_aggregator(
        [true_zone, missing_zone, expired_zone, future_zone, false_zone],
        demands,
    )

    result = aggregator.evaluate()

    assert result.status is BuildingHeatDemandStatus.HEAT_REQUIRED
    assert result.eligible_demands == (demands[3], demands[0])
    assert result.missing_zone_ids == (missing_zone.zone_id,)
    assert result.expired_zone_ids == (expired_zone.zone_id,)
    assert result.future_dated_zone_ids == (future_zone.zone_id,)


def test_all_eligible_false_is_no_heat_required():
    living_room = create_zone("living_room")
    bedroom = create_zone("bedroom")
    demands = [create_demand(living_room, False), create_demand(bedroom, False)]
    aggregator, _, _ = create_aggregator([living_room, bedroom], demands)

    result = aggregator.evaluate()

    assert result.status is BuildingHeatDemandStatus.NO_HEAT_REQUIRED
    assert result.eligible_demands == (demands[1], demands[0])


@pytest.mark.parametrize("requires_heat", [True, False])
def test_expired_demand_plus_fresh_false_uses_valid_no_heat(requires_heat):
    old_zone = create_zone("old_zone")
    fresh_zone = create_zone("fresh_zone")
    aggregator, _, _ = create_aggregator(
        [old_zone, fresh_zone],
        [
            create_demand(old_zone, requires_heat, NOW - MAX_AGE - timedelta(microseconds=1)),
            create_demand(fresh_zone, False),
        ],
    )

    assert aggregator.evaluate().status is BuildingHeatDemandStatus.NO_HEAT_REQUIRED


@pytest.mark.parametrize(
    ("observed_at", "expected_status", "evidence_field"),
    [
        (NOW - MAX_AGE, BuildingHeatDemandStatus.NO_HEAT_REQUIRED, "eligible_demands"),
        (
            NOW - MAX_AGE - timedelta(microseconds=1),
            BuildingHeatDemandStatus.INDETERMINATE,
            "expired_zone_ids",
        ),
        (NOW, BuildingHeatDemandStatus.NO_HEAT_REQUIRED, "eligible_demands"),
        (
            NOW + timedelta(microseconds=1),
            BuildingHeatDemandStatus.INDETERMINATE,
            "future_dated_zone_ids",
        ),
    ],
)
def test_freshness_boundaries(observed_at, expected_status, evidence_field):
    zone = create_zone("living_room")
    demand = create_demand(zone, False, observed_at)
    aggregator, _, _ = create_aggregator([zone], [demand])

    result = aggregator.evaluate()

    assert result.status is expected_status
    assert getattr(result, evidence_field)


def test_source_mismatch_raises_with_all_typed_identifiers():
    zone = create_zone("living_room")
    actual = SensorId(value="other_sensor")
    aggregator, _, _ = create_aggregator(
        [zone],
        [create_demand(zone, True, sensor_id=actual)],
    )

    with pytest.raises(
        ZoneDemandPrimarySensorMismatchError,
        match="living_room.*living_room_temperature.*other_sensor",
    ) as raised:
        aggregator.evaluate()

    assert raised.value.zone_id is zone.zone_id
    assert raised.value.expected_sensor_id is zone.primary_sensor_id
    assert raised.value.actual_sensor_id is actual


def test_naive_clock_is_rejected_without_mutating_stored_demand():
    zone = create_zone("living_room")
    demand = create_demand(zone, True)
    aggregator, store, _ = create_aggregator(
        [zone],
        [demand],
        CountingClock(datetime(2026, 1, 1, 12)),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        aggregator.evaluate()

    assert store.get(zone.zone_id) is demand


def test_expired_demand_remains_stored_after_evaluation():
    zone = create_zone("living_room")
    demand = create_demand(zone, True, NOW - MAX_AGE - timedelta(seconds=1))
    aggregator, store, _ = create_aggregator([zone], [demand])

    result = aggregator.evaluate()

    assert result.status is BuildingHeatDemandStatus.INDETERMINATE
    assert store.get(zone.zone_id) is demand
