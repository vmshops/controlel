from pydantic import Field

from controlel.domain.entities.entity import Entity


class Zone(Entity):
    """
    Heating zone entity.

    Represents a physical area controlled by Controlel.
    """

    target_temperature: float = Field(default=21.0)
    current_temperature: float | None = Field(default=None)
    heating_active: bool = Field(default=False)
