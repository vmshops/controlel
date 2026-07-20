from controlel.domain.capabilities.capability import Capability
from controlel.domain.sensors.sensor import Sensor


def test_sensor_with_capabilities():
    sensor = Sensor(
        name="Living room sensor",
        capabilities=[
            Capability(name="temperature"),
            Capability(name="humidity"),
        ],
    )

    assert len(sensor.capabilities) == 2
    assert sensor.capabilities[0].name == "temperature"
