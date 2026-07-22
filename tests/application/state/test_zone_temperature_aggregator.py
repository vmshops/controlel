from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.application.state.zone_temperature_aggregator import (
    PrimarySensorConfigurationNotFoundError,
    PrimarySensorZoneMismatchError,
    ZoneTemperatureAggregator,
    ZoneTemperatureResult,
    ZoneTemperatureStatus,
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
NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
MAX_AGE = timedelta(minutes=5)


class FixedClock:
    def __init__(self, current_time: datetime):
        self.current_time = current_time
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.current_time


def create_zone(maximum_age: timedelta = MAX_AGE) -> Zone:
    return Zone(
        zone_id=ZONE_ID,
        primary_sensor_id=PRIMARY_SENSOR_ID,
        primary_measurement_max_age=maximum_age,
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
    clock: FixedClock | None = None,
) -> ZoneTemperatureAggregator:
    return ZoneTemperatureAggregator(
        state_store=state_store,
        sensor_repository=sensors,
        clock=clock or FixedClock(NOW),
    )


def record_primary(
    state_store: RuntimeStateStore,
    timestamp: datetime = NOW,
) -> Measurement:
    measurement = Measurement(
        sensor_id=PRIMARY_SENSOR_ID,
        value=Temperature(20),
        timestamp=timestamp,
    )
    state_store.record(measurement)
    return measurement


def test_returns_none_when_primary_sensor_has_no_latest_measurement():
    state_store = RuntimeStateStore()
    sensors = SensorRepository()
    add_sensor(sensors, PRIMARY_SENSOR_ID)

    result = create_aggregator(state_store, sensors).get_effective(create_zone())

    assert result.status is ZoneTemperatureStatus.MISSING
    assert result.measurement is None


@pytest.mark.parametrize(
    "timestamp",
    [NOW - timedelta(minutes=1), NOW - MAX_AGE, NOW],
    ids=["fresh", "cutoff-boundary", "equal-to-now"],
)
def test_eligible_primary_returns_exact_stored_measurement(timestamp):
    state_store = RuntimeStateStore()
    sensors = SensorRepository()
    add_sensor(sensors, PRIMARY_SENSOR_ID)
    measurement = record_primary(state_store, timestamp)

    result = create_aggregator(state_store, sensors).get_effective(create_zone())

    assert result.status is ZoneTemperatureStatus.EFFECTIVE
    assert result.measurement is measurement


@pytest.mark.parametrize(
    ("timestamp", "expected_status"),
    [
        (
            NOW - MAX_AGE - timedelta(microseconds=1),
            ZoneTemperatureStatus.EXPIRED,
        ),
        (NOW + timedelta(microseconds=1), ZoneTemperatureStatus.FUTURE_DATED),
    ],
    ids=["expired", "future"],
)
def test_ineligible_primary_reports_reason_and_store_is_not_mutated(
    timestamp,
    expected_status,
):
    state_store = RuntimeStateStore()
    sensors = SensorRepository()
    add_sensor(sensors, PRIMARY_SENSOR_ID)
    measurement = record_primary(state_store, timestamp)
    before = state_store.list_latest()

    result = create_aggregator(state_store, sensors).get_effective(create_zone())

    assert result.status is expected_status
    assert result.measurement is None
    assert state_store.get_latest(PRIMARY_SENSOR_ID) is measurement
    assert state_store.list_latest() == before


def test_secondary_measurement_does_not_become_effective_or_affect_freshness():
    state_store = RuntimeStateStore()
    sensors = SensorRepository()
    secondary_sensor_id = SensorId(value="living_room_secondary")
    add_sensor(sensors, PRIMARY_SENSOR_ID)
    add_sensor(sensors, secondary_sensor_id)
    primary = record_primary(state_store, NOW - timedelta(minutes=1))
    state_store.record(
        Measurement(
            sensor_id=secondary_sensor_id,
            value=Temperature(30),
            timestamp=NOW + timedelta(days=1),
        )
    )

    result = create_aggregator(state_store, sensors).get_effective(create_zone())

    assert result.status is ZoneTemperatureStatus.EFFECTIVE
    assert result.measurement is primary


def test_zone_temperature_status_has_stable_string_values():
    assert {status.name: status.value for status in ZoneTemperatureStatus} == {
        "EFFECTIVE": "effective",
        "MISSING": "missing",
        "EXPIRED": "expired",
        "FUTURE_DATED": "future_dated",
    }
    assert all(isinstance(status, str) for status in ZoneTemperatureStatus)


def test_zone_temperature_result_is_immutable():
    result = ZoneTemperatureResult(
        status=ZoneTemperatureStatus.MISSING,
        measurement=None,
    )

    with pytest.raises(FrozenInstanceError):
        result.status = ZoneTemperatureStatus.EXPIRED


def test_effective_result_requires_measurement():
    with pytest.raises(ValueError, match="EFFECTIVE requires a measurement"):
        ZoneTemperatureResult(
            status=ZoneTemperatureStatus.EFFECTIVE,
            measurement=None,
        )


@pytest.mark.parametrize(
    "status",
    [
        ZoneTemperatureStatus.MISSING,
        ZoneTemperatureStatus.EXPIRED,
        ZoneTemperatureStatus.FUTURE_DATED,
    ],
)
def test_non_effective_result_rejects_measurement(status):
    with pytest.raises(ValueError, match="requires measurement to be None"):
        ZoneTemperatureResult(
            status=status,
            measurement=Measurement(
                sensor_id=PRIMARY_SENSOR_ID,
                value=Temperature(20),
                timestamp=NOW,
            ),
        )


def test_clock_is_read_exactly_once_for_measurement_evaluation():
    state_store = RuntimeStateStore()
    sensors = SensorRepository()
    add_sensor(sensors, PRIMARY_SENSOR_ID)
    record_primary(state_store)
    clock = FixedClock(NOW)

    create_aggregator(state_store, sensors, clock).get_effective(create_zone())

    assert clock.calls == 1


def test_naive_clock_time_raises_clear_value_error():
    state_store = RuntimeStateStore()
    sensors = SensorRepository()
    add_sensor(sensors, PRIMARY_SENSOR_ID)
    record_primary(state_store)
    aggregator = create_aggregator(
        state_store,
        sensors,
        FixedClock(datetime(2026, 1, 1, 12)),
    )

    with pytest.raises(
        ValueError,
        match=r"Clock\.now\(\) must return a timezone-aware datetime",
    ):
        aggregator.get_effective(create_zone())


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
