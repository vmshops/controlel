from inspect import signature

from controlel.application.ports.scheduler import ScheduledTaskHandle, Scheduler


def test_scheduler_public_signatures_remain_narrow():
    assert list(signature(Scheduler.schedule_at).parameters) == [
        "self",
        "when",
        "callback",
    ]
    assert list(signature(ScheduledTaskHandle.cancel).parameters) == ["self"]
