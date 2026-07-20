from controlel.domain.entities.entity import Entity


class Sensor(Entity):
    """
    Represents a physical or virtual sensor.
    """

    sensor_type: str
