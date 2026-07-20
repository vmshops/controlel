from controlel.application.sensors.sensor_provider import SensorProvider
from controlel.domain.events.temperature_measured_event import (
    TemperatureMeasuredEvent,
)
from controlel.domain.sensors.sensor import Sensor


class SensorReadingService:
    """
    Reads sensors and creates events.
    """

    def __init__(self, provider: SensorProvider):
        self.provider = provider

    def read_temperature(self, sensor: Sensor):
        measurement = self.provider.measure(sensor)

        return TemperatureMeasuredEvent(
            measurement=measurement,
        )
