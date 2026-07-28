import logging
from datetime import UTC, datetime

import pytest
from homeassistant.helpers import issue_registry as ir

from controlel.application.ports.scheduled_runtime_failure_sink import ScheduledRuntimeFailure
from controlel.application.runtime.runtime_lifecycle import RuntimeReentrancyError
from controlel.domain.commands.heating_action import HeatingAction
from custom_components.controlel.config import HomeAssistantServiceCall
from custom_components.controlel.const import DOMAIN
from custom_components.controlel.heat_source import HomeAssistantServiceCallError
from custom_components.controlel.operational import (
    CommandOutcome,
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
    assert [operation for operation, _ in runtime.operations].count("stop") == 1
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
