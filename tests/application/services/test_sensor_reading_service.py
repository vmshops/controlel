from controlel.application.services.sensor_reading_service import (
    SensorReadingService,
)
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.infrastructure.sensors.fake_temperature_sensor_provider import (
    FakeTemperatureSensorProvider,
)


def test_sensor_reading_creates_temperature_event():
    sensor = Sensor(
        sensor_id=SensorId(value="living_room"),
        name="living_room",
    )

    service = SensorReadingService(
        FakeTemperatureSensorProvider(19),
    )

    event = service.read_temperature(sensor)

    assert event.measurement.value.value == 19
    assert event.measurement.sensor_id == SensorId(value="living_room")
