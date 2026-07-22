from datetime import timedelta

from pydantic import field_validator

from controlel.domain.entities.entity import Entity
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId


class Zone(Entity):
    """
    Heating zone entity.

    Represents a physical area controlled by Controlel.
    """

    zone_id: ZoneId

    primary_sensor_id: SensorId

    primary_measurement_max_age: timedelta

    name: str

    target_temperature: Temperature

    @field_validator("primary_measurement_max_age", mode="before")
    @classmethod
    def primary_measurement_max_age_must_be_positive_timedelta(
        cls,
        value: object,
    ) -> timedelta:
        if not isinstance(value, timedelta):
            raise ValueError("primary_measurement_max_age must be a timedelta")
        if value <= timedelta(0):
            raise ValueError("primary_measurement_max_age must be greater than zero")
        return value
