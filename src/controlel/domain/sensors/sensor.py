from pydantic import Field

from controlel.domain.capabilities.capability import Capability
from controlel.domain.entities.entity import Entity


class Sensor(Entity):
    """
    Represents a physical or virtual sensor.
    """

    capabilities: list[Capability] = Field(default_factory=list)
