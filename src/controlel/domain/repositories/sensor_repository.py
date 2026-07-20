from uuid import UUID

from controlel.domain.sensors.sensor import Sensor


class SensorRepository:
    def __init__(self):
        self._items: dict[UUID, Sensor] = {}

    def add(self, sensor: Sensor):
        self._items[sensor.id] = sensor

    def get(self, sensor_id: UUID):
        return self._items[sensor_id]
