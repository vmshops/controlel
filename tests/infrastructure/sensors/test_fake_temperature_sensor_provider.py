from controlel.domain.sensors.sensor import Sensor
from controlel.infrastructure.sensors.fake_temperature_sensor_provider import (
    FakeTemperatureSensorProvider,
)


def test_fake_temperature_sensor_provider_returns_measurement():
    sensor = Sensor(
        name="living_room_sensor",
    )

    provider = FakeTemperatureSensorProvider(
        temperature=19,
    )

    measurement = provider.measure(sensor)

    assert measurement.value.value == 19
    assert measurement.source == "living_room_sensor"
