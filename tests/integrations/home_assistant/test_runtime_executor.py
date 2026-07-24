import asyncio
from threading import get_ident
from time import sleep

import pytest

from custom_components.controlel.runtime_executor import (
    HomeAssistantRuntimeExecutor,
    RuntimeExecutorClosedError,
)


def test_uses_one_worker_preserves_order_and_never_runs_on_event_loop():
    async def scenario():
        executor = HomeAssistantRuntimeExecutor()
        event_loop_thread = get_ident()
        order: list[int] = []
        worker_threads: list[int] = []

        def operation(value: int) -> int:
            order.append(value)
            worker_threads.append(get_ident())
            sleep(0.01)
            return value

        results = await asyncio.gather(
            executor.async_submit(operation, 1),
            executor.async_submit(operation, 2),
            executor.async_submit(operation, 3),
        )
        await executor.async_close()
        return results, order, worker_threads, event_loop_thread

    results, order, worker_threads, event_loop_thread = asyncio.run(scenario())

    assert results == [1, 2, 3]
    assert order == [1, 2, 3]
    assert len(set(worker_threads)) == 1
    assert worker_threads[0] != event_loop_thread


def test_event_loop_remains_responsive_during_runtime_work():
    async def scenario():
        executor = HomeAssistantRuntimeExecutor()
        heartbeat = False

        async def mark_heartbeat():
            nonlocal heartbeat
            await asyncio.sleep(0.005)
            heartbeat = True

        task = asyncio.create_task(mark_heartbeat())
        await executor.async_submit(sleep, 0.03)
        await task
        await executor.async_close()
        return heartbeat

    assert asyncio.run(scenario()) is True


def test_close_is_idempotent_and_rejects_late_submission():
    async def scenario():
        executor = HomeAssistantRuntimeExecutor()
        await executor.async_close()
        await executor.async_close()
        with pytest.raises(RuntimeExecutorClosedError):
            await executor.async_submit(lambda: None)

    asyncio.run(scenario())
