from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.sensor_id import SensorId


class RuntimeStateStore:
    """Stores the latest accepted measurement for each sensor."""

    def __init__(self) -> None:
        self._latest: dict[SensorId, Measurement] = {}

    def record(self, measurement: Measurement) -> bool:
        current = self._latest.get(measurement.sensor_id)

        if current is not None and measurement.timestamp < current.timestamp:
            return False

        self._latest[measurement.sensor_id] = measurement
        return True

    def get_latest(self, sensor_id: SensorId) -> Measurement | None:
        return self._latest.get(sensor_id)

    def list_latest(self) -> list[Measurement]:
        return list(self._latest.values())
