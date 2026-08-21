from datetime import UTC, datetime, timedelta

import pytest

from controlel.simulation import DeterministicScheduler, SimulationRecorder, SimulationRun, VirtualClock


def test_virtual_clock_and_scheduler_preserve_deadline_then_insertion_order() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = VirtualClock(start)
    scheduler = DeterministicScheduler(clock)
    observed: list[str] = []

    scheduler.schedule_at(start + timedelta(minutes=2), lambda: observed.append("later"))
    scheduler.schedule_at(start + timedelta(minutes=1), lambda: observed.append("first"))
    cancelled = scheduler.schedule_at(start + timedelta(minutes=1), lambda: observed.append("cancelled"))
    scheduler.schedule_at(start + timedelta(minutes=1), lambda: observed.append("second"))
    cancelled.cancel()

    clock.advance_to(start + timedelta(minutes=1))
    assert scheduler.run_due() == 2
    clock.advance_to(start + timedelta(minutes=2))
    assert scheduler.run_due() == 1

    assert observed == ["first", "second", "later"]


def test_virtual_clock_never_moves_backwards() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = VirtualClock(start)
    clock.advance_to(start + timedelta(seconds=1))

    with pytest.raises(ValueError, match="cannot move backwards"):
        clock.advance_to(start)


def test_scheduler_stops_immediate_self_rescheduling_at_the_explicit_limit() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = VirtualClock(start)
    scheduler = DeterministicScheduler(clock)

    def reschedule() -> None:
        scheduler.schedule_at(clock.now(), reschedule)

    scheduler.schedule_at(start, reschedule)

    with pytest.raises(RuntimeError, match="timeline_livelock"):
        scheduler.run_due(max_callbacks=3)


def test_past_scheduled_callback_runs_now_and_retains_original_deadline() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = VirtualClock(start)
    recorder = SimulationRecorder(
        SimulationRun(run_id="run", environment_id="shadow", scenario_id="past-event", started_at=start)
    )
    scheduler = DeterministicScheduler(clock, recorder)
    delivered: list[datetime] = []
    clock.advance_to(start + timedelta(minutes=2))

    scheduler.schedule_at(start + timedelta(minutes=1), lambda: delivered.append(clock.now()))
    scheduler.run_due()

    delivery_record = next(record for record in recorder.records if record.kind == "scheduler.delivered")
    assert delivered == [start + timedelta(minutes=2)]
    assert delivery_record.scheduled_for == start + timedelta(minutes=1)
    assert delivery_record.delivered_at == start + timedelta(minutes=2)
