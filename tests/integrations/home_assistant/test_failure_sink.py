import asyncio
import logging
from datetime import UTC, datetime

from controlel.application.ports.scheduled_runtime_failure_sink import (
    ScheduledRuntimeFailure,
)
from controlel.domain.commands.heating_action import HeatingAction
from custom_components.controlel.config import HomeAssistantServiceCall
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.failure_sink import (
    HomeAssistantScheduledFailureSink,
    clear_entry_issues,
)
from custom_components.controlel.heat_source import HomeAssistantServiceCallError
from custom_components.controlel.runtime_executor import HomeAssistantRuntimeExecutor

NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def test_recoverable_failure_reuses_issue_and_success_clears_it():
    async def scenario():
        executor = HomeAssistantRuntimeExecutor()
        created: list[tuple[tuple[object, ...], dict[str, object]]] = []
        deleted: list[tuple[object, str, str]] = []
        sink = HomeAssistantScheduledFailureSink(
            hass="hass",
            bridge=HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            entry_id="entry",
            logger=logging.getLogger(__name__),
            create_issue=lambda *args, **kwargs: created.append((args, kwargs)),
            delete_issue=lambda *args: deleted.append(args),
            warning_severity="warning",
            error_severity="error",
        )
        original = RuntimeError("service failure")
        error = HomeAssistantServiceCallError(
            HeatingAction.ENABLE_HEATING,
            HomeAssistantServiceCall("switch", "turn_on", "switch.boiler"),
            original,
        )
        failure = ScheduledRuntimeFailure(NOW, error)

        await executor.async_submit(sink.report, failure)
        await executor.async_submit(sink.report, failure)
        await asyncio.sleep(0)
        await executor.async_submit(sink.clear_service_failure_issue)
        await asyncio.sleep(0)
        await executor.async_close()
        return sink, failure, created, deleted

    sink, failure, created, deleted = asyncio.run(scenario())

    assert sink.last_failure is failure
    assert len(created) == 2
    assert {call[0][2] for call in created} == {sink.recoverable_issue_id}
    assert all(call[1]["severity"] == "warning" for call in created)
    assert deleted[-1] == ("hass", "controlel", sink.recoverable_issue_id)


def test_fatal_failure_preserves_exception_and_requests_async_shutdown():
    async def scenario():
        executor = HomeAssistantRuntimeExecutor()
        created: list[tuple[tuple[object, ...], dict[str, object]]] = []
        fatal: list[Exception] = []
        sink = HomeAssistantScheduledFailureSink(
            hass="hass",
            bridge=HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            entry_id="entry",
            logger=logging.getLogger(__name__),
            create_issue=lambda *args, **kwargs: created.append((args, kwargs)),
            delete_issue=lambda *args: None,
            warning_severity="warning",
            error_severity="error",
        )
        sink.bind_fatal_handler(fatal.append)
        error = RuntimeError("programming failure")
        failure = ScheduledRuntimeFailure(NOW, error)

        await executor.async_submit(sink.report, failure)
        await asyncio.sleep(0)
        await executor.async_close()
        return sink, error, failure, created, fatal

    sink, error, failure, created, fatal = asyncio.run(scenario())

    assert sink.last_failure is failure
    assert fatal == [error]
    assert created[0][0][2] == sink.fatal_issue_id
    assert created[0][1]["severity"] == "error"


def test_entry_removal_clears_recoverable_and_fatal_issues():
    deleted: list[tuple[object, str, str]] = []

    clear_entry_issues(
        "hass",
        "entry",
        lambda *args: deleted.append(args),
    )

    assert deleted == [
        ("hass", "controlel", "entry_heat_source_service_failure"),
        ("hass", "controlel", "entry_fatal_runtime_failure"),
    ]
