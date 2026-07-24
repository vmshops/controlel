import asyncio
from datetime import UTC, datetime, timedelta
from threading import get_ident

import pytest

from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.runtime_executor import HomeAssistantRuntimeExecutor
from custom_components.controlel.scheduler import (
    HomeAssistantScheduler,
    HomeAssistantSchedulerCancellationError,
    HomeAssistantSchedulerInstallationError,
)

NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def test_timer_installation_callback_and_cancellation_cross_the_correct_boundaries():
    async def scenario():
        executor = HomeAssistantRuntimeExecutor()
        loop_thread = get_ident()
        installed: list[tuple[object, object, datetime, int]] = []
        cancelled: list[None] = []
        submitted_tasks: list[asyncio.Task[object]] = []
        callback_threads: list[int] = []

        def installer(hass, action, when):
            installed.append((hass, action, when, get_ident()))
            return lambda: cancelled.append(None)

        def submit(callback):
            submitted_tasks.append(asyncio.create_task(executor.async_submit(callback)))

        scheduler = HomeAssistantScheduler(
            hass="hass",
            bridge=HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            submit_runtime_callback=submit,
            timer_installer=installer,
        )
        deadline = NOW + timedelta(minutes=1)
        handle = await executor.async_submit(
            scheduler.schedule_at,
            deadline,
            lambda: callback_threads.append(get_ident()),
        )

        timer_action = installed[0][1]
        timer_action(deadline)
        await asyncio.gather(*submitted_tasks)
        await executor.async_submit(handle.cancel)
        await executor.async_close()
        return installed, cancelled, callback_threads, loop_thread

    installed, cancelled, callback_threads, loop_thread = asyncio.run(scenario())

    assert installed[0][0] == "hass"
    assert installed[0][2] == NOW + timedelta(minutes=1)
    assert installed[0][3] == loop_thread
    assert cancelled == [None]
    assert len(set(callback_threads)) == 1
    assert callback_threads[0] != loop_thread


def test_installation_failure_preserves_original_exception():
    async def scenario():
        executor = HomeAssistantRuntimeExecutor()
        original = RuntimeError("install failed")

        def installer(hass, action, when):
            raise original

        scheduler = HomeAssistantScheduler(
            "hass",
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            lambda callback: None,
            timer_installer=installer,
        )
        with pytest.raises(HomeAssistantSchedulerInstallationError) as raised:
            await executor.async_submit(scheduler.schedule_at, NOW, lambda: None)
        await executor.async_close()
        return raised.value, original

    raised, original = asyncio.run(scenario())

    assert raised.original_error is original
    assert raised.__cause__ is original


def test_cancellation_failure_preserves_original_exception():
    async def scenario():
        executor = HomeAssistantRuntimeExecutor()
        original = RuntimeError("cancel failed")

        def installer(hass, action, when):
            def cancel():
                raise original

            return cancel

        scheduler = HomeAssistantScheduler(
            "hass",
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            lambda callback: None,
            timer_installer=installer,
        )
        handle = await executor.async_submit(scheduler.schedule_at, NOW, lambda: None)
        with pytest.raises(HomeAssistantSchedulerCancellationError) as raised:
            await executor.async_submit(handle.cancel)
        await executor.async_close()
        return raised.value, original

    raised, original = asyncio.run(scenario())

    assert raised.original_error is original
    assert raised.__cause__ is original
