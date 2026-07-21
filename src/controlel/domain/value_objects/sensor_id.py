from controlel.domain.value_objects.value_object import ValueObject


class SensorId(ValueObject):
    """
    Unique identifier of a sensor.
    """

    value: str
