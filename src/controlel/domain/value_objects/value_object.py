from pydantic import BaseModel, ConfigDict


class ValueObject[T](BaseModel):
    """
    Base class for immutable value objects.
    """

    value: T

    model_config = ConfigDict(
        frozen=True,
    )

    def __init__(self, value: T):
        super().__init__(value=value)
