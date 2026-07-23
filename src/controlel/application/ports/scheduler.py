from collections.abc import Callable
from datetime import datetime
from typing import Protocol


class ScheduledTaskHandle(Protocol):
    def cancel(self) -> None: ...


class Scheduler(Protocol):
    """Schedules one-shot callbacks at timezone-aware application times.

    Implementations must not invoke a callback before its requested datetime.
    """

    def schedule_at(
        self,
        when: datetime,
        callback: Callable[[], None],
    ) -> ScheduledTaskHandle: ...
