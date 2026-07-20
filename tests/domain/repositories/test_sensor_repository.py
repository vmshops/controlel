from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.temperature import Temperature


def test_repository_returns_sensor():
    repo = SensorRepository()

    sensor = Sensor(
        name="Living room",
        value=Temperature(21),
    )

    repo.add(sensor)

    loaded = repo.get(sensor.id)

    assert loaded == sensor
