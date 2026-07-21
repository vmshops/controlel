from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId


def test_repository_returns_sensor():
    repo = SensorRepository()

    sensor = Sensor(
        sensor_id=SensorId(value="living_room"),
        name="Living room",
    )

    repo.add(sensor)

    loaded = repo.get(sensor.id)

    assert loaded == sensor
