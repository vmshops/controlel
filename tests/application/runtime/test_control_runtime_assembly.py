from datetime import UTC, datetime, timedelta

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.control_runtime_assembly import ControlRuntimeAssembly
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class NoOpHandle:
    def cancel(self) -> None:
        pass


class NoOpScheduler:
    def schedule_at(self, when: datetime, callback):
        return NoOpHandle()


class NoOpFailureSink:
    def report(self, failure) -> None:
        pass


class RecordingSourcePort:
    def __init__(self) -> None:
        self.commands = []

    def execute(self, command) -> None:
        self.commands.append(command)


def test_shared_assembly_builds_the_ordinary_runtime_with_supplied_outer_ports() -> None:
    clock = FixedClock()
    scheduler = NoOpScheduler()
    source = RecordingSourcePort()
    assembly = ControlRuntimeAssembly(
        sensor_repository=SensorRepository(),
        zone_repository=ZoneRepository(),
        clock=clock,
        scheduler=scheduler,
        scheduled_failure_sink=NoOpFailureSink(),
        max_future_skew=timedelta(minutes=1),
        indeterminate_grace_period=timedelta(minutes=5),
        indeterminate_timeout_action=HeatingAction.DISABLE_HEATING,
    )

    runtime = assembly.build(source)

    assert isinstance(runtime, ControlRuntime)
    assert runtime.clock is clock
    assert runtime.scheduler is scheduler
    assert runtime.heat_source_command_dispatcher.heat_source_port is source
