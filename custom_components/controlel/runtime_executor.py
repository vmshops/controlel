"""Dedicated serialized execution context for the synchronous core runtime."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TypeVar

T = TypeVar("T")


class RuntimeExecutorClosedError(RuntimeError):
    """Raised when work is submitted after executor shutdown begins."""


class HomeAssistantRuntimeExecutor:
    """Own exactly one worker for every synchronous ControlRuntime operation."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="controlel-runtime",
        )
        self._submission_lock = asyncio.Lock()
        self._closing = False
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def async_submit(
        self,
        operation: Callable[..., T],
        *args: object,
    ) -> T:
        if self._closing:
            raise RuntimeExecutorClosedError("Controlel runtime executor is closing")

        async with self._submission_lock:
            if self._closing:
                raise RuntimeExecutorClosedError("Controlel runtime executor is closing")
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                self._executor,
                partial(operation, *args),
            )

    async def async_close(self) -> None:
        if self._closed:
            return

        self._closing = True
        async with self._submission_lock:
            if self._closed:
                return
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                partial(self._executor.shutdown, wait=True, cancel_futures=False),
            )
            self._closed = True
