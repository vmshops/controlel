from controlel.domain.sensors.sensor import Sensor


def test_sensor_creation():
    sensor = Sensor(
        name="Living room temperature",
        sensor_type="temperature",
    )

    assert sensor.name == "Living room temperature"
    assert sensor.sensor_type == "temperature"
    assert sensor.enabled is True
