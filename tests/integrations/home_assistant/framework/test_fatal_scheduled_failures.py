import logging
from datetime import UTC, datetime

import pytest
from homeassistant.helpers import issue_registry as ir

from controlel.application.ports.scheduled_runtime_failure_sink import ScheduledRuntimeFailure
from controlel.application.runtime.fatal_shutdown_result import (
    FatalShutdownEmergencyOutcome,
    FatalShutdownResult,
)
from controlel.application.runtime.runtime_lifecycle import RuntimeReentrancyError
from controlel.domain.commands.heating_action import HeatingAction
from custom_components.controlel.config import HomeAssistantServiceCall
from custom_components.controlel.const import DOMAIN
from custom_components.controlel.heat_source import HomeAssistantServiceCallError
from custom_components.controlel.operational import (
    CommandOutcome,
    EmergencyDisableOutcome,
    RuntimeStatus,
    SafetyState,
)
from custom_components.controlel.scheduler import HomeAssistantSchedulerInstallationError

from .test_state_ingestion import RecordingRuntime, make_host

NOW = datetime(2026, 7, 24, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeReentrancyError("process_temperature", "scheduled_callback"),
        ValueError("clock regression"),
        HomeAssistantSchedulerInstallationError(NOW, RuntimeError("timer install failed")),
        RuntimeError("unexpected scheduled programming failure"),
    ],
    ids=["reentrancy", "clock-regression", "scheduler-install", "programming"],
)
@pytest.mark.asyncio
async def test_real_ha_scheduled_failure_is_fatal_and_schedules_terminal_shutdown(
    hass,
    caplog,
    error,
) -> None:
    runtime = RecordingRuntime()
    host = make_host(hass, runtime)
    await host.async_initialize()
    registry = ir.async_get(hass)
    failure = ScheduledRuntimeFailure(NOW, error)

    def obsolete_callback() -> None:
        runtime.operations.append(("obsolete", None))

    with caplog.at_level(logging.ERROR):
        host.submit_scheduled_callback(lambda: host._failure_sink.report(failure))
        await hass.async_block_till_done()

    issue = registry.async_get_issue(DOMAIN, host._failure_sink.fatal_issue_id)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.translation_key == "fatal_runtime_failure"
    assert host.accepting is False
    assert host.stopped is True
    assert host._executor.closed is True
    assert host.snapshot_source.current.runtime_status is RuntimeStatus.FATAL_ERROR
    assert host.snapshot_source.current.safety_state is SafetyState.FATAL_ERROR
    assert host.snapshot_source.current.fatal_failure_active is True
    assert host.snapshot_source.current.last_command_outcome is CommandOutcome.FAILED_FATAL
    assert host.snapshot_source.current.emergency_disable_outcome is EmergencyDisableOutcome.NO_COMMAND_PATH_AVAILABLE
    assert host.snapshot_source.current.emergency_disable_attempted is False
    assert host.snapshot_source.current.original_fatal_cause == type(error).__name__
    assert [operation for operation, _ in runtime.operations].count("stop") == 1
    operations_after_fatal = list(runtime.operations)
    host.submit_scheduled_callback(obsolete_callback)
    await hass.async_block_till_done()
    assert runtime.operations == operations_after_fatal
    assert "Fatal Controlel runtime failure" in caplog.text
    assert "Stopping Controlel after fatal runtime failure" in caplog.text


@pytest.mark.asyncio
async def test_recoverable_real_service_failure_leaves_host_running(hass) -> None:
    runtime = RecordingRuntime()
    host = make_host(hass, runtime)
    await host.async_initialize()
    error = HomeAssistantServiceCallError(
        HeatingAction.ENABLE_HEATING,
        HomeAssistantServiceCall("switch", "turn_on", "switch.boiler"),
        RuntimeError("recoverable"),
    )

    host._failure_sink.handle_synchronous_failure(error)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN,
        host._failure_sink.recoverable_issue_id,
    )

    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert host.accepting is True
    assert host.stopped is False
    assert host.snapshot_source.current.recoverable_failure_active is True
    assert host.snapshot_source.current.last_command_outcome is CommandOutcome.FAILED_RECOVERABLE
    host._failure_sink.clear_service_failure_issue()
    await hass.async_block_till_done()
    assert host.snapshot_source.current.recoverable_failure_active is False
    await host.async_stop()


class FatalOutcomeRuntime(RecordingRuntime):
    def __init__(
        self,
        outcome: FatalShutdownEmergencyOutcome,
        *,
        failure_type: str | None = None,
    ) -> None:
        super().__init__()
        self.outcome = outcome
        self.failure_type = failure_type

    def fatal_shutdown(
        self,
        failed_action: HeatingAction | None,
        requested_at: datetime,
    ) -> FatalShutdownResult:
        self.operations.append(("fatal_shutdown", failed_action))
        attempted = self.outcome in {
            FatalShutdownEmergencyOutcome.DISABLE_DISPATCHED,
            FatalShutdownEmergencyOutcome.DISABLE_FAILED,
        }
        return FatalShutdownResult(
            emergency_disable_attempted=attempted,
            emergency_disable_outcome=self.outcome,
            timestamp=requested_at,
            original_failed_action=failed_action,
            emergency_failure_type=self.failure_type,
        )


@pytest.mark.parametrize(
    ("core_outcome", "expected", "failure_type"),
    [
        (
            FatalShutdownEmergencyOutcome.DISABLE_DISPATCHED,
            EmergencyDisableOutcome.DISPATCHED,
            None,
        ),
        (
            FatalShutdownEmergencyOutcome.DISABLE_FAILED,
            EmergencyDisableOutcome.FAILED,
            "RuntimeError",
        ),
        (
            FatalShutdownEmergencyOutcome.DISABLE_SKIPPED_ALREADY_FAILED,
            EmergencyDisableOutcome.SKIPPED_ALREADY_FAILED,
            None,
        ),
    ],
)
@pytest.mark.asyncio
async def test_fatal_emergency_outcomes_are_terminal_and_truthful(
    hass,
    core_outcome,
    expected,
    failure_type,
) -> None:
    runtime = FatalOutcomeRuntime(core_outcome, failure_type=failure_type)
    host = make_host(hass, runtime)
    await host.async_initialize()
    error = (
        HomeAssistantServiceCallError(
            HeatingAction.DISABLE_HEATING,
            HomeAssistantServiceCall("switch", "turn_off", "switch.boiler"),
            RuntimeError("original disable failed"),
        )
        if core_outcome is FatalShutdownEmergencyOutcome.DISABLE_SKIPPED_ALREADY_FAILED
        else RuntimeError("fatal")
    )

    host.request_fatal_shutdown(error)
    await hass.async_block_till_done()

    snapshot = host.snapshot_source.current
    assert host.stopped is True
    assert snapshot.runtime_status is RuntimeStatus.FATAL_ERROR
    assert snapshot.emergency_disable_outcome is expected
    assert snapshot.emergency_disable_attempted is (
        expected
        in {
            EmergencyDisableOutcome.DISPATCHED,
            EmergencyDisableOutcome.FAILED,
        }
    )
    assert snapshot.original_fatal_cause == type(error).__name__
    assert [operation for operation, _ in runtime.operations].count("fatal_shutdown") == 1
    assert [operation for operation, _ in runtime.operations].count("stop") == 1
    assert host.snapshot_source.trace[-1].emergency_disable_outcome is expected


@pytest.mark.asyncio
async def test_old_fatal_host_callbacks_cannot_affect_replacement_runtime(hass) -> None:
    old_runtime = FatalOutcomeRuntime(FatalShutdownEmergencyOutcome.DISABLE_DISPATCHED)
    old_host = make_host(hass, old_runtime)
    await old_host.async_initialize()

    old_host.request_fatal_shutdown(RuntimeError("fatal"))
    await hass.async_block_till_done()

    replacement_runtime = RecordingRuntime()
    replacement_host = make_host(hass, replacement_runtime)
    await replacement_host.async_initialize()
    old_host.submit_scheduled_callback(lambda: replacement_runtime.operations.append(("obsolete", None)))
    replacement_host.submit_scheduled_callback(lambda: replacement_runtime.operations.append(("replacement", None)))
    await hass.async_block_till_done()

    assert ("obsolete", None) not in replacement_runtime.operations
    assert ("replacement", None) in replacement_runtime.operations
    await replacement_host.async_stop()
