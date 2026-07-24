"""The single explicit bridge from the runtime worker to Home Assistant's loop."""

import asyncio
from collections.abc import Callable, Coroutine
from threading import get_ident
from typing import Any, TypeVar

T = TypeVar("T")


class EventLoopBridgeThreadError(RuntimeError):
    """Raised when a blocking bridge call is attempted on the event-loop thread."""


class HomeAssistantEventLoopBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._event_loop_thread_id = get_ident()

    def run_coroutine(
        self,
        coroutine_factory: Callable[[], Coroutine[Any, Any, T]],
    ) -> T:
        if get_ident() == self._event_loop_thread_id:
            raise EventLoopBridgeThreadError("Blocking event-loop bridge cannot run on the Home Assistant event loop")
        future = asyncio.run_coroutine_threadsafe(coroutine_factory(), self._loop)
        return future.result()

    def call_soon(
        self,
        callback: Callable[..., None],
        *args: object,
    ) -> None:
        self._loop.call_soon_threadsafe(callback, *args)
