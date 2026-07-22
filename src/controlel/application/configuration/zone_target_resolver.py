from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId


class SensorConfigurationNotFoundError(LookupError):
    """Raised when a sensor has no registered configuration."""

    def __init__(self, sensor_id: SensorId):
        self.sensor_id = sensor_id
        super().__init__(f"Sensor configuration not found for '{sensor_id.value}'")


class ZoneConfigurationNotFoundError(LookupError):
    """Raised when a sensor's configured zone is not registered."""

    def __init__(self, zone_id: ZoneId):
        self.zone_id = zone_id
        super().__init__(f"Zone configuration not found for '{zone_id.value}'")


class ZoneTargetResolver:
    def __init__(
        self,
        sensor_repository: SensorRepository,
        zone_repository: ZoneRepository,
    ):
        self.sensor_repository = sensor_repository
        self.zone_repository = zone_repository

    def resolve(self, sensor_id: SensorId) -> Temperature:
        try:
            sensor = self.sensor_repository.get(sensor_id)
        except KeyError as error:
            raise SensorConfigurationNotFoundError(sensor_id) from error

        try:
            zone = self.zone_repository.get(sensor.zone_id)
        except KeyError as error:
            raise ZoneConfigurationNotFoundError(sensor.zone_id) from error

        return zone.target_temperature
