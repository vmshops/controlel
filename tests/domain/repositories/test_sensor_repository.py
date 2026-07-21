import pytest

from controlel.domain.capabilities.capability import Capability
from controlel.domain.repositories.sensor_repository import (
    DuplicateSensorIdError,
    SensorRepository,
)
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId


def create_sensor(sensor_id: str, *capabilities: str) -> Sensor:
    return Sensor(
        sensor_id=SensorId(value=sensor_id),
        name=sensor_id,
        capabilities=[Capability(name=name) for name in capabilities],
    )


def test_sensor_can_be_registered():
    repository = SensorRepository()
    sensor = create_sensor("living_room_temperature")

    repository.add(sensor)

    assert repository.list_all() == [sensor]


def test_sensor_can_be_retrieved_by_sensor_id():
    repository = SensorRepository()
    sensor = create_sensor("living_room_temperature")

    repository.add(sensor)

    assert repository.get(SensorId(value="living_room_temperature")) == sensor


def test_duplicate_sensor_id_is_rejected():
    repository = SensorRepository()
    repository.add(create_sensor("living_room_temperature"))

    with pytest.raises(
        DuplicateSensorIdError,
        match="Sensor with id 'living_room_temperature' is already registered",
    ):
        repository.add(create_sensor("living_room_temperature"))


def test_all_sensors_can_be_listed():
    repository = SensorRepository()
    temperature_sensor = create_sensor("living_room_temperature", "temperature")
    humidity_sensor = create_sensor("living_room_humidity", "humidity")

    repository.add(temperature_sensor)
    repository.add(humidity_sensor)

    assert repository.list_all() == [temperature_sensor, humidity_sensor]


def test_sensors_can_be_filtered_by_capability_name():
    repository = SensorRepository()
    indoor_sensor = create_sensor(
        "living_room_climate",
        "temperature",
        "humidity",
    )
    outdoor_sensor = create_sensor("outdoor_temperature", "temperature")
    humidity_sensor = create_sensor("bathroom_humidity", "humidity")

    repository.add(indoor_sensor)
    repository.add(outdoor_sensor)
    repository.add(humidity_sensor)

    result = repository.find_by_capability("temperature")

    assert result == [indoor_sensor, outdoor_sensor]
