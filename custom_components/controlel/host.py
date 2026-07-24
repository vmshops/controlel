"""Home Assistant lifecycle and serialized ControlRuntime ownership."""

import asyncio
import logging
from collections import deque
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationResult,
    HeatDemandEvaluationStatus,
)
from controlel.application.runtime.runtime_lifecycle import (
    RuntimeReentrancyError,
    RuntimeStoppedError,
)
from controlel.application.runtime.runtime_processing_result import (
    RuntimeProcessingResult,
    RuntimeProcessingStatus,
)

from .failure_sink import HomeAssistantScheduledFailureSink
from .heat_source import HomeAssistantServiceCallError
from .measurement_ingestion import (
    HomeAssistantMeasurementMapper,
    StateLike,
    StateVersion,
)
from .runtime_executor import (
    HomeAssistantRuntimeExecutor,
    RuntimeExecutorClosedError,
)

type Unsubscribe = Callable[[], None]
type StateListener = Callable[[StateLike | None], None]
type StateSubscriber = Callable[[object, str, StateListener], Unsubscribe]
type StateGetter = Callable[[str], StateLike | None]
type ShutdownSubscriber = Callable[[object, Callable[[], None]], Unsubscribe]


class HomeAssistantTaskOwner(Protocol):
    def async_create_task(
        self,
        target: Coroutine[Any, Any, Any],
        name: str | None = None,
    ) -> asyncio.Task[Any]: ...


class HomeAssistantControlelHost:
    """Own one runtime and every path by which Home Assistant can enter it."""

    def __init__(
        self,
        hass: HomeAssistantTaskOwner,
        runtime: ControlRuntime,
        executor: HomeAssistantRuntimeExecutor,
        measurement_mapper: HomeAssistantMeasurementMapper,
        failure_sink: HomeAssistantScheduledFailureSink,
        temperature_entity_id: str,
        logger: logging.Logger,
        state_subscriber: StateSubscriber | None = None,
        state_getter: StateGetter | None = None,
        shutdown_subscriber: ShutdownSubscriber | None = None,
    ) -> None:
        self._hass = hass
        self._runtime = runtime
        self._executor = executor
        self._measurement_mapper = measurement_mapper
        self._failure_sink = failure_sink
        self._temperature_entity_id = temperature_entity_id
        self._logger = logger
        self._state_subscriber = state_subscriber or _default_state_subscriber
        self._state_getter = state_getter or self._default_state_getter
        self._shutdown_subscriber = shutdown_subscriber or _default_shutdown_subscriber

        self._lifecycle_lock = asyncio.Lock()
        self._buffer: deque[StateLike | None] = deque()
        self._live_queue: deque[StateLike | None] = deque()
        self._unsubscribe: Unsubscribe | None = None
        self._unsubscribe_shutdown: Unsubscribe | None = None
        self._live_drain_task: asyncio.Task[Any] | None = None
        self._accepted_callback_tasks: set[asyncio.Task[Any]] = set()
        self._fatal_shutdown_task: asyncio.Task[Any] | None = None
        self._fatal_error: Exception | None = None
        self._last_state_version: StateVersion | None = None
        self._accepting = True
        self._buffering = True
        self._initialized = False
        self._stopping = False
        self._stopped = False

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def stopped(self) -> bool:
        return self._stopped

    async def async_initialize(self) -> None:
        async with self._lifecycle_lock:
            if self._initialized:
                raise RuntimeError("Controlel host is already initialized")
            if self._stopping or self._stopped:
                raise RuntimeError("Controlel host cannot initialize after shutdown")

            self._unsubscribe = self._state_subscriber(
                self._hass,
                self._temperature_entity_id,
                self._on_state_change,
            )
            self._unsubscribe_shutdown = self._shutdown_subscriber(
                self._hass,
                self._on_home_assistant_stop,
            )
            snapshot = self._state_getter(self._temperature_entity_id)

            await self._async_process_state_now(snapshot)
            await self._async_drain_setup_buffer()

            try:
                startup_result = await self._executor.async_submit(self._runtime.start)
            except HomeAssistantServiceCallError as error:
                self._handle_synchronous_failure(error)
            except Exception as error:
                self._handle_synchronous_failure(error)
                raise
            else:
                self._log_evaluation_result(startup_result)

            await self._async_drain_setup_buffer()
            if self._fatal_error is not None:
                raise self._fatal_error
            self._buffering = False
            self._initialized = True
            self._failure_sink.clear_fatal_issue_after_successful_reload()

    async def async_process_state(
        self,
        state: StateLike | None,
    ) -> RuntimeProcessingResult | None:
        if not self._accepting:
            return None
        if self._buffering:
            self._buffer.append(state)
            return None
        return await self._async_process_state_now(state)

    async def async_reevaluate(self) -> HeatDemandEvaluationResult:
        if not self._accepting:
            raise RuntimeStoppedError("Controlel host is not accepting work")
        try:
            result = await self._executor.async_submit(self._runtime.reevaluate_heat_demand)
        except Exception as error:
            self._handle_synchronous_failure(error)
            raise
        self._log_evaluation_result(result)
        return result

    def submit_scheduled_callback(
        self,
        callback: Callable[[], None],
    ) -> None:
        """Accept a timer callback on the HA loop without running core code there."""
        if not self._accepting:
            return
        task = self._create_task(
            self._async_run_scheduled_callback(callback),
            "Controlel scheduled runtime callback",
        )
        self._accepted_callback_tasks.add(task)
        task.add_done_callback(self._accepted_callback_tasks.discard)

    def request_fatal_shutdown(self, error: Exception) -> None:
        """Coordinate terminal shutdown on the HA loop after a fatal failure."""
        if self._stopping or self._stopped:
            return
        self._logger.error(
            "Stopping Controlel after fatal runtime failure",
            exc_info=(type(error), error, error.__traceback__),
        )
        self._accepting = False
        self._fatal_error = error
        if not self._initialized:
            return
        self._fatal_shutdown_task = self._create_task(
            self.async_stop(),
            "Controlel fatal runtime shutdown",
        )

    async def async_stop(self) -> None:
        async with self._lifecycle_lock:
            if self._stopped:
                return
            self._stopping = True
            self._accepting = False

            unsubscribe = self._unsubscribe
            self._unsubscribe = None
            if unsubscribe is not None:
                try:
                    unsubscribe()
                except Exception:
                    self._logger.exception("Failed to unsubscribe Controlel state listener")

            unsubscribe_shutdown = self._unsubscribe_shutdown
            self._unsubscribe_shutdown = None
            if unsubscribe_shutdown is not None:
                try:
                    unsubscribe_shutdown()
                except Exception:
                    self._logger.exception("Failed to unsubscribe Controlel shutdown listener")

            drain_task = self._live_drain_task
            if drain_task is not None and drain_task is not asyncio.current_task():
                await asyncio.gather(drain_task, return_exceptions=True)

            callback_tasks = [task for task in self._accepted_callback_tasks if task is not asyncio.current_task()]
            if callback_tasks:
                await asyncio.gather(*callback_tasks, return_exceptions=True)

            if not self._executor.closed:
                try:
                    await self._executor.async_submit(self._runtime.stop)
                except RuntimeExecutorClosedError:
                    pass
                except Exception as error:
                    self._logger.exception("Controlel runtime stop failed; continuing cleanup")
                    self._failure_sink.handle_synchronous_failure(error)
                finally:
                    await self._executor.async_close()

            self._buffer.clear()
            self._live_queue.clear()
            self._buffering = False
            self._stopping = False
            self._stopped = True

    def clear_transient_issues(self) -> None:
        self._failure_sink.clear_transient_issues()

    def _on_state_change(self, state: StateLike | None) -> None:
        if not self._accepting:
            return
        if self._buffering:
            self._buffer.append(state)
            return

        self._live_queue.append(state)
        if self._live_drain_task is None or self._live_drain_task.done():
            self._live_drain_task = self._create_task(
                self._async_drain_live_queue(),
                "Controlel temperature state processing",
            )

    def _on_home_assistant_stop(self) -> None:
        if self._stopping or self._stopped:
            return
        self._create_task(
            self.async_stop(),
            "Controlel Home Assistant shutdown",
        )

    async def _async_drain_setup_buffer(self) -> None:
        while self._buffer:
            await self._async_process_state_now(self._buffer.popleft())

    async def _async_drain_live_queue(self) -> None:
        while self._live_queue:
            await self._async_process_state_now(self._live_queue.popleft())

    async def _async_process_state_now(
        self,
        state: StateLike | None,
    ) -> RuntimeProcessingResult | None:
        version = self._measurement_mapper.state_version(state)
        if version is not None and version == self._last_state_version:
            self._logger.debug("Discarded exact duplicate Controlel state version")
            return None
        self._last_state_version = version

        mapping = self._measurement_mapper.map_state(state)
        if mapping.measurement is None:
            self._logger.debug(
                "Rejected Home Assistant temperature state: %s",
                mapping.rejection_reason,
            )
            return None

        try:
            result = await self._executor.async_submit(
                self._runtime.process_temperature,
                mapping.measurement,
            )
        except RuntimeStoppedError as error:
            if self._stopping or self._stopped:
                self._logger.debug("Ignored temperature state during Controlel shutdown")
                return None
            self._handle_synchronous_failure(error)
            raise
        except Exception as error:
            self._handle_synchronous_failure(error)
            if isinstance(error, HomeAssistantServiceCallError):
                return None
            raise

        self._log_processing_result(result)
        return result

    async def _async_run_scheduled_callback(
        self,
        callback: Callable[[], None],
    ) -> None:
        if not self._accepting:
            return
        try:
            await self._executor.async_submit(callback)
        except RuntimeExecutorClosedError:
            if not self._stopping and not self._stopped:
                raise

    def _handle_synchronous_failure(self, error: Exception) -> None:
        self._failure_sink.handle_synchronous_failure(error)
        if isinstance(error, HomeAssistantServiceCallError):
            return
        if isinstance(error, RuntimeStoppedError) and (self._stopping or self._stopped):
            return
        if isinstance(error, RuntimeReentrancyError):
            self.request_fatal_shutdown(error)

    def _log_processing_result(self, result: RuntimeProcessingResult) -> None:
        if result.status is RuntimeProcessingStatus.NO_DECISION:
            self._logger.debug("Controlel made no decision: %s", result.reason)
        elif result.status is RuntimeProcessingStatus.BUILDING_HEAT_DEMAND_INDETERMINATE:
            self._logger.info("Controlel heat demand is indeterminate and within grace")
        elif result.status is RuntimeProcessingStatus.COMMAND_SUPPRESSED:
            self._logger.debug("Controlel suppressed an already-applied demand command")
        elif result.status is RuntimeProcessingStatus.COMMAND_EXECUTED:
            self._logger.info("Controlel executed a heat-demand command")
        elif result.status is RuntimeProcessingStatus.SAFETY_COMMAND_SUPPRESSED:
            self._logger.info("Controlel suppressed an already-applied safety command")
        elif result.status is RuntimeProcessingStatus.SAFETY_COMMAND_EXECUTED:
            self._logger.warning("Controlel executed the configured safety command")
        else:
            self._logger.debug("Controlel processing result: %s", result.status)

    def _log_evaluation_result(self, result: HeatDemandEvaluationResult) -> None:
        if result.status is HeatDemandEvaluationStatus.INDETERMINATE_GRACE:
            self._logger.info(
                "Controlel heat demand is indeterminate; next evaluation at %s",
                result.next_evaluation_at,
            )
        elif result.status is HeatDemandEvaluationStatus.DEMAND_COMMAND_SUPPRESSED:
            self._logger.debug("Controlel suppressed an already-applied demand command")
        elif result.status is HeatDemandEvaluationStatus.DEMAND_COMMAND_EXECUTED:
            self._logger.info("Controlel executed a heat-demand command")
        elif result.status is HeatDemandEvaluationStatus.SAFETY_COMMAND_SUPPRESSED:
            self._logger.info("Controlel suppressed an already-applied safety command")
        elif result.status is HeatDemandEvaluationStatus.SAFETY_COMMAND_EXECUTED:
            self._logger.warning("Controlel executed the configured safety command")

    def _default_state_getter(self, entity_id: str) -> StateLike | None:
        states = getattr(self._hass, "states")
        return states.get(entity_id)

    def _create_task(
        self,
        coroutine: Coroutine[Any, Any, Any],
        name: str,
    ) -> asyncio.Task[Any]:
        return self._hass.async_create_task(coroutine, name=name)


def _default_state_subscriber(
    hass: object,
    entity_id: str,
    listener: StateListener,
) -> Unsubscribe:
    from homeassistant.core import callback
    from homeassistant.helpers.event import async_track_state_change_event

    @callback
    def on_event(event: Any) -> None:
        listener(event.data["new_state"])

    return async_track_state_change_event(hass, entity_id, on_event)


def _default_shutdown_subscriber(
    hass: object,
    listener: Callable[[], None],
) -> Unsubscribe:
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    from homeassistant.core import callback

    @callback
    def on_stop(_: Any) -> None:
        listener()

    return hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_stop)
