from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.sensor_id import SensorId


class DuplicateSensorIdError(ValueError):
    """Raised when a sensor with the same domain identifier is registered twice."""

    def __init__(self, sensor_id: SensorId):
        super().__init__(f"Sensor with id '{sensor_id.value}' is already registered")


class SensorRepository:
    def __init__(self):
        self._items: dict[SensorId, Sensor] = {}

    def add(self, sensor: Sensor) -> None:
        if sensor.sensor_id in self._items:
            raise DuplicateSensorIdError(sensor.sensor_id)

        self._items[sensor.sensor_id] = sensor

    def get(self, sensor_id: SensorId) -> Sensor:
        return self._items[sensor_id]

    def list_all(self) -> list[Sensor]:
        return list(self._items.values())

    def find_by_capability(self, capability_name: str) -> list[Sensor]:
        return [
            sensor
            for sensor in self._items.values()
            if any(capability.name == capability_name for capability in sensor.capabilities)
        ]
