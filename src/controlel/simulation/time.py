"""Virtual aware time and deterministic one-shot scheduling."""

from __future__ import annotations

import heapq
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from controlel.simulation.recorder import SimulationRecorder


class VirtualClock:
    """Monotonic, explicitly advanced application clock."""

    def __init__(self, start_at: datetime) -> None:
        self._now = _aware(start_at, "start_at")

    def now(self) -> datetime:
        return self._now

    def advance_to(self, when: datetime) -> None:
        when = _aware(when, "when")
        if when < self._now:
            raise ValueError("virtual time cannot move backwards")
        self._now = when


@dataclass(order=True, slots=True)
class _ScheduledItem:
    scheduled_for: datetime
    sequence: int
    callback: Callable[[], None] = field(compare=False)
    cancelled: bool = field(default=False, compare=False)


class _VirtualScheduledTaskHandle:
    def __init__(self, scheduler: DeterministicScheduler, item: _ScheduledItem) -> None:
        self._scheduler = scheduler
        self._item = item

    def cancel(self) -> None:
        self._scheduler.cancel(self._item)


class DeterministicScheduler:
    """Exact-delivery v0.1 scheduler ordered by deadline and insertion."""

    def __init__(self, clock: VirtualClock, recorder: SimulationRecorder | None = None) -> None:
        self._clock = clock
        self._recorder = recorder
        self._queue: list[_ScheduledItem] = []
        self._sequence = 0

    def schedule_at(
        self,
        when: datetime,
        callback: Callable[[], None],
    ) -> _VirtualScheduledTaskHandle:
        when = _aware(when, "when")
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._sequence += 1
        item = _ScheduledItem(when, self._sequence, callback)
        heapq.heappush(self._queue, item)
        if self._recorder is not None:
            self._recorder.record(
                "scheduler.scheduled",
                recorded_at=self._clock.now(),
                scheduled_for=when,
                delivered_at=self._clock.now(),
                payload={"scheduler_sequence": item.sequence},
            )
        return _VirtualScheduledTaskHandle(self, item)

    def cancel(self, item: _ScheduledItem) -> None:
        if item.cancelled:
            return
        item.cancelled = True
        if self._recorder is not None:
            self._recorder.record(
                "scheduler.cancelled",
                recorded_at=self._clock.now(),
                scheduled_for=item.scheduled_for,
                delivered_at=self._clock.now(),
                payload={"scheduler_sequence": item.sequence},
            )

    @property
    def next_deadline(self) -> datetime | None:
        self._discard_cancelled_head()
        return self._queue[0].scheduled_for if self._queue else None

    def run_due(self, *, max_callbacks: int | None = None) -> int:
        """Run every non-cancelled callback due at the current virtual instant."""

        if max_callbacks is not None and max_callbacks < 0:
            raise ValueError("max_callbacks must not be negative")
        executed = 0
        while True:
            self._discard_cancelled_head()
            if not self._queue or self._queue[0].scheduled_for > self._clock.now():
                return executed
            if max_callbacks is not None and executed >= max_callbacks:
                raise RuntimeError("timeline_livelock")
            item = heapq.heappop(self._queue)
            if self._recorder is not None:
                self._recorder.record(
                    "scheduler.delivered",
                    recorded_at=self._clock.now(),
                    scheduled_for=item.scheduled_for,
                    delivered_at=self._clock.now(),
                    payload={"scheduler_sequence": item.sequence},
                )
            item.callback()
            executed += 1

    def _discard_cancelled_head(self) -> None:
        while self._queue and self._queue[0].cancelled:
            heapq.heappop(self._queue)


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value
