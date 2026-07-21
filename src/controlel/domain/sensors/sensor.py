from pydantic import Field

from controlel.domain.capabilities.capability import Capability
from controlel.domain.entities.entity import Entity
from controlel.domain.value_objects.sensor_id import SensorId


class Sensor(Entity):
    """
    Represents a physical or virtual sensor.
    """

    sensor_id: SensorId

    name: str

    capabilities: list[Capability] = Field(default_factory=list)
