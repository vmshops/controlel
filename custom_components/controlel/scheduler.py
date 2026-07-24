"""Home Assistant one-shot scheduler adapter."""

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock

from controlel.application.ports.scheduler import ScheduledTaskHandle

from .event_loop_bridge import HomeAssistantEventLoopBridge

type TimerCancel = Callable[[], None]
type TimerInstaller = Callable[[object, Callable[[datetime], None], datetime], TimerCancel]
type RuntimeCallbackSubmitter = Callable[[Callable[[], None]], None]


class HomeAssistantSchedulerInstallationError(RuntimeError):
    def __init__(self, when: datetime, original_error: Exception) -> None:
        self.when = when
        self.original_error = original_error
        super().__init__(f"Could not install Controlel timer for {when.isoformat()}: {original_error}")


class HomeAssistantSchedulerCancellationError(RuntimeError):
    def __init__(self, original_error: Exception) -> None:
        self.original_error = original_error
        super().__init__(f"Could not cancel Controlel timer: {original_error}")


class _HomeAssistantScheduledTaskHandle(ScheduledTaskHandle):
    def __init__(
        self,
        bridge: HomeAssistantEventLoopBridge,
        cancel_callback: TimerCancel,
    ) -> None:
        self._bridge = bridge
        self._cancel_callback = cancel_callback
        self._state_lock = Lock()
        self._cancelled = False

    def cancel(self) -> None:
        with self._state_lock:
            if self._cancelled:
                return

            async def async_cancel() -> None:
                self._cancel_callback()

            try:
                self._bridge.run_coroutine(async_cancel)
            except Exception as error:
                raise HomeAssistantSchedulerCancellationError(error) from error
            self._cancelled = True


class HomeAssistantScheduler:
    def __init__(
        self,
        hass: object,
        bridge: HomeAssistantEventLoopBridge,
        submit_runtime_callback: RuntimeCallbackSubmitter,
        timer_installer: TimerInstaller | None = None,
    ) -> None:
        self._hass = hass
        self._bridge = bridge
        self._submit_runtime_callback = submit_runtime_callback
        self._timer_installer = timer_installer or _default_timer_installer

    def schedule_at(
        self,
        when: datetime,
        callback: Callable[[], None],
    ) -> ScheduledTaskHandle:
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("scheduled deadline must be timezone-aware")
        normalized = when.astimezone(UTC)

        async def async_install() -> TimerCancel:
            def on_timer(_: datetime) -> None:
                self._submit_runtime_callback(callback)

            return self._timer_installer(self._hass, on_timer, normalized)

        try:
            cancel_callback = self._bridge.run_coroutine(async_install)
        except Exception as error:
            raise HomeAssistantSchedulerInstallationError(normalized, error) from error
        return _HomeAssistantScheduledTaskHandle(
            bridge=self._bridge,
            cancel_callback=cancel_callback,
        )


def _default_timer_installer(
    hass: object,
    action: Callable[[datetime], None],
    when: datetime,
) -> TimerCancel:
    from homeassistant.core import callback
    from homeassistant.helpers.event import async_track_point_in_utc_time

    @callback
    def on_timer(now: datetime) -> None:
        action(now)

    return async_track_point_in_utc_time(hass, on_timer, when)
