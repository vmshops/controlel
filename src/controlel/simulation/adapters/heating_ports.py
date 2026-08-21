"""Simulation-owned recording output ports with deterministic outcomes."""

from __future__ import annotations

from controlel.application.ports.scheduled_runtime_failure_sink import ScheduledRuntimeFailure
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.simulation.recorder import SimulationRecorder
from controlel.simulation.time import VirtualClock


class SimulatedDispatchError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class RecordingHeatSourcePort:
    """Record source requests without changing any reported or physical state."""

    def __init__(self, clock: VirtualClock, recorder: SimulationRecorder) -> None:
        self._clock = clock
        self._recorder = recorder
        self._failure_reason_code: str | None = None

    def configure_success(self) -> None:
        self._failure_reason_code = None

    def configure_failure(self, reason_code: str) -> None:
        if not reason_code:
            raise ValueError("reason_code must not be empty")
        self._failure_reason_code = reason_code

    def execute(self, command: HeatSourceCommand) -> None:
        failure = self._failure_reason_code
        outcome = "failed" if failure is not None else "dispatched"
        self._recorder.record(
            "command.source",
            recorded_at=self._clock.now(),
            delivered_at=self._clock.now(),
            payload={
                "action": command.action.value,
                "command_family": command.command_type.value,
                "dispatch_outcome": outcome,
                "failure_reason_code": failure,
            },
        )
        if failure is not None:
            raise SimulatedDispatchError(failure)


class RecordingScheduledFailureSink:
    """Keep scheduled runtime failures inside the isolated Shadow trace."""

    def __init__(self, clock: VirtualClock, recorder: SimulationRecorder) -> None:
        self._clock = clock
        self._recorder = recorder

    def report(self, failure: ScheduledRuntimeFailure) -> None:
        self._recorder.record(
            "runtime.scheduled_failure",
            recorded_at=self._clock.now(),
            scheduled_for=failure.scheduled_for,
            delivered_at=self._clock.now(),
            payload={
                "exception_type": type(failure.error).__name__,
                "reason_code": "scheduled_runtime_failure",
            },
        )
