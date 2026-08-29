"""Home Assistant lifecycle and serialized WaterSafetyRuntime ownership."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, Protocol

from controlel.application.configuration.water_safety_setup_adapter import (
    WATER_SAFETY_SENSOR_ROLE,
    WaterSafetySetupPayload,
)
from controlel.application.services.water_safety_projector import WaterSafetyDiagnosticsProjector
from controlel.application.setup import EffectiveRuntimeConfiguration
from controlel.application.setup.json_data import canonical_json
from controlel.application.state.water_safety_diagnostics import WaterSafetyDiagnosticsSnapshotV1
from controlel.application.water_safety import (
    WaterOutputAction,
    WaterOutputCommand,
    WaterOutputKind,
    WaterOutputOwner,
    WaterSafetyProcessingResult,
    WaterSafetyRuntime,
)
from controlel.domain.water_safety import MoistureCondition, WaterSafetyState

from .runtime_executor import HomeAssistantRuntimeExecutor, RuntimeExecutorClosedError
from .scheduler import HomeAssistantScheduler
from .water_safety_moisture import HomeAssistantMoistureMapper, MoistureMappingRejectionReason, StateLike
from .water_safety_output import HomeAssistantWaterSafetyOutputPort
from .water_safety_persistence import (
    HomeAssistantWaterSafetyEvidenceStore,
    HomeAssistantWaterSafetyStateStore,
)

type Unsubscribe = Callable[[], None]
type StateListener = Callable[[StateLike | None, StateLike | None], None]
type StateSubscriber = Callable[[object, str, StateListener], Unsubscribe]
type StateGetter = Callable[[str], StateLike | None]


class HomeAssistantTaskOwner(Protocol):
    def async_create_task(
        self,
        target: Coroutine[Any, Any, Any],
        name: str | None = None,
    ) -> asyncio.Task[Any]: ...


class HomeAssistantWaterSafetyHost:
    """Own one Water Safety runtime and every Home Assistant entry path into it."""

    def __init__(
        self,
        hass: HomeAssistantTaskOwner,
        runtime: WaterSafetyRuntime,
        effective: EffectiveRuntimeConfiguration,
        executor: HomeAssistantRuntimeExecutor,
        mapper: HomeAssistantMoistureMapper,
        output_port: HomeAssistantWaterSafetyOutputPort,
        scheduler: HomeAssistantScheduler,
        *,
        logger: logging.Logger,
        state_subscriber: StateSubscriber | None = None,
        state_getter: StateGetter | None = None,
        projector: WaterSafetyDiagnosticsProjector | None = None,
    ) -> None:
        self._hass = hass
        self._runtime = runtime
        self._effective = effective
        self._executor = executor
        self._mapper = mapper
        self._output_port = output_port
        self._scheduler = scheduler
        self._logger = logger
        self._state_subscriber = state_subscriber or _default_state_subscriber
        self._state_getter = state_getter or _default_state_getter(hass)
        self._projector = projector or WaterSafetyDiagnosticsProjector()
        self._config = WaterSafetySetupPayload.model_validate_json(canonical_json(effective.module_payload))
        self._owner = WaterOutputOwner(
            environment_id=effective.environment_id,
            module_key=effective.module_key,
            module_instance_id=effective.module_instance_id,
        )
        self._bindings = {binding.role: binding.reference for binding in effective.bindings}
        self._lifecycle_lock = asyncio.Lock()
        self._unsubscribe: Unsubscribe | None = None
        self._deadline_handle: object | None = None
        self._callback_tasks: set[asyncio.Task[Any]] = set()
        self._accepting = True
        self._initialized = False
        self._stopping = False
        self._stopped = False
        self._diagnostics_snapshot: WaterSafetyDiagnosticsSnapshotV1 | None = None

    @property
    def runtime(self) -> WaterSafetyRuntime:
        return self._runtime

    @property
    def frontend_api_water_safety_evidence(self) -> WaterSafetyDiagnosticsSnapshotV1:
        if self._diagnostics_snapshot is None:
            raise RuntimeError("Water Safety diagnostics are unavailable before initialization")
        return self._diagnostics_snapshot

    async def async_initialize(self) -> None:
        async with self._lifecycle_lock:
            if self._initialized:
                raise RuntimeError("Water Safety host is already initialized")
            if self._stopping or self._stopped:
                raise RuntimeError("Water Safety host cannot initialize after shutdown")

            snapshot = self._state_getter(self._mapper.entity_id)
            observation = self._require_observation(snapshot)
            started_at = datetime.now(UTC)
            await self._async_submit_runtime(self._runtime.start, observation, started_at=started_at)
            self._refresh_diagnostics()
            self._reschedule_deadline()

            self._unsubscribe = self._state_subscriber(
                self._hass,
                self._mapper.entity_id,
                self._on_state_change,
            )
            self._initialized = True
            self._logger.info("Water Safety runtime started")

    async def async_stop(self) -> None:
        async with self._lifecycle_lock:
            if self._stopped:
                return
            self._accepting = False
            self._stopping = True
            unsubscribe = self._unsubscribe
            self._unsubscribe = None
            if unsubscribe is not None:
                unsubscribe()
            self._cancel_deadline()
            try:
                self._scheduler.cancel_all()
            except Exception:
                self._logger.exception("Water Safety scheduler cleanup failed")
            callback_tasks = [task for task in self._callback_tasks if task is not asyncio.current_task()]
            if callback_tasks:
                await asyncio.gather(*callback_tasks, return_exceptions=True)
            if not self._executor.closed:
                await self._executor.async_close()
            self._stopping = False
            self._stopped = True
            self._logger.info("Water Safety runtime stopped")

    async def silence(self) -> WaterSafetyProcessingResult:
        return await self._process(lambda: self._runtime.silence(silenced_at=datetime.now(UTC)))

    async def disable(self) -> WaterSafetyProcessingResult:
        return await self._process(lambda: self._runtime.disable(disabled_at=datetime.now(UTC)))

    async def enable(self) -> WaterSafetyProcessingResult:
        snapshot = self._state_getter(self._mapper.entity_id)
        observation = self._require_observation(snapshot)
        return await self._process(
            lambda: self._runtime.enable(observation, enabled_at=datetime.now(UTC)),
        )

    async def test_notification(self) -> WaterSafetyProcessingResult:
        self._require_safe_test()
        role = self._config.notification_target_roles[0]
        command = WaterOutputCommand(
            command_id=f"{self._effective.module_instance_id}:test:notification",
            requested_at=datetime.now(UTC),
            owner=self._owner,
            output_kind=WaterOutputKind.NOTIFICATION,
            action=WaterOutputAction.NOTIFY_WET,
            target_role=role,
            target=self._bindings[role],
            message_code="water_safety.wet",
            custom_message=None,
            repeated=False,
        )
        result = await self._async_submit_runtime(self._output_port.request, command)
        return WaterSafetyProcessingResult(
            previous_state=self._runtime.state,
            state=self._runtime.state,
            snapshot=self._runtime.snapshot,
            output_results=(result,),
        )

    async def test_siren(self) -> WaterSafetyProcessingResult:
        self._require_safe_test()
        if not self._config.siren_target_roles:
            raise RuntimeError("Water Safety has no configured siren targets")
        role = self._config.siren_target_roles[0]
        command = WaterOutputCommand(
            command_id=f"{self._effective.module_instance_id}:test:siren",
            requested_at=datetime.now(UTC),
            owner=self._owner,
            output_kind=WaterOutputKind.SIREN,
            action=WaterOutputAction.REQUEST_SIREN_ON,
            target_role=role,
            target=self._bindings[role],
        )
        result = await self._async_submit_runtime(self._output_port.request, command)
        return WaterSafetyProcessingResult(
            previous_state=self._runtime.state,
            state=self._runtime.state,
            snapshot=self._runtime.snapshot,
            output_results=(result,),
        )

    async def async_frontend_api_water_safety_action(self, action: str) -> dict[str, object]:
        handlers = {
            "silence": self.silence,
            "disable": self.disable,
            "enable": self.enable,
            "test_notification": self.test_notification,
            "test_siren": self.test_siren,
        }
        handler = handlers.get(action)
        if handler is None:
            raise ValueError(f"unsupported water safety action: {action}")
        result = await handler()
        return {
            "state": result.state.value,
            "assessment_status": result.assessment_status.value,
        }

    def submit_scheduled_callback(self, callback: Callable[[], None]) -> None:
        if not self._accepting:
            return
        task = self._hass.async_create_task(
            self._async_run_scheduled_callback(callback),
            "Controlel Water Safety scheduled runtime callback",
        )
        self._callback_tasks.add(task)
        task.add_done_callback(self._callback_tasks.discard)

    def _on_state_change(
        self,
        state: StateLike | None,
        previous_state: StateLike | None = None,
    ) -> None:
        del previous_state
        if not self._accepting or self._stopping:
            return
        task = self._hass.async_create_task(
            self._async_process_state(state),
            "Controlel Water Safety state change",
        )
        self._callback_tasks.add(task)
        task.add_done_callback(self._callback_tasks.discard)

    async def _async_process_state(self, state: StateLike | None) -> None:
        mapping = self._mapper.map_state(state)
        if mapping.observation is None:
            if mapping.rejection_reason in {
                MoistureMappingRejectionReason.MISSING_STATE,
                MoistureMappingRejectionReason.MISSING_TIMESTAMP,
                MoistureMappingRejectionReason.NAIVE_TIMESTAMP,
            }:
                return
            observation = self._unknown_observation()
        else:
            observation = mapping.observation
        await self._process(lambda: self._runtime.observe(observation))

    async def _async_run_scheduled_callback(self, callback: Callable[[], None]) -> None:
        if not self._accepting:
            return
        try:
            await self._async_submit_runtime(callback)
        except RuntimeExecutorClosedError:
            if not self._stopping and not self._stopped:
                raise

    async def _process(self, operation: Callable[[], WaterSafetyProcessingResult]) -> WaterSafetyProcessingResult:
        result = await self._async_submit_runtime(operation)
        self._refresh_diagnostics()
        self._reschedule_deadline()
        return result

    async def _async_submit_runtime(self, operation: Callable[..., Any], *args: object) -> Any:
        return await self._executor.async_submit(operation, *args)

    def _reschedule_deadline(self) -> None:
        self._cancel_deadline()
        deadline = self._runtime.next_deadline
        if deadline is None:
            return
        self._deadline_handle = self._scheduler.schedule_at(deadline, self._on_deadline)

    def _cancel_deadline(self) -> None:
        if self._deadline_handle is not None:
            cancel = getattr(self._deadline_handle, "cancel", None)
            if callable(cancel):
                cancel()
            self._deadline_handle = None

    def _on_deadline(self) -> None:
        async def async_tick() -> None:
            await self._process(lambda: self._runtime.tick(datetime.now(UTC)))

        task = self._hass.async_create_task(async_tick(), "Controlel Water Safety deadline tick")
        self._callback_tasks.add(task)
        task.add_done_callback(self._callback_tasks.discard)

    def _refresh_diagnostics(self) -> None:
        self._diagnostics_snapshot = self._projector.project(
            self._runtime.diagnostics(),
            area_name=self._config.area_name,
            zone_name=self._config.zone_name,
        )

    def _require_safe_test(self) -> None:
        state = self._runtime.state
        if state is WaterSafetyState.WET:
            raise RuntimeError("Water Safety test actions are not allowed while WET")
        if state is WaterSafetyState.DISABLED or not self._runtime.snapshot.processing_enabled:
            raise RuntimeError("Water Safety test actions are not allowed while disabled")

    def _require_observation(self, state: StateLike | None):
        mapping = self._mapper.map_state(state)
        if mapping.observation is not None:
            return mapping.observation
        if mapping.rejection_reason in {
            MoistureMappingRejectionReason.MISSING_STATE,
            MoistureMappingRejectionReason.MISSING_TIMESTAMP,
            MoistureMappingRejectionReason.NAIVE_TIMESTAMP,
        }:
            return self._unknown_observation()
        raise RuntimeError(f"cannot start Water Safety from moisture state: {mapping.rejection_reason}")

    def _unknown_observation(self):
        from controlel.domain.water_safety import MoistureObservation

        return MoistureObservation(
            sensor_id=self._config.sensor_id,
            condition=MoistureCondition.UNKNOWN,
            observed_at=datetime.now(UTC),
            provider_state=None,
        )


def build_water_safety_host(
    hass: HomeAssistantTaskOwner,
    effective: EffectiveRuntimeConfiguration,
    *,
    bridge: object,
    scheduler: HomeAssistantScheduler,
    state_store: HomeAssistantWaterSafetyStateStore,
    evidence_store: HomeAssistantWaterSafetyEvidenceStore,
    logger: logging.Logger,
    restored_snapshot: object | None = None,
) -> HomeAssistantWaterSafetyHost:
    from .event_loop_bridge import HomeAssistantEventLoopBridge

    if not isinstance(bridge, HomeAssistantEventLoopBridge):
        raise TypeError("bridge must be a HomeAssistantEventLoopBridge")
    sensor_binding = next(binding for binding in effective.bindings if binding.role == WATER_SAFETY_SENSOR_ROLE)
    mapper = HomeAssistantMoistureMapper(
        sensor_id=WaterSafetySetupPayload.model_validate_json(canonical_json(effective.module_payload)).sensor_id,
        binding=sensor_binding.reference,
    )
    output_port = HomeAssistantWaterSafetyOutputPort(hass, bridge)
    runtime = WaterSafetyRuntime(
        effective,
        output_port,
        state_port=state_store,
        evidence_port=evidence_store,
        restored_snapshot=restored_snapshot,
    )
    return HomeAssistantWaterSafetyHost(
        hass=hass,
        runtime=runtime,
        effective=effective,
        executor=HomeAssistantRuntimeExecutor(),
        mapper=mapper,
        output_port=output_port,
        scheduler=scheduler,
        logger=logger,
    )


def _default_state_subscriber(hass: object, entity_id: str, listener: StateListener) -> Unsubscribe:
    from homeassistant.core import callback
    from homeassistant.helpers.event import async_track_state_change_event

    @callback
    def on_state_event(event: Any) -> None:
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        listener(new_state, old_state)

    return async_track_state_change_event(hass, entity_id, on_state_event)


def _default_state_getter(hass: object) -> StateGetter:
    def getter(entity_id: str) -> StateLike | None:
        return getattr(hass, "states").get(entity_id)

    return getter
