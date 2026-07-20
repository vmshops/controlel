from datetime import UTC, datetime

from pydantic import BaseModel

from controlel.domain.value_objects.temperature import Temperature


class ControlState(BaseModel):
    """
    Represents current heating control state.
    """

    current_temperature: Temperature
    target_temperature: Temperature

    heating_enabled: bool = False

    updated_at: datetime = datetime.now(UTC)
