from datetime import UTC, datetime, timedelta

from controlel.application.state.zone_demand_store import ZoneDemandStore
from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def create_demand(zone: str, requires_heat: bool, age: timedelta = timedelta()) -> ZoneDemand:
    return ZoneDemand(
        zone_id=ZoneId(value=zone),
        requires_heat=requires_heat,
        source_sensor_id=SensorId(value=f"{zone}_temperature"),
        observed_at=NOW - age,
    )


def test_empty_lookup_returns_none():
    assert ZoneDemandStore().get(ZoneId(value="living_room")) is None


def test_record_replaces_one_zone_without_reordering_or_affecting_another():
    store = ZoneDemandStore()
    living_true = create_demand("living_room", True)
    bedroom = create_demand("bedroom", False)
    living_false = create_demand("living_room", False)

    store.record(living_true)
    store.record(bedroom)
    store.record(living_false)

    assert store.get(living_true.zone_id) is living_false
    assert store.get(bedroom.zone_id) is bedroom
    assert store.list_current() == [living_false, bedroom]


def test_list_current_is_a_snapshot_and_expired_entries_are_retained():
    store = ZoneDemandStore()
    expired = create_demand("living_room", True, timedelta(days=1))
    store.record(expired)

    snapshot = store.list_current()
    snapshot.clear()

    assert store.list_current() == [expired]
