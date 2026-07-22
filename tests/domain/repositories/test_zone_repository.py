from datetime import timedelta

import pytest

from controlel.domain.entities.zone import Zone
from controlel.domain.repositories.zone_repository import (
    DuplicateZoneIdError,
    ZoneRepository,
)
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId


def create_zone(zone_id: str, target: float = 22) -> Zone:
    return Zone(
        zone_id=ZoneId(value=zone_id),
        primary_sensor_id=SensorId(value=f"{zone_id}_temperature"),
        primary_measurement_max_age=timedelta(minutes=5),
        name=zone_id,
        target_temperature=Temperature(target),
    )


def test_zone_can_be_added_and_retrieved_by_zone_id():
    repository = ZoneRepository()
    zone = create_zone("living_room")

    repository.add(zone)

    assert repository.get(ZoneId(value="living_room")) == zone


def test_duplicate_zone_id_is_rejected():
    repository = ZoneRepository()
    repository.add(create_zone("living_room"))

    with pytest.raises(
        DuplicateZoneIdError,
        match="Zone with id 'living_room' is already registered",
    ):
        repository.add(create_zone("living_room"))


def test_listing_preserves_insertion_order():
    repository = ZoneRepository()
    living_room = create_zone("living_room")
    bedroom = create_zone("bedroom")
    repository.add(living_room)
    repository.add(bedroom)

    assert repository.list_all() == [living_room, bedroom]


def test_list_all_returns_a_snapshot():
    repository = ZoneRepository()
    zone = create_zone("living_room")
    repository.add(zone)

    snapshot = repository.list_all()
    snapshot.clear()

    assert repository.list_all() == [zone]
