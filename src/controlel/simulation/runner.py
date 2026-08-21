"""Deterministic, module-neutral Scenario v1 execution kernel."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from importlib import metadata
from uuid import uuid4

from controlel.simulation.model import (
    ASSERTION_CONTRACT_VERSION,
    REPLAY_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    SCHEDULER_POLICY_VERSION,
    SEMANTIC_FINGERPRINT_POLICY_VERSION,
    SIMULATION_CONTRACT_VERSION,
    TIMELINE_ORDERING_POLICY_VERSION,
    TRACE_SCHEMA_VERSION,
    AssertionResult,
    AssertionStatus,
    ReplayArtifact,
    SimulationOutcome,
    SimulationReport,
    SimulationRun,
)
from controlel.simulation.recorder import SimulationRecorder
from controlel.simulation.scenario import (
    CANONICALIZATION_POLICY_VERSION,
    Scenario,
    ScenarioTimelineItem,
    TimelinePhase,
)
from controlel.simulation.time import DeterministicScheduler, VirtualClock

MAX_VIRTUAL_DURATION = timedelta(days=7)
MAX_EXECUTED_TRANSITIONS = 10_000


class TrustedSimulationAdapter(ABC):
    """Nominal boundary for reviewed, simulation-owned module compositions.

    Implementations belong to the simulation outer layer and may compose only
    virtual providers, recording command ports, and isolated trace sinks. This
    is deliberately not a dynamic plugin contract.
    """

    adapter_version: str

    @abstractmethod
    def __init__(
        self,
        scenario: Scenario,
        clock: VirtualClock,
        scheduler: DeterministicScheduler,
        recorder: SimulationRecorder,
    ) -> None: ...

    @abstractmethod
    def dispatch(self, item: ScenarioTimelineItem) -> None: ...

    @abstractmethod
    def capture_after_scheduler(self) -> None: ...

    @abstractmethod
    def capture_diagnostics(self, reason: str) -> None: ...


class ScenarioRunner:
    """Execute one explicit adapter against virtual time and isolated outputs."""

    def __init__(
        self,
        adapter_type: type[TrustedSimulationAdapter],
        *,
        environment_id: str = "shadow-local",
    ) -> None:
        if not isinstance(adapter_type, type) or not issubclass(adapter_type, TrustedSimulationAdapter):
            raise TypeError("adapter_type must be a trusted simulation adapter class")
        if not environment_id:
            raise ValueError("environment_id must not be empty")
        adapter_version = getattr(adapter_type, "adapter_version", None)
        if not isinstance(adapter_version, str) or not adapter_version:
            raise ValueError("adapter_type must declare a non-empty adapter_version")
        self._adapter_type = adapter_type
        self._adapter_version = adapter_version
        self._environment_id = environment_id

    def run(self, scenario: Scenario, *, run_id: str | None = None) -> SimulationReport:
        clock = VirtualClock(scenario.start_at)
        run = SimulationRun(
            run_id=run_id or f"simulation-run:{uuid4()}",
            environment_id=self._environment_id,
            scenario_id=scenario.scenario_id,
            started_at=scenario.start_at,
        )
        recorder = SimulationRecorder(run)
        scheduler = DeterministicScheduler(clock, recorder)
        adapter = self._adapter_type(scenario, clock, scheduler, recorder)
        errors: list[str] = []

        try:
            self._execute_timeline(scenario, clock, scheduler, adapter)
            adapter.capture_diagnostics("run_complete")
        except Exception as error:
            errors.append(f"{type(error).__name__}: {error}")
            recorder.record(
                "simulation.error",
                recorded_at=clock.now(),
                delivered_at=clock.now(),
                payload={
                    "exception_type": type(error).__name__,
                    "reason_code": "simulation_execution_error",
                },
            )

        assertions = self._evaluate_expectations(scenario, recorder, errors)
        for assertion in assertions:
            recorder.record(
                "assertion.result",
                recorded_at=clock.now(),
                delivered_at=clock.now(),
                payload=assertion.model_dump(mode="json"),
            )
        if errors:
            outcome = SimulationOutcome.ERROR
        elif any(assertion.status is AssertionStatus.FAILED for assertion in assertions):
            outcome = SimulationOutcome.FAILED
        else:
            outcome = SimulationOutcome.PASSED
        return SimulationReport(
            run=run,
            scenario_hash=scenario.content_hash,
            core_version=_installed_core_version(),
            module_adapter_version=self._adapter_version,
            ended_at=clock.now(),
            outcome=outcome,
            records=recorder.records,
            assertions=assertions,
            errors=tuple(errors),
            semantic_fingerprint=recorder.semantic_fingerprint(),
        )

    def replay(self, artifact: ReplayArtifact, *, run_id: str | None = None) -> SimulationReport:
        self._validate_replay_versions(artifact)
        scenario = Scenario.from_mapping(artifact.canonical_scenario)
        self._validate_replay_scenario_metadata(artifact, scenario)
        if scenario.content_hash != artifact.scenario_hash:
            raise ValueError("replay scenario hash does not match artifact")
        report = self.run(scenario, run_id=run_id)
        if report.semantic_fingerprint != artifact.expected_semantic_fingerprint:
            raise ValueError("replay semantic fingerprint does not match artifact")
        return report

    @staticmethod
    def _execute_timeline(
        scenario: Scenario,
        clock: VirtualClock,
        scheduler: DeterministicScheduler,
        adapter: TrustedSimulationAdapter,
    ) -> None:
        grouped: dict[datetime, list[ScenarioTimelineItem]] = {}
        for item in scenario.timeline:
            grouped.setdefault(item.delivery_at, []).append(item)
        scenario_times = sorted(grouped)
        scenario_index = 0
        transitions = 0
        limit_at = scenario.start_at + MAX_VIRTUAL_DURATION

        while scenario_index < len(scenario_times) or scheduler.next_deadline is not None:
            next_scenario_at = scenario_times[scenario_index] if scenario_index < len(scenario_times) else None
            next_deadline = scheduler.next_deadline
            candidates = tuple(value for value in (next_scenario_at, next_deadline) if value is not None)
            if not candidates:
                break
            next_at = min(candidates)
            delivery_at = max(next_at, clock.now())
            if delivery_at > limit_at:
                raise RuntimeError("maximum virtual duration exceeded")
            clock.advance_to(delivery_at)

            items = grouped.get(next_scenario_at, []) if next_scenario_at == next_at else []
            for item in items:
                if item.phase is TimelinePhase.BEFORE_DEADLINES:
                    adapter.dispatch(item)
                    transitions += 1
                    _check_transition_limit(transitions)

            transitions += scheduler.run_due(max_callbacks=MAX_EXECUTED_TRANSITIONS - transitions)
            _check_transition_limit(transitions)
            adapter.capture_after_scheduler()

            for item in items:
                if item.phase is TimelinePhase.AFTER_DEADLINES:
                    adapter.dispatch(item)
                    transitions += 1
                    _check_transition_limit(transitions)

            transitions += scheduler.run_due(max_callbacks=MAX_EXECUTED_TRANSITIONS - transitions)
            _check_transition_limit(transitions)
            adapter.capture_after_scheduler()

            if items:
                scenario_index += 1

    @staticmethod
    def _evaluate_expectations(
        scenario: Scenario,
        recorder: SimulationRecorder,
        errors: list[str],
    ) -> tuple[AssertionResult, ...]:
        results: list[AssertionResult] = []
        for index, expectation in enumerate(scenario.expectations):
            if expectation.type.startswith("operational_event."):
                matching = tuple(
                    record.record_id
                    for record in recorder.records
                    if record.kind == "operational_event" and record.payload.get("event_code") == expectation.event_code
                )
                exists = bool(matching)
                expected_exists = expectation.type == "operational_event.exists"
                passed = exists is expected_exists
                reason_code = "expectation_satisfied" if passed else "operational_event_expectation_failed"
            else:
                matching = ()
                passed = not errors
                reason_code = "expectation_satisfied" if passed else "unhandled_error_recorded"
            results.append(
                AssertionResult(
                    expectation_index=index,
                    expectation_type=expectation.type,
                    status=AssertionStatus.PASSED if passed else AssertionStatus.FAILED,
                    reason_code=reason_code,
                    evidence_record_ids=matching,
                )
            )
        return tuple(results)

    def _validate_replay_versions(self, artifact: ReplayArtifact) -> None:
        expected = {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "trace_schema_version": TRACE_SCHEMA_VERSION,
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "simulation_contract_version": SIMULATION_CONTRACT_VERSION,
            "scheduler_policy_version": SCHEDULER_POLICY_VERSION,
            "timeline_ordering_policy_version": TIMELINE_ORDERING_POLICY_VERSION,
            "semantic_fingerprint_policy_version": SEMANTIC_FINGERPRINT_POLICY_VERSION,
            "assertion_contract_version": ASSERTION_CONTRACT_VERSION,
            "canonicalization_policy_version": CANONICALIZATION_POLICY_VERSION,
            "module_adapter_version": self._adapter_version,
        }
        for field_name, expected_value in expected.items():
            if getattr(artifact, field_name) != expected_value:
                raise ValueError(f"unsupported replay {field_name}")

    @staticmethod
    def _validate_replay_scenario_metadata(artifact: ReplayArtifact, scenario: Scenario) -> None:
        expected = {
            "scenario_schema_version": scenario.schema_version,
            "module": scenario.module,
            "module_contract_version": scenario.module_contract_version,
        }
        for field_name, expected_value in expected.items():
            if getattr(artifact, field_name) != expected_value:
                raise ValueError(f"replay {field_name} does not match canonical scenario")


def _check_transition_limit(count: int) -> None:
    if count > MAX_EXECUTED_TRANSITIONS:
        raise RuntimeError("timeline_livelock")


def _installed_core_version() -> str:
    try:
        return metadata.version("controlel")
    except metadata.PackageNotFoundError:
        return "0.0.0+uninstalled"
