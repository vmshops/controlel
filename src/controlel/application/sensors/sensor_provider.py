from abc import ABC, abstractmethod

from controlel.domain.measurements.measurement import Measurement
from controlel.domain.sensors.sensor import Sensor


class SensorProvider(ABC):
    """
    Provides measurements from sensors.
    """

    @abstractmethod
    def measure(self, sensor: Sensor) -> Measurement:
        """
        Read measurement from sensor.
        """
        raise NotImplementedError
