from collections.abc import Callable
from datetime import datetime
from typing import Protocol


class ScheduledTaskHandle(Protocol):
    """Best-effort cancellation handle for a one-shot scheduled task.

    An already queued callback may still arrive after cancellation.
    """

    def cancel(self) -> None: ...


class Scheduler(Protocol):
    """Schedules one-shot callbacks at aware absolute wall-clock times.

    Callbacks may be late but must not intentionally run early. Callback return
    values are ignored. A runtime-compatible implementation delivers callbacks
    through the same serialized host context as all other ControlRuntime calls.
    Cancellation remains best effort, so runtime generation checks are still
    mandatory.

    Scheduler does not report runtime evaluation failures. ControlRuntime
    reports them through ScheduledRuntimeFailureSink.
    """

    def schedule_at(
        self,
        when: datetime,
        callback: Callable[[], None],
    ) -> ScheduledTaskHandle: ...
