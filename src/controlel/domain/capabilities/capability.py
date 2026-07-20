from pydantic import BaseModel, ConfigDict


class Capability(BaseModel):
    """
    Represents a device capability.
    """

    name: str

    model_config = ConfigDict(
        frozen=True,
    )
