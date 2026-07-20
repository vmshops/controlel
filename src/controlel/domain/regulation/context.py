from pydantic import BaseModel, ConfigDict

from controlel.domain.value_objects.temperature import Temperature


class ControlContext(BaseModel):
    """
    Represents current state and target values for regulation.
    """

    current_temperature: Temperature

    target_temperature: Temperature

    hysteresis: Temperature = Temperature(0)

    model_config = ConfigDict(
        frozen=True,
    )
