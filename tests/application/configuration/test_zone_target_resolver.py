from datetime import timedelta

import pytest

from controlel.application.configuration.zone_target_resolver import (
    SensorConfigurationNotFoundError,
    ZoneConfigurationNotFoundError,
    ZoneTargetResolver,
)
from controlel.domain.entities.zone import Zone
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId


def add_zone(
    repository: ZoneRepository,
    zone_id: str,
    target: float,
    primary_sensor_id: str | None = None,
) -> Zone:
    zone = Zone(
        zone_id=ZoneId(value=zone_id),
        primary_sensor_id=SensorId(value=primary_sensor_id or f"{zone_id}_temperature"),
        primary_measurement_max_age=timedelta(minutes=5),
        name=zone_id,
        target_temperature=Temperature(target),
    )
    repository.add(zone)
    return zone


def add_sensor(
    repository: SensorRepository,
    sensor_id: str,
    zone_id: str,
    name: str = "Unrelated display name",
) -> None:
    repository.add(
        Sensor(
            sensor_id=SensorId(value=sensor_id),
            zone_id=ZoneId(value=zone_id),
            name=name,
        )
    )


def create_resolver(
    sensor_repository: SensorRepository,
    zone_repository: ZoneRepository,
) -> ZoneTargetResolver:
    return ZoneTargetResolver(
        sensor_repository=sensor_repository,
        zone_repository=zone_repository,
    )


def test_resolves_sensor_to_complete_configured_zone():
    sensors = SensorRepository()
    zones = ZoneRepository()
    add_sensor(sensors, "living_room_temperature", "living_room")
    configured_zone = add_zone(zones, "living_room", 22)

    resolved_zone = create_resolver(sensors, zones).resolve(SensorId(value="living_room_temperature"))

    assert resolved_zone is configured_zone


def test_two_sensors_in_one_zone_return_same_zone():
    sensors = SensorRepository()
    zones = ZoneRepository()
    add_sensor(sensors, "living_room_primary", "living_room")
    add_sensor(sensors, "living_room_secondary", "living_room")
    configured_zone = add_zone(
        zones,
        "living_room",
        22,
        primary_sensor_id="living_room_primary",
    )
    resolver = create_resolver(sensors, zones)

    assert resolver.resolve(SensorId(value="living_room_primary")) is configured_zone
    assert resolver.resolve(SensorId(value="living_room_secondary")) is configured_zone


def test_sensors_in_different_zones_return_their_configured_zones():
    sensors = SensorRepository()
    zones = ZoneRepository()
    add_sensor(sensors, "living_room_temperature", "living_room")
    add_sensor(sensors, "bedroom_temperature", "bedroom")
    living_room = add_zone(zones, "living_room", 22)
    bedroom = add_zone(zones, "bedroom", 18)
    resolver = create_resolver(sensors, zones)

    assert resolver.resolve(SensorId(value="living_room_temperature")) is living_room
    assert resolver.resolve(SensorId(value="bedroom_temperature")) is bedroom


def test_sensor_name_is_irrelevant_to_resolution():
    sensors = SensorRepository()
    zones = ZoneRepository()
    add_sensor(
        sensors,
        "living_room_temperature",
        "living_room",
        name="Not a zone identifier",
    )
    configured_zone = add_zone(zones, "living_room", 22)

    resolved_zone = create_resolver(sensors, zones).resolve(SensorId(value="living_room_temperature"))

    assert resolved_zone is configured_zone


def test_missing_sensor_raises_explicit_configuration_error_without_fallback():
    resolver = create_resolver(SensorRepository(), ZoneRepository())

    with pytest.raises(
        SensorConfigurationNotFoundError,
        match="Sensor configuration not found for 'missing_sensor'",
    ):
        resolver.resolve(SensorId(value="missing_sensor"))


def test_missing_zone_raises_explicit_configuration_error_without_fallback():
    sensors = SensorRepository()
    add_sensor(sensors, "living_room_temperature", "missing_zone")
    resolver = create_resolver(sensors, ZoneRepository())

    with pytest.raises(
        ZoneConfigurationNotFoundError,
        match="Zone configuration not found for 'missing_zone'",
    ):
        resolver.resolve(SensorId(value="living_room_temperature"))
