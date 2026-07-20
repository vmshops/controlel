from controlel.application.services.sensor_reading_service import (
    SensorReadingService,
)
from controlel.domain.sensors.sensor import Sensor
from controlel.infrastructure.sensors.fake_temperature_sensor_provider import (
    FakeTemperatureSensorProvider,
)


def test_sensor_reading_creates_temperature_event():
    sensor = Sensor(
        name="living_room",
    )

    service = SensorReadingService(
        FakeTemperatureSensorProvider(19),
    )

    event = service.read_temperature(sensor)

    assert event.measurement.value.value == 19
    assert event.measurement.source == "living_room"
