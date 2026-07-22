from pydantic import BaseModel, ConfigDict

from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId


class ControlContext(BaseModel):
    """
    Represents current state and target values for regulation.
    """

    sensor_id: SensorId

    zone_id: ZoneId

    current_temperature: Temperature

    target_temperature: Temperature

    hysteresis: Temperature = Temperature(0)

    model_config = ConfigDict(
        frozen=True,
    )
