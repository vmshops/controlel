from datetime import UTC, datetime

import pytest

from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.application.state.zone_temperature_aggregator import (
    PrimarySensorConfigurationNotFoundError,
    PrimarySensorZoneMismatchError,
    ZoneTemperatureAggregator,
)
from controlel.domain.entities.zone import Zone
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId

PRIMARY_SENSOR_ID = SensorId(value="living_room_primary")
ZONE_ID = ZoneId(value="living_room")
TIMESTAMP = datetime(2026, 1, 1, 12, tzinfo=UTC)


def create_zone() -> Zone:
    return Zone(
        zone_id=ZONE_ID,
        primary_sensor_id=PRIMARY_SENSOR_ID,
        name="Living room",
        target_temperature=Temperature(22),
    )


def add_sensor(
    repository: SensorRepository,
    sensor_id: SensorId,
    zone_id: ZoneId = ZONE_ID,
) -> Sensor:
    sensor = Sensor(
        sensor_id=sensor_id,
        zone_id=zone_id,
        name=sensor_id.value,
    )
    repository.add(sensor)
    return sensor


def create_aggregator(
    state_store: RuntimeStateStore,
    sensors: SensorRepository,
) -> ZoneTemperatureAggregator:
    return ZoneTemperatureAggregator(
        state_store=state_store,
        sensor_repository=sensors,
    )


def test_returns_none_when_primary_sensor_has_no_latest_measurement():
    state_store = RuntimeStateStore()
    sensors = SensorRepository()
    add_sensor(sensors, PRIMARY_SENSOR_ID)

    result = create_aggregator(state_store, sensors).get_effective(create_zone())

    assert result is None


def test_returns_exact_latest_primary_measurement_with_provenance_and_timestamp():
    state_store = RuntimeStateStore()
    sensors = SensorRepository()
    add_sensor(sensors, PRIMARY_SENSOR_ID)
    measurement = Measurement(
        sensor_id=PRIMARY_SENSOR_ID,
        value=Temperature(20),
        timestamp=TIMESTAMP,
    )
    state_store.record(measurement)

    result = create_aggregator(state_store, sensors).get_effective(create_zone())

    assert result is measurement
    assert result.sensor_id == PRIMARY_SENSOR_ID
    assert result.timestamp == TIMESTAMP


def test_secondary_measurement_does_not_become_effective():
    state_store = RuntimeStateStore()
    sensors = SensorRepository()
    secondary_sensor_id = SensorId(value="living_room_secondary")
    add_sensor(sensors, PRIMARY_SENSOR_ID)
    add_sensor(sensors, secondary_sensor_id)
    primary = Measurement(
        sensor_id=PRIMARY_SENSOR_ID,
        value=Temperature(20),
        timestamp=TIMESTAMP,
    )
    state_store.record(primary)
    state_store.record(
        Measurement(
            sensor_id=secondary_sensor_id,
            value=Temperature(30),
            timestamp=TIMESTAMP,
        )
    )

    result = create_aggregator(state_store, sensors).get_effective(create_zone())

    assert result is primary


def test_missing_primary_sensor_raises_explicit_error_with_typed_ids():
    aggregator = create_aggregator(RuntimeStateStore(), SensorRepository())

    with pytest.raises(
        PrimarySensorConfigurationNotFoundError,
        match="Primary sensor 'living_room_primary' for zone 'living_room'",
    ) as raised:
        aggregator.get_effective(create_zone())

    assert raised.value.sensor_id == PRIMARY_SENSOR_ID
    assert raised.value.zone_id == ZONE_ID


def test_primary_sensor_in_another_zone_raises_explicit_mismatch_error():
    sensors = SensorRepository()
    actual_zone_id = ZoneId(value="bedroom")
    add_sensor(sensors, PRIMARY_SENSOR_ID, actual_zone_id)
    aggregator = create_aggregator(RuntimeStateStore(), sensors)

    with pytest.raises(
        PrimarySensorZoneMismatchError,
        match=("Primary sensor 'living_room_primary' for zone 'living_room' belongs to zone 'bedroom'"),
    ) as raised:
        aggregator.get_effective(create_zone())

    assert raised.value.sensor_id == PRIMARY_SENSOR_ID
    assert raised.value.expected_zone_id == ZONE_ID
    assert raised.value.actual_zone_id == actual_zone_id


def test_get_effective_does_not_mutate_runtime_state():
    state_store = RuntimeStateStore()
    sensors = SensorRepository()
    add_sensor(sensors, PRIMARY_SENSOR_ID)
    measurement = Measurement(
        sensor_id=PRIMARY_SENSOR_ID,
        value=Temperature(20),
        timestamp=TIMESTAMP,
    )
    state_store.record(measurement)
    before = state_store.list_latest()

    create_aggregator(state_store, sensors).get_effective(create_zone())

    assert state_store.list_latest() == before
