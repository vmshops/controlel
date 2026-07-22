from datetime import UTC, datetime, timedelta

from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature

BASE_TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


def create_measurement(
    sensor_id: str,
    value: float,
    timestamp: datetime = BASE_TIMESTAMP,
) -> Measurement:
    return Measurement(
        sensor_id=SensorId(value=sensor_id),
        value=Temperature(value),
        timestamp=timestamp,
    )


def test_empty_lookup_returns_none():
    store = RuntimeStateStore()

    assert store.get_latest(SensorId(value="unknown")) is None


def test_recording_returns_true_and_supports_lookup_by_sensor_id():
    store = RuntimeStateStore()
    measurement = create_measurement("living_room_temperature", 20)

    stored = store.record(measurement)

    assert stored is True
    assert store.get_latest(measurement.sensor_id) == measurement


def test_multiple_sensors_have_independent_state():
    store = RuntimeStateStore()
    living_room = create_measurement("living_room_temperature", 20)
    bedroom = create_measurement("bedroom_temperature", 18)

    store.record(living_room)
    store.record(bedroom)

    assert store.get_latest(living_room.sensor_id) == living_room
    assert store.get_latest(bedroom.sensor_id) == bedroom


def test_newer_measurement_replaces_current_measurement():
    store = RuntimeStateStore()
    current = create_measurement("living_room_temperature", 20)
    newer = create_measurement(
        "living_room_temperature",
        21,
        BASE_TIMESTAMP + timedelta(seconds=1),
    )
    store.record(current)

    assert store.record(newer) is True
    assert store.get_latest(newer.sensor_id) == newer


def test_equal_timestamp_measurement_replaces_by_arrival_order():
    store = RuntimeStateStore()
    first = create_measurement("living_room_temperature", 20)
    second = create_measurement("living_room_temperature", 21)
    store.record(first)

    assert store.record(second) is True
    assert store.get_latest(second.sensor_id) == second


def test_older_measurement_is_rejected_and_returns_false():
    store = RuntimeStateStore()
    current = create_measurement("living_room_temperature", 20)
    older = create_measurement(
        "living_room_temperature",
        19,
        BASE_TIMESTAMP - timedelta(seconds=1),
    )
    store.record(current)

    assert store.record(older) is False
    assert store.get_latest(current.sensor_id) == current


def test_store_keeps_one_latest_measurement_per_sensor():
    store = RuntimeStateStore()
    first = create_measurement("living_room_temperature", 20)
    second = create_measurement(
        "living_room_temperature",
        21,
        BASE_TIMESTAMP + timedelta(seconds=1),
    )

    store.record(first)
    store.record(second)

    assert store.list_latest() == [second]


def test_list_latest_returns_a_snapshot():
    store = RuntimeStateStore()
    measurement = create_measurement("living_room_temperature", 20)
    store.record(measurement)

    snapshot = store.list_latest()
    snapshot.clear()

    assert store.list_latest() == [measurement]


def test_first_sensor_registration_order_is_preserved_after_replacement():
    store = RuntimeStateStore()
    living_room = create_measurement("living_room_temperature", 20)
    bedroom = create_measurement("bedroom_temperature", 18)
    living_room_newer = create_measurement(
        "living_room_temperature",
        21,
        BASE_TIMESTAMP + timedelta(seconds=1),
    )

    store.record(living_room)
    store.record(bedroom)
    store.record(living_room_newer)

    assert store.list_latest() == [living_room_newer, bedroom]
