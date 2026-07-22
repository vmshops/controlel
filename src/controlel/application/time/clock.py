from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Provides the current timezone-aware application time."""

    def now(self) -> datetime: ...
