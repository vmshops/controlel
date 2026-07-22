from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


def test_sensor_has_identity():
    sensor = Sensor(
        sensor_id=SensorId(value="living_room_temperature"),
        zone_id=ZoneId(value="living_room"),
        name="Living Room Temperature",
    )

    assert sensor.sensor_id.value == "living_room_temperature"
    assert sensor.name == "Living Room Temperature"
