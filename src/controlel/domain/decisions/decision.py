from pydantic import BaseModel


class Decision(BaseModel):
    """
    Represents a regulation decision.
    """

    action: str

    reason: str | None = None
