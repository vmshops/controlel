from controlel.application.state.runtime_state_store import RuntimeStateStore
from controlel.domain.entities.zone import Zone
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId


class PrimarySensorConfigurationNotFoundError(LookupError):
    """Raised when a zone's configured primary sensor is not registered."""

    def __init__(self, sensor_id: SensorId, zone_id: ZoneId):
        self.sensor_id = sensor_id
        self.zone_id = zone_id
        super().__init__(f"Primary sensor '{sensor_id.value}' for zone '{zone_id.value}' is not configured")


class PrimarySensorZoneMismatchError(ValueError):
    """Raised when a zone's primary sensor belongs to a different zone."""

    def __init__(
        self,
        sensor_id: SensorId,
        expected_zone_id: ZoneId,
        actual_zone_id: ZoneId,
    ):
        self.sensor_id = sensor_id
        self.expected_zone_id = expected_zone_id
        self.actual_zone_id = actual_zone_id
        super().__init__(
            f"Primary sensor '{sensor_id.value}' for zone "
            f"'{expected_zone_id.value}' belongs to zone '{actual_zone_id.value}'"
        )


class ZoneTemperatureAggregator:
    def __init__(
        self,
        state_store: RuntimeStateStore,
        sensor_repository: SensorRepository,
    ):
        self.state_store = state_store
        self.sensor_repository = sensor_repository

    def get_effective(self, zone: Zone) -> Measurement | None:
        try:
            primary_sensor = self.sensor_repository.get(zone.primary_sensor_id)
        except KeyError as error:
            raise PrimarySensorConfigurationNotFoundError(
                zone.primary_sensor_id,
                zone.zone_id,
            ) from error

        if primary_sensor.zone_id != zone.zone_id:
            raise PrimarySensorZoneMismatchError(
                sensor_id=zone.primary_sensor_id,
                expected_zone_id=zone.zone_id,
                actual_zone_id=primary_sensor.zone_id,
            )

        return self.state_store.get_latest(zone.primary_sensor_id)
