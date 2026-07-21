from controlel.domain.capabilities.capability import Capability
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId


def test_sensor_with_capabilities():
    sensor = Sensor(
        sensor_id=SensorId(value="living_room_sensor"),
        name="Living room sensor",
        capabilities=[
            Capability(name="temperature"),
            Capability(name="humidity"),
        ],
    )

    assert len(sensor.capabilities) == 2
    assert sensor.capabilities[0].name == "temperature"
