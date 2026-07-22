from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.infrastructure.sensors.fake_temperature_sensor_provider import (
    FakeTemperatureSensorProvider,
)


def test_fake_temperature_sensor_provider_returns_measurement():
    sensor = Sensor(
        sensor_id=SensorId(value="living_room_sensor"),
        name="Living room temperature",
    )

    provider = FakeTemperatureSensorProvider(
        temperature=19,
    )

    measurement = provider.measure(sensor)

    assert measurement.value.value == 19
    assert measurement.sensor_id == SensorId(value="living_room_sensor")
