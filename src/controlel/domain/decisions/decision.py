from pydantic import BaseModel, ConfigDict


class Decision(BaseModel):
    """
    Represents a result of a regulation evaluation.
    """

    action: str

    model_config = ConfigDict(
        frozen=True,
    )
