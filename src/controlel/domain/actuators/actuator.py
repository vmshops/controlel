from controlel.domain.entities.entity import Entity


class Actuator(Entity):
    """
    Represents something that can change system state.
    """

    name: str
    enabled: bool = True
