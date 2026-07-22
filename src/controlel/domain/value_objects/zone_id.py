from controlel.domain.value_objects.value_object import ValueObject


class ZoneId(ValueObject):
    """Stable domain identifier of a zone."""

    value: str
