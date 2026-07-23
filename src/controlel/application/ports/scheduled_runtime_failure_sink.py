from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ScheduledRuntimeFailure:
    scheduled_for: datetime
    error: Exception

    def __post_init__(self) -> None:
        if not isinstance(self.scheduled_for, datetime):
            raise TypeError("scheduled_for must be a datetime")
        if self.scheduled_for.tzinfo is None or self.scheduled_for.utcoffset() is None:
            raise ValueError("scheduled_for must be timezone-aware")
        if not isinstance(self.error, Exception):
            raise TypeError("error must be an Exception")


class ScheduledRuntimeFailureSink(Protocol):
    def report(
        self,
        failure: ScheduledRuntimeFailure,
    ) -> None: ...
