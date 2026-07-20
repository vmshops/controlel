from controlel.application.sensors.sensor_provider import SensorProvider
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.value_objects.temperature import Temperature


class FakeTemperatureSensorProvider(SensorProvider):
    """
    Fake temperature sensor for testing and simulation.
    """

    def __init__(self, temperature: float = 20):
        self.temperature = temperature

    def measure(self, sensor: Sensor) -> Measurement:
        return Measurement(
            value=Temperature(self.temperature),
            source=sensor.name,
        )
