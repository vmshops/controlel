"""Application-level command authority and bounded runtime supervision."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Protocol, TypeVar

from controlel.application.ports.heat_source_port import HeatSourcePort
from controlel.application.ports.scheduled_runtime_failure_sink import ScheduledRuntimeFailure
from controlel.application.ports.scheduler import ScheduledTaskHandle, Scheduler
from controlel.application.runtime.failsafe_runtime import FailsafeRuntime
from controlel.application.state.runtime_supervision_state import (
    RuntimeHandoverEvidence,
    RuntimeSupervisionDiagnosticsV1,
    RuntimeSupervisionState,
)
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.heat_delivery import ObservationQuality
from controlel.domain.operating_mode import OperatingMode, SafeHeatingTemperatureEvidence
from controlel.domain.runtime_supervision import (
    CommandAuthority,
    FailsafeReason,
    FatalCauseCode,
    RestartPolicy,
    SupervisorPhase,
)
from controlel.domain.source_control import (
    ReportedSourceEvidence,
    SourceCapabilities,
    SourceOwnership,
)

T = TypeVar("T")
RestartFactory = Callable[[HeatSourcePort, RuntimeHandoverEvidence], object]


class Clock(Protocol):
    def now(self) -> datetime: ...


class StoppableRuntime(Protocol):
    def stop(self) -> None: ...


class CommandAuthorityError(RuntimeError):
    """Raised when a quarantined controller attempts source dispatch."""


class _AuthorityPort:
    def __init__(self, supervisor: "RuntimeSupervisor", authority: CommandAuthority, generation: int) -> None:
        self.supervisor, self.authority, self.generation = supervisor, authority, generation

    def execute(self, command: HeatSourceCommand) -> None:
        if not self.supervisor._owns(self.authority, self.generation):
            raise CommandAuthorityError("controller generation does not own command authority")
        self.supervisor._source.execute(command)


class RuntimeSupervisor:
    """Own one command authority, automatic failsafe, and bounded restart campaign."""

    def __init__(
        self,
        source: HeatSourcePort,
        clock: Clock,
        *,
        scheduler: Scheduler | None = None,
        restart_policy: RestartPolicy = RestartPolicy(),
        failsafe_factory: Callable[[HeatSourcePort], FailsafeRuntime] | None = None,
        restart_factory: RestartFactory | None = None,
    ) -> None:
        self._source, self._clock, self._scheduler = source, clock, scheduler
        self.restart_policy, self._failsafe_factory = restart_policy, failsafe_factory
        self._restart_factory = restart_factory
        self._generation, self._campaign = 1, 1
        self._normal_active, self._authority = True, CommandAuthority.NORMAL
        self._trusted_evidence: SafeHeatingTemperatureEvidence | None = None
        self._reported_evidence: ReportedSourceEvidence | None = None
        self._normal_runtime: StoppableRuntime | None = None
        self._failsafe: FailsafeRuntime | None = None
        self._restart_handle: ScheduledTaskHandle | None = None
        self._manual_handle: ScheduledTaskHandle | None = None
        self._manual_generation = 0
        self.state = RuntimeSupervisionState(
            SupervisorPhase.NORMAL,
            self._authority,
            self._generation,
            None,
            None,
            None,
            0,
            restart_policy.attempt_limit,
            None,
            False,
            None,
            None,
        )

    def normal_port(self) -> HeatSourcePort:
        return _AuthorityPort(self, CommandAuthority.NORMAL, self._generation)

    def failsafe_port(self) -> HeatSourcePort:
        return _AuthorityPort(self, CommandAuthority.FAILSAFE, self._generation)

    def attach_normal_runtime(self, runtime: StoppableRuntime) -> None:
        self._normal_runtime = runtime

    def scheduled_failure_sink(self):
        supervisor = self

        class Sink:
            def report(self, failure: ScheduledRuntimeFailure) -> None:
                supervisor.report_fatal(failure.error)

        return Sink()

    def run_normal(self, operation: Callable[[], T]) -> T | None:
        if not self._normal_active:
            return None
        try:
            return operation()
        except Exception as error:
            self.report_fatal(error)
            return None

    def update_trusted_evidence(self, evidence: SafeHeatingTemperatureEvidence | None) -> None:
        self._trusted_evidence = evidence
        if self._failsafe is not None and not self._normal_active:
            self._evaluate_failsafe()

    def ingest_reported_source(self, evidence: ReportedSourceEvidence) -> None:
        self._reported_evidence = evidence
        if self._failsafe is not None:
            self._failsafe.ingest_reported_source(evidence)

    def report_fatal(self, error: Exception) -> None:
        self._normal_active = False
        self._generation += 1
        self._campaign += 1
        self._authority = CommandAuthority.FAILSAFE
        failed, self._normal_runtime = self._normal_runtime, None
        handover = self._normal_handover_evidence(failed) if failed is not None else None
        if failed is not None:
            try:
                failed.stop()
            except Exception:
                pass
        self._failsafe = self._failsafe_factory(self.failsafe_port()) if self._failsafe_factory else None
        if self._failsafe is not None and handover is not None:
            self._failsafe.restore_handover(handover)
        elif self._failsafe is not None and self._reported_evidence is not None:
            self._failsafe.ingest_reported_source(self._reported_evidence)
        self._enter_failsafe(_cause_code(error))
        self._evaluate_failsafe()
        self._schedule_restart()

    def request_restart(self, factory: RestartFactory | None = None) -> object | None:
        now = self._clock.now()
        if self.state.restart_budget_exhausted or (self.state.next_restart_at and now < self.state.next_restart_at):
            return None
        chosen = factory or self._restart_factory
        if chosen is None:
            return None
        attempts = self.state.restart_attempt_count + 1
        evidence = self._handover_evidence()
        try:
            candidate = chosen(_AuthorityPort(self, CommandAuthority.NORMAL, self._generation), evidence)
        except Exception as error:
            exhausted = attempts >= self.restart_policy.attempt_limit
            self.state = replace(
                self.state,
                phase=SupervisorPhase.RESTART_EXHAUSTED if exhausted else SupervisorPhase.RESTART_WAIT,
                fatal_cause_code=_cause_code(error),
                restart_attempt_count=attempts,
                next_restart_at=None if exhausted else now + self.restart_policy.retry_interval,
                restart_budget_exhausted=exhausted,
            )
            if not exhausted:
                self._schedule_restart()
            return None
        self._invalidate_callbacks()
        self._authority, self._normal_active = CommandAuthority.NORMAL, True
        self._normal_runtime = candidate if callable(getattr(candidate, "stop", None)) else None
        self.state = replace(
            self.state,
            phase=SupervisorPhase.NORMAL,
            command_authority=self._authority,
            failsafe_mode=None,
            failsafe_reason=None,
            restart_attempt_count=attempts,
            next_restart_at=None,
            restart_budget_exhausted=False,
            manual_recovery_deadline=None,
            last_recovered_to_normal_at=now,
        )
        return candidate

    def reset_restart_campaign(self) -> None:
        self._campaign += 1
        self._cancel(self._restart_handle)
        self._restart_handle = None
        self.state = replace(
            self.state,
            restart_attempt_count=0,
            restart_budget_exhausted=False,
            next_restart_at=self._clock.now() + self.restart_policy.retry_interval,
        )
        self._schedule_restart()

    def activate_manual_recovery(self) -> None:
        now = self._clock.now()
        self._manual_generation += 1
        token = self._manual_generation
        self._cancel(self._manual_handle)
        deadline = now + self.restart_policy.manual_recovery_duration
        self.state = replace(
            self.state,
            failsafe_mode=OperatingMode.MANUAL_RECOVERY_HEAT,
            failsafe_reason=FailsafeReason.MANUAL_RECOVERY,
            manual_recovery_deadline=deadline,
        )
        if self._failsafe:
            self._evaluate_failsafe(manual_recovery=True)
        if self._scheduler:
            self._manual_handle = self._scheduler.schedule_at(deadline, lambda: self._manual_expired(token, deadline))

    def diagnostics(self) -> RuntimeSupervisionDiagnosticsV1:
        state = self.state
        return RuntimeSupervisionDiagnosticsV1(
            1,
            state.phase.value,
            state.command_authority.value,
            state.normal_generation,
            state.fatal_cause_code,
            state.failsafe_mode.value if state.failsafe_mode else None,
            state.failsafe_reason.value if state.failsafe_reason else None,
            state.restart_attempt_count,
            state.restart_budget,
            _iso(state.next_restart_at),
            state.restart_budget_exhausted,
            _iso(state.manual_recovery_deadline),
            _iso(state.last_recovered_to_normal_at),
        )

    def _enter_failsafe(self, code: str | None) -> None:
        valid = self._trusted_evidence is not None and self._trusted_evidence.quality is ObservationQuality.VALID
        now = self._clock.now()
        self.state = RuntimeSupervisionState(
            SupervisorPhase.FAILSAFE,
            CommandAuthority.FAILSAFE,
            self._generation,
            code,
            OperatingMode.SAFE_HEATING if valid else OperatingMode.EMERGENCY_OFF,
            FailsafeReason.VALID_TRUSTED_EVIDENCE if valid else FailsafeReason.TRUSTED_EVIDENCE_UNAVAILABLE,
            self.state.restart_attempt_count,
            self.restart_policy.attempt_limit,
            now + self.restart_policy.retry_interval,
            False,
            None,
            self.state.last_recovered_to_normal_at,
        )

    def _evaluate_failsafe(self, *, manual_recovery: bool = False) -> None:
        if self._failsafe:
            try:
                self._failsafe.evaluate(
                    now=self._clock.now(),
                    evidence=self._trusted_evidence,
                    manual_recovery=manual_recovery,
                )
            except Exception:
                self.state = replace(
                    self.state,
                    fatal_cause_code=FatalCauseCode.FAILSAFE_DISPATCH_FAILED.value,
                )

    def _schedule_restart(self) -> None:
        if not self._scheduler or not self._restart_factory or not self.state.next_restart_at:
            return
        self._cancel(self._restart_handle)
        campaign, generation, deadline = self._campaign, self._generation, self.state.next_restart_at
        self._restart_handle = self._scheduler.schedule_at(
            deadline, lambda: self._restart_callback(campaign, generation, deadline)
        )

    def _restart_callback(self, campaign: int, generation: int, deadline: datetime) -> None:
        if campaign != self._campaign or generation != self._generation or self._normal_active:
            return
        if self._clock.now() < deadline:
            self._schedule_restart()
            return
        self._restart_handle = None
        self.request_restart()

    def _manual_expired(self, token: int, deadline: datetime) -> None:
        if token != self._manual_generation or self._normal_active or self._clock.now() < deadline:
            return
        self._manual_handle = None
        self._enter_failsafe(self.state.fatal_cause_code)
        self._evaluate_failsafe()

    def _handover_evidence(self) -> RuntimeHandoverEvidence:
        if self._failsafe is None:
            return RuntimeHandoverEvidence(None, SourceOwnership.EXTERNAL, SourceCapabilities(), None, None)
        return RuntimeHandoverEvidence(
            self._failsafe.reported_source_evidence,
            self._failsafe.ownership,
            self._failsafe.capabilities,
            self._failsafe.source_control_state,
            self._failsafe.source_reconciliation_state,
        )

    def _normal_handover_evidence(self, runtime: StoppableRuntime) -> RuntimeHandoverEvidence:
        reported = getattr(runtime, "reported_source_evidence", None)
        if reported is None:
            reported = self._reported_evidence
        ownership = getattr(runtime, "source_ownership", SourceOwnership.EXTERNAL)
        capabilities = getattr(runtime, "source_capabilities", SourceCapabilities())
        return RuntimeHandoverEvidence(
            reported,
            ownership,
            capabilities,
            getattr(runtime, "source_control_state", None),
            getattr(runtime, "source_reconciliation_state", None),
        )

    def _invalidate_callbacks(self) -> None:
        self._campaign += 1
        self._manual_generation += 1
        self._cancel(self._restart_handle)
        self._cancel(self._manual_handle)
        self._restart_handle = self._manual_handle = None

    def _owns(self, authority: CommandAuthority, generation: int) -> bool:
        return authority is self._authority and generation == self._generation

    @staticmethod
    def _cancel(handle: ScheduledTaskHandle | None) -> None:
        if handle:
            try:
                handle.cancel()
            except Exception:
                pass


def _cause_code(error: Exception) -> str:
    if isinstance(error, ValueError):
        return FatalCauseCode.INVALID_RUNTIME_STATE.value
    if isinstance(error, RuntimeError):
        return FatalCauseCode.RUNTIME_FAILURE.value
    return FatalCauseCode.UNEXPECTED_EXCEPTION.value


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
