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

    name: str

    target_temperature: Temperature
