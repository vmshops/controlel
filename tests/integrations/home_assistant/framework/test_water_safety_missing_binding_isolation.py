"""P0 regression: missing Water Safety notification bindings must not kill the entry."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.helpers import entity_registry as er

from controlel.application.configuration.water_safety_setup_adapter import (
    DEFAULT_NOTIFICATION_ROLE,
    WATER_SAFETY_SENSOR_ROLE,
)
from controlel.application.runtime.heat_demand_evaluation_result import (
    HeatDemandEvaluationResult,
    HeatDemandEvaluationTrigger,
)
from controlel.application.water_safety import WaterOutputOutcome
from controlel.domain.water_safety import WaterSafetyState
from controlel.infrastructure.home_assistant import active_reference_for_module
from custom_components.controlel import config_flow as cf
from custom_components.controlel import water_safety_activation as activation
from custom_components.controlel import water_safety_host as water_host_module
from custom_components.controlel.diagnostics import async_get_config_entry_diagnostics
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.lifecycle_diagnostics import lifecycle_failures_for_entry
from custom_components.controlel.water_safety_lifecycle import (
    WATER_SAFETY_LIFECYCLE_OWNERS_KEY,
    water_safety_lifecycle_owner,
)

from .test_config_flow import (
    _activate_new_heating,
    _activate_new_water,
    _activate_water_draft,
    _choose,
    _defaults,
    _empty_entry,
    _open_water_menu,
    _register_notify_targets,
    _register_water_candidates,
    _water_drafts,
)
from .test_water_safety_output import _notification_command, _spy_output_port_ha_dispatch
from .test_water_safety_release_blockers import SENSOR, _active_entry, _host


async def _reload_loaded(hass, entry) -> None:
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED


def _spy_ha_service_dispatch(port) -> list[tuple[str, str]]:
    return _spy_output_port_ha_dispatch(port)


def _frontend_water_module(hass, entry):
    registry = hass.data["controlel_frontend_api_v1_registry"]
    overview = registry.get(entry.entry_id).overview()
    return next(module for module in overview.modules if module.module_id == "water_safety")


async def _activate_heating_and_water_with_notification(hass, *, title: str, notify_name: str, platform: str):
    utility, _garage, moisture, _outside, _unrelated = _register_water_candidates(hass)
    (phone,) = _register_notify_targets(hass, notify_name)
    hass.states.async_set(moisture, "off")
    entry = await _empty_entry(hass, title=title)
    heating = await _activate_new_heating(hass, entry, platform=platform)
    water = await _open_water_menu(hass, entry)
    area = await _choose(hass, water, "water_safety_area_sensor")
    water = await hass.config_entries.options.async_configure(
        area["flow_id"],
        {
            cf.WATER_AREA: utility.id,
            cf.WATER_MOISTURE_SENSOR: moisture,
            cf.WATER_SHOW_ALL_COMPATIBLE: False,
        },
    )
    notifications = await _choose(hass, water, "water_safety_notifications")
    water = await hass.config_entries.options.async_configure(
        notifications["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [phone], cf.WATER_TEST_NOTIFICATION: False},
    )
    activated = await _activate_water_draft(hass, water)
    assert activated["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.runtime_data.host is not None
    assert entry.runtime_data.water_safety_host is not None
    assert active_reference_for_module(entry.data, "heating") is not None
    assert active_reference_for_module(entry.data, "heating").canonical_revision_id == heating.canonical_revision_id
    return entry, moisture, phone


@pytest.mark.asyncio
async def test_missing_notification_binding_starts_water_safety_degraded(hass, monkeypatch, caplog):
    entry, _canonical = await _active_entry(hass, monkeypatch)
    hass.services.async_remove("notify", "mobile_app_phone")
    service = activation.WaterSafetyActivationService()
    host = await service.async_start_from_active_reference(
        hass,
        entry,
        bridge=HomeAssistantEventLoopBridge(hass.loop),
    )
    try:
        assert host is not None
        assert host.runtime.state is WaterSafetyState.OK
        assert host.degraded_notification_bindings
        assert all(status == "MISSING" for status in host.degraded_notification_bindings.values())
        assert all(role.startswith("water_safety.notification.") for role in host.degraded_notification_bindings)
        assert host._config.notification_target_roles == ()
        assert not any(role.startswith("water_safety.notification.") for role in host._bindings)
        assert "notification binding" in caplog.text
        assert "MISSING" in caplog.text
    finally:
        await host.async_stop()


@pytest.mark.asyncio
async def test_missing_moisture_binding_still_fails_water_safety_start(hass, monkeypatch):
    entry, _canonical = await _active_entry(hass, monkeypatch)
    er.async_get(hass).async_remove(SENSOR)
    service = activation.WaterSafetyActivationService()
    build = AsyncMock()
    monkeypatch.setattr(service, "_async_build_and_start_host", build)
    with pytest.raises(ValueError, match=f"{WATER_SAFETY_SENSOR_ROLE}.*MISSING"):
        await service.async_start_from_active_reference(
            hass,
            entry,
            bridge=HomeAssistantEventLoopBridge(hass.loop),
        )
    build.assert_not_awaited()


@pytest.mark.asyncio
async def test_heating_and_water_entry_loads_when_notification_primary_is_missing(hass) -> None:
    entry, _moisture, phone = await _activate_heating_and_water_with_notification(
        hass,
        title="Missing notify isolation",
        notify_name="missing_notify_isolation",
        platform="missing-notify-isolation",
    )
    service = phone.removeprefix("notify.")
    hass.services.async_remove("notify", service)
    await _reload_loaded(hass, entry)

    assert entry.runtime_data.host is not None
    water_host = entry.runtime_data.water_safety_host
    assert water_host is not None
    assert water_host.degraded_notification_bindings == {DEFAULT_NOTIFICATION_ROLE: "MISSING"}
    assert entry.runtime_data.water_safety_startup_failure is None
    assert entry.runtime_data.water_safety_degraded_notification_bindings == {DEFAULT_NOTIFICATION_ROLE: "MISSING"}
    readiness = (await async_get_config_entry_diagnostics(hass, entry))["configuration_readiness"]["water_safety"]
    assert readiness["configured"] is True
    assert readiness["runtime_loaded"] is True
    assert readiness["degraded_notification_bindings"] == {DEFAULT_NOTIFICATION_ROLE: "MISSING"}
    assert readiness["startup_failure"] is None


@pytest.mark.asyncio
async def test_moisture_missing_isolates_water_failure_without_killing_heating(hass) -> None:
    entry, moisture, _phone = await _activate_heating_and_water_with_notification(
        hass,
        title="Missing moisture isolation",
        notify_name="moisture_fail_phone",
        platform="missing-moisture-isolation",
    )
    er.async_get(hass).async_remove(moisture)
    hass.states.async_remove(moisture)
    await _reload_loaded(hass, entry)

    assert entry.runtime_data.host is not None
    assert entry.runtime_data.water_safety_host is None
    assert entry.runtime_data.water_safety_startup_failure is not None
    assert WATER_SAFETY_SENSOR_ROLE in entry.runtime_data.water_safety_startup_failure
    assert "MISSING" in entry.runtime_data.water_safety_startup_failure
    failures = lifecycle_failures_for_entry(hass, entry.entry_id)
    assert failures["water_safety_setup"] is not None
    assert failures["setup"] is None

    first_heating_host = entry.runtime_data.host
    assert first_heating_host.accepting is True
    assert first_heating_host.stopped is False
    assert await first_heating_host.async_reevaluate() is not None

    await _reload_loaded(hass, entry)
    assert first_heating_host.stopped is True
    assert first_heating_host._executor.closed is True
    second_heating_host = entry.runtime_data.host
    assert second_heating_host is not None
    assert second_heating_host is not first_heating_host
    assert second_heating_host.accepting is True
    assert await second_heating_host.async_reevaluate() is not None
    assert entry.runtime_data.water_safety_host is None

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert second_heating_host.stopped is True
    assert second_heating_host._executor.closed is True
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.runtime_data.host is not None
    assert entry.runtime_data.host.accepting is True
    assert entry.runtime_data.water_safety_host is None


@pytest.mark.asyncio
async def test_unavailable_notification_requires_explicit_clear_and_activation_recovers(hass) -> None:
    entry, _moisture, phone = await _activate_heating_and_water_with_notification(
        hass,
        title="Notify recovery",
        notify_name="recovery_phone",
        platform="notify-recovery",
    )
    prior = entry.runtime_data.loaded_water_safety_configuration
    assert prior is not None

    service = phone.removeprefix("notify.")
    hass.services.async_remove("notify", service)
    await _reload_loaded(hass, entry)
    assert entry.runtime_data.water_safety_host is not None
    assert entry.runtime_data.water_safety_host.degraded_notification_bindings

    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_notifications")
    assert _defaults(form)[cf.WATER_NOTIFICATION_TARGETS] == [phone]
    assert phone in form["description_placeholders"]["unavailable_notification_targets"]
    rejected = await hass.config_entries.options.async_configure(form["flow_id"], _defaults(form))
    assert rejected["type"] is data_entry_flow.FlowResultType.FORM
    assert rejected["errors"] == {cf.WATER_NOTIFICATION_TARGETS: "invalid_water_notification_targets"}
    assert await _water_drafts(hass, entry) == ()
    assert entry.runtime_data.loaded_water_safety_configuration == prior

    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_notifications")
    saved = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [], cf.WATER_TEST_NOTIFICATION: False},
    )
    draft = (await _water_drafts(hass, entry))[0]
    assert list(draft.settings.get("notification_target_roles", ())) == []
    assert all(not binding.role.startswith("water_safety.notification.") for binding in draft.bindings)

    recovered = await _activate_water_draft(hass, saved)
    assert recovered["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.runtime_data.host is not None
    host = entry.runtime_data.water_safety_host
    assert host is not None
    assert host.degraded_notification_bindings == {}
    assert host._config.notification_target_roles == ()
    assert entry.runtime_data.loaded_water_safety_configuration is not None
    assert entry.runtime_data.loaded_water_safety_configuration.canonical_revision_id != prior.canonical_revision_id

    await _reload_loaded(hass, entry)
    assert entry.runtime_data.water_safety_host is not None
    assert entry.runtime_data.water_safety_host.degraded_notification_bindings == {}
    assert entry.runtime_data.water_safety_startup_failure is None

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.runtime_data.water_safety_host is not None
    assert entry.runtime_data.water_safety_host.degraded_notification_bindings == {}
    assert entry.runtime_data.water_safety_host._config.notification_target_roles == ()


@pytest.mark.asyncio
async def test_unavailable_notification_can_be_explicitly_replaced_and_survives_restart(hass) -> None:
    entry, _moisture, stale = await _activate_heating_and_water_with_notification(
        hass,
        title="Notify replacement",
        notify_name="stale_replacement_phone",
        platform="notify-replacement",
    )
    hass.services.async_remove("notify", stale.removeprefix("notify."))
    (replacement,) = _register_notify_targets(hass, "replacement_phone")
    await _reload_loaded(hass, entry)

    prior = entry.runtime_data.loaded_water_safety_configuration
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_notifications")
    assert _defaults(form)[cf.WATER_NOTIFICATION_TARGETS] == [stale]
    saved = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [replacement], cf.WATER_TEST_NOTIFICATION: False},
    )
    draft = (await _water_drafts(hass, entry))[0]
    notification_bindings = [
        binding for binding in draft.bindings if binding.role.startswith("water_safety.notification.")
    ]
    assert [(binding.role, binding.reference.current_locator) for binding in notification_bindings] == [
        (DEFAULT_NOTIFICATION_ROLE, replacement)
    ]

    activated = await _activate_water_draft(hass, saved)
    assert activated["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.runtime_data.loaded_water_safety_configuration != prior
    host = entry.runtime_data.water_safety_host
    assert host is not None
    assert host.degraded_notification_bindings == {}
    assert host._bindings[DEFAULT_NOTIFICATION_ROLE].current_locator == replacement

    await _reload_loaded(hass, entry)
    assert entry.runtime_data.water_safety_host._bindings[DEFAULT_NOTIFICATION_ROLE].current_locator == replacement
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.runtime_data.water_safety_host._bindings[DEFAULT_NOTIFICATION_ROLE].current_locator == replacement


@pytest.mark.asyncio
async def test_activation_cancellation_bounds_uncooperative_callback_and_remains_retryable(
    hass,
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(water_host_module, "CALLBACK_TASK_TERMINATION_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(water_host_module, "RESOURCE_CLEANUP_TIMEOUT_SECONDS", 0.1)
    entry, _canonical = await _active_entry(hass, monkeypatch)
    hass.states.async_set(SENSOR, "unavailable")
    await hass.async_block_till_done()
    service = activation.WaterSafetyActivationService()
    original_build = activation.build_water_safety_host
    resources_ready = asyncio.Event()
    callback_started = asyncio.Event()
    callback_cancelled = asyncio.Event()
    callback_can_finish = asyncio.Event()
    scheduler_cancel_all_attempted = asyncio.Event()
    executor_close_attempted = asyncio.Event()
    primary_message = "primary initialization cancellation"

    def build_and_cancel_after_resources(*args, **kwargs):
        host = original_build(*args, **kwargs)
        original_submit = host._async_submit_runtime
        original_cancel_all = host._scheduler.cancel_all
        original_close = host._executor.async_close

        def tracked_cancel_all():
            try:
                original_cancel_all()
            finally:
                hass.loop.call_soon_threadsafe(scheduler_cancel_all_attempted.set)

        async def tracked_close():
            executor_close_attempted.set()
            await original_close()

        async def held_callback():
            callback_started.set()
            while not callback_can_finish.is_set():
                try:
                    await callback_can_finish.wait()
                except asyncio.CancelledError:
                    callback_cancelled.set()

        async def cancel_after_deadline_allocation(operation, *operation_args):
            result = await original_submit(operation, *operation_args)
            if not resources_ready.is_set() and getattr(operation, "__name__", "") == "_reschedule_deadline":
                assert host._unsubscribe is not None
                assert host._deadline_handle is not None
                callback_task = hass.async_create_task(
                    held_callback(),
                    "Water Safety cancellation cleanup regression callback",
                )
                host._callback_tasks.add(callback_task)
                callback_task.add_done_callback(host._callback_tasks.discard)
                resources_ready.set()
                raise asyncio.CancelledError(primary_message)
            return result

        monkeypatch.setattr(host._scheduler, "cancel_all", tracked_cancel_all)
        monkeypatch.setattr(host._executor, "async_close", tracked_close)
        monkeypatch.setattr(host, "_async_submit_runtime", cancel_after_deadline_allocation)
        return host

    monkeypatch.setattr(activation, "build_water_safety_host", build_and_cancel_after_resources)
    starting = hass.async_create_task(
        service.async_start_from_active_reference(
            hass,
            entry,
            bridge=HomeAssistantEventLoopBridge(hass.loop),
        ),
        "Water Safety cancellation cleanup regression activation",
    )
    await resources_ready.wait()
    await callback_started.wait()
    await callback_cancelled.wait()
    starting.cancel("secondary cancellation during cleanup")

    async with asyncio.timeout(1):
        with pytest.raises(asyncio.CancelledError) as raised:
            await starting

    assert raised.value.args == (primary_message,)
    owner = water_safety_lifecycle_owner(hass, entry.entry_id)
    assert len(owner.pending_cleanup_hosts) == 1
    host = owner.pending_cleanup_hosts[0]
    assert host._unsubscribe is None
    assert host._deadline_handle is None
    assert host._scheduler._closed is True
    assert host._scheduler._handles == set()
    assert scheduler_cancel_all_attempted.is_set()
    assert not executor_close_attempted.is_set()
    assert host._executor.closed is False
    assert host._stopped is False
    assert host._accepting is False
    assert host.quiescent is True
    assert len(host._callback_tasks) == 1
    callback_task = next(iter(host._callback_tasks))
    assert callback_task.done() is False
    assert host._cleanup_tasks == {}
    assert service.__dict__ == {}
    assert "callback task cancellation" in caplog.text
    assert "remain retryable" in caplog.text

    callback_can_finish.set()
    async with asyncio.timeout(1):
        await callback_task
    assert await owner.async_retry_pending_cleanup()
    assert host._callback_tasks == set()
    assert executor_close_attempted.is_set()
    assert host._executor.closed is True
    assert host._stopped is True
    assert host._cleanup_tasks == {}
    assert owner.pending_cleanup_hosts == ()

    await host.async_stop()


@pytest.mark.asyncio
async def test_cleanup_failure_before_deadline_release_retains_dependency_and_retries(
    hass,
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(water_host_module, "RESOURCE_CLEANUP_TIMEOUT_SECONDS", 0.1)
    entry, _canonical = await _active_entry(hass, monkeypatch)
    hass.states.async_set(SENSOR, "unavailable")
    await hass.async_block_till_done()
    original_build = activation.build_water_safety_host
    scheduler_cancel_all_attempted = asyncio.Event()
    executor_close_attempted = asyncio.Event()
    primary_message = "initialization cancelled before activation completed"
    deadline_cleanup_fails = True

    class RetryableDeadline:
        def __init__(self) -> None:
            self.released = False

        def cancel(self) -> None:
            if deadline_cleanup_fails:
                raise RuntimeError("deadline cleanup regression failure before release")
            self.released = True

    retryable_deadline = RetryableDeadline()

    def build_with_failing_deadline_cleanup(*args, **kwargs):
        host = original_build(*args, **kwargs)
        original_submit = host._async_submit_runtime
        original_cancel_all = host._scheduler.cancel_all
        original_close = host._executor.async_close
        cancellation_injected = False

        async def cancel_after_deadline_allocation(operation, *operation_args):
            nonlocal cancellation_injected
            result = await original_submit(operation, *operation_args)
            if not cancellation_injected and getattr(operation, "__name__", "") == "_reschedule_deadline":
                cancellation_injected = True
                assert host._deadline_handle is not None
                await original_submit(host._cancel_deadline)
                assert host._deadline_handle is None
                host._deadline_handle = retryable_deadline

                def tracked_cancel_all():
                    try:
                        original_cancel_all()
                    finally:
                        hass.loop.call_soon_threadsafe(scheduler_cancel_all_attempted.set)

                async def tracked_close():
                    executor_close_attempted.set()
                    await original_close()

                monkeypatch.setattr(host._scheduler, "cancel_all", tracked_cancel_all)
                monkeypatch.setattr(host._executor, "async_close", tracked_close)
                raise asyncio.CancelledError(primary_message)
            return result

        monkeypatch.setattr(host, "_async_submit_runtime", cancel_after_deadline_allocation)
        return host

    monkeypatch.setattr(activation, "build_water_safety_host", build_with_failing_deadline_cleanup)
    with pytest.raises(asyncio.CancelledError) as raised:
        await activation.WaterSafetyActivationService().async_start_from_active_reference(
            hass,
            entry,
            bridge=HomeAssistantEventLoopBridge(hass.loop),
        )

    assert raised.value.args == (primary_message,)
    owner = water_safety_lifecycle_owner(hass, entry.entry_id)
    assert len(owner.pending_cleanup_hosts) == 1
    host = owner.pending_cleanup_hosts[0]
    assert scheduler_cancel_all_attempted.is_set()
    assert not executor_close_attempted.is_set()
    assert host._deadline_handle is retryable_deadline
    assert retryable_deadline.released is False
    assert host._scheduler._closed is True
    assert host._scheduler._handles == set()
    assert host._callback_tasks == set()
    assert host._executor.closed is False
    assert host._stopped is False
    assert host._cleanup_tasks == {}
    assert "current deadline cancellation" in caplog.text
    assert "deadline cleanup regression failure before release" in caplog.text

    deadline_cleanup_fails = False
    assert await owner.async_retry_pending_cleanup()
    assert host._deadline_handle is None
    assert retryable_deadline.released is True
    assert executor_close_attempted.is_set()
    assert host._executor.closed is True
    assert host._stopped is True
    assert host._cleanup_tasks == {}
    assert owner.pending_cleanup_hosts == ()


@pytest.mark.asyncio
async def test_ha_lifecycle_retains_quiescent_cleanup_without_failed_unload_and_recovers(
    hass,
    monkeypatch,
) -> None:
    monkeypatch.setattr(water_host_module, "RESOURCE_CLEANUP_TIMEOUT_SECONDS", 0.01)
    entry, _moisture, _phone = await _activate_heating_and_water_with_notification(
        hass,
        title="Water HA lifecycle recovery",
        notify_name="ha_lifecycle_recovery",
        platform="ha-lifecycle-recovery",
    )
    water_host = entry.runtime_data.water_safety_host
    heating_host = entry.runtime_data.host
    owner = water_safety_lifecycle_owner(hass, entry.entry_id)
    close_started = asyncio.Event()
    close_can_finish = asyncio.Event()
    original_close = water_host._executor.async_close

    async def held_close() -> None:
        close_started.set()
        await close_can_finish.wait()
        await original_close()

    monkeypatch.setattr(water_host._executor, "async_close", held_close)

    original_build = activation.build_water_safety_host
    created_after_pending = 0

    def count_builds(*args, **kwargs):
        nonlocal created_after_pending
        created_after_pending += 1
        return original_build(*args, **kwargs)

    monkeypatch.setattr(activation, "build_water_safety_host", count_builds)
    dispatched = _spy_ha_service_dispatch(water_host._output_port)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await close_started.wait()
    assert entry.state is config_entries.ConfigEntryState.NOT_LOADED
    assert entry.state is not config_entries.ConfigEntryState.FAILED_UNLOAD
    assert created_after_pending == 0
    assert owner.pending_cleanup_hosts == (water_host,)
    assert owner.pending_cleanup_is_quiescent is True
    assert water_host.quiescent is True
    assert water_host._output_port.quiescent is True
    assert water_host.stopped is False
    assert heating_host.stopped is True
    assert water_host._unsubscribe is None
    assert water_host._deadline_handle is None
    assert water_host._callback_tasks == set()
    assert water_host._scheduler.released is True
    action_registry = hass.data.get("controlel_water_safety_v1_action_registry")
    assert action_registry is None or entry.entry_id not in action_registry.handlers

    with pytest.raises(RuntimeError, match="quiescent"):
        await water_host.async_frontend_api_water_safety_action("silence")
    scheduled_callbacks: list[str] = []
    water_host.submit_scheduled_callback(lambda: scheduled_callbacks.append("ran"))
    dispatch_count = len(dispatched)
    hass.states.async_set(water_host._mapper.entity_id, "on")
    await hass.async_block_till_done()
    assert scheduled_callbacks == []
    assert len(dispatched) == dispatch_count
    hass.states.async_set(water_host._mapper.entity_id, "off")
    await hass.async_block_till_done()
    old_dispatch_count = len(dispatched)
    old_port_result = await hass.async_add_executor_job(
        water_host._output_port.request,
        _notification_command(),
    )
    assert old_port_result.outcome is WaterOutputOutcome.FAILED
    assert old_port_result.failure_code == "water_safety_host_quiescent"
    assert len(dispatched) == old_dispatch_count

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert created_after_pending == 0
    assert owner.pending_cleanup_hosts == (water_host,)
    assert entry.runtime_data.water_safety_host is None
    assert "prior host remains lifecycle-owned" in entry.runtime_data.water_safety_startup_failure
    assert entry.runtime_data.water_safety_action_unregister is None
    assert action_registry is None or entry.entry_id not in action_registry.handlers
    pending_heating_host = entry.runtime_data.host
    assert pending_heating_host is not None
    assert pending_heating_host is not heating_host
    assert pending_heating_host.accepting is True
    heating_result = await pending_heating_host.async_reevaluate()
    assert isinstance(heating_result, HeatDemandEvaluationResult)
    assert heating_result.trigger is HeatDemandEvaluationTrigger.MANUAL
    assert heating_result.building_heat_demand is not None
    pending_water_module = _frontend_water_module(hass, entry)
    assert pending_water_module.status == "error"
    assert pending_water_module.reason == "water_safety_startup_failed"
    pending_readiness = (await async_get_config_entry_diagnostics(hass, entry))["configuration_readiness"][
        "water_safety"
    ]
    assert pending_readiness["runtime_loaded"] is False
    assert "prior host remains lifecycle-owned" in pending_readiness["startup_failure"]
    old_output_port = water_host._output_port

    cleanup_task = water_host._cleanup_tasks["runtime executor close"]
    close_can_finish.set()
    await cleanup_task
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert created_after_pending == 1
    assert owner.pending_cleanup_hosts == ()
    assert owner.active_host is entry.runtime_data.water_safety_host
    replacement = entry.runtime_data.water_safety_host
    assert replacement is not water_host
    assert replacement._output_port is not old_output_port
    assert old_output_port.quiescent is True
    assert replacement._output_port.quiescent is False
    assert water_host.stopped is True
    assert pending_heating_host.stopped is True
    assert entry.runtime_data.host is not None
    assert entry.runtime_data.host.accepting is True
    recovered_water_module = _frontend_water_module(hass, entry)
    assert recovered_water_module.status == "active"
    assert recovered_water_module.reason is None
    recovered_readiness = (await async_get_config_entry_diagnostics(hass, entry))["configuration_readiness"][
        "water_safety"
    ]
    assert recovered_readiness["runtime_loaded"] is True
    assert recovered_readiness["startup_failure"] is None
    recovered_water = hass.data["controlel_frontend_api_v1_registry"].get(entry.entry_id).water_safety()
    assert recovered_water.processing_enabled is True
    assert recovered_water.state == WaterSafetyState.OK.value
    replacement_dispatch = _spy_ha_service_dispatch(replacement._output_port)
    issued = await replacement.test_notification()
    assert issued.output_results[0].outcome is WaterOutputOutcome.ACCEPTED
    assert any(item[0] == "notify" for item in replacement_dispatch)
    retained_dispatch = len(dispatched)
    retained = await hass.async_add_executor_job(old_output_port.request, _notification_command())
    assert retained.outcome is WaterOutputOutcome.FAILED
    assert retained.failure_code == "water_safety_host_quiescent"
    assert len(dispatched) == retained_dispatch


@pytest.mark.asyncio
async def test_ordinary_initialization_failure_retains_quiescent_host_for_real_reload(
    hass,
    monkeypatch,
) -> None:
    monkeypatch.setattr(water_host_module, "RESOURCE_CLEANUP_TIMEOUT_SECONDS", 0.01)
    entry, _moisture, _phone = await _activate_heating_and_water_with_notification(
        hass,
        title="Water initialization failure recovery",
        notify_name="initialization_failure_recovery",
        platform="initialization-failure-recovery",
    )
    owner = water_safety_lifecycle_owner(hass, entry.entry_id)
    original_build = activation.build_water_safety_host
    close_started = asyncio.Event()
    close_can_finish = asyncio.Event()
    failure_injected = False

    def fail_one_initialization_after_resources(*args, **kwargs):
        nonlocal failure_injected
        host = original_build(*args, **kwargs)
        if failure_injected:
            return host
        failure_injected = True
        original_submit = host._async_submit_runtime
        original_close = host._executor.async_close
        failed = False

        async def fail_after_deadline_allocation(operation, *operation_args):
            nonlocal failed
            result = await original_submit(operation, *operation_args)
            if not failed and getattr(operation, "__name__", "") == "_reschedule_deadline":
                failed = True
                raise RuntimeError("ordinary initialization failure after resources")
            return result

        async def held_close() -> None:
            close_started.set()
            await close_can_finish.wait()
            await original_close()

        monkeypatch.setattr(host, "_async_submit_runtime", fail_after_deadline_allocation)
        monkeypatch.setattr(host._executor, "async_close", held_close)
        return host

    monkeypatch.setattr(activation, "build_water_safety_host", fail_one_initialization_after_resources)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await close_started.wait()
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.runtime_data.host is not None
    assert entry.runtime_data.host.accepting is True
    assert entry.runtime_data.water_safety_host is None
    assert "ordinary initialization failure after resources" in entry.runtime_data.water_safety_startup_failure
    assert entry.runtime_data.water_safety_action_unregister is None
    (failed_host,) = owner.pending_cleanup_hosts
    assert failed_host.quiescent is True
    assert failed_host.stopped is False

    cleanup_task = failed_host._cleanup_tasks["runtime executor close"]
    close_can_finish.set()
    await cleanup_task
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert owner.pending_cleanup_hosts == ()
    assert failed_host.stopped is True
    assert owner.active_host is entry.runtime_data.water_safety_host
    assert entry.runtime_data.water_safety_host is not failed_host
    assert entry.runtime_data.water_safety_startup_failure is None


@pytest.mark.asyncio
async def test_water_only_missing_required_binding_reloads_and_unloads_without_retained_resources(hass) -> None:
    entry = await _empty_entry(hass, title="Water-only failed lifecycle")
    await _activate_new_water(hass, entry)
    started_host = entry.runtime_data.water_safety_host
    assert started_host is not None
    moisture = started_host._mapper.entity_id
    er.async_get(hass).async_remove(moisture)
    hass.states.async_remove(moisture)

    for _attempt in range(3):
        await _reload_loaded(hass, entry)
        assert entry.runtime_data.host is None
        assert entry.runtime_data.water_safety_host is None
        assert entry.runtime_data.loaded_water_safety_configuration is None
        assert WATER_SAFETY_SENSOR_ROLE in entry.runtime_data.water_safety_startup_failure
        assert entry.runtime_data.water_safety_action_unregister is None
        frontend_registry = hass.data["controlel_frontend_api_v1_registry"]
        assert set(frontend_registry.providers) == {entry.entry_id}
        action_registry = hass.data.get("controlel_water_safety_v1_action_registry")
        assert action_registry is None or entry.entry_id not in action_registry.handlers

    assert started_host._unsubscribe is None
    assert started_host._deadline_handle is None
    assert started_host._callback_tasks == set()
    assert started_host._scheduler._closed is True
    assert started_host._scheduler._handles == set()
    assert started_host._executor.closed is True
    assert started_host._stopped is True

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.entry_id not in frontend_registry.providers
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.runtime_data.host is None
    assert entry.runtime_data.water_safety_host is None
    assert WATER_SAFETY_SENSOR_ROLE in entry.runtime_data.water_safety_startup_failure


@pytest.mark.asyncio
async def test_ha_dispatch_crossing_unload_does_not_actuate(hass, monkeypatch) -> None:
    hass.states.async_set(SENSOR, "off")
    hass.services.async_register("notify", "mobile_app_phone", lambda call: None)
    host = _host(hass)
    await host.async_initialize()
    dispatched = _spy_ha_service_dispatch(host._output_port)
    admitted = asyncio.Event()
    resume = asyncio.Event()
    retired = asyncio.Event()
    original_dispatch = host._output_port._async_dispatch_ha_service
    original_quiesce = host._output_port.quiesce

    async def pause_then_dispatch(*args, **kwargs):
        admitted.set()
        await resume.wait()
        return await original_dispatch(*args, **kwargs)

    def quiesce_and_signal() -> None:
        original_quiesce()
        retired.set()

    monkeypatch.setattr(host._output_port, "_async_dispatch_ha_service", pause_then_dispatch)
    monkeypatch.setattr(host._output_port, "quiesce", quiesce_and_signal)
    notifying = hass.async_create_task(host.test_notification(), "Water dispatch-crossing-unload request")
    stopping = None
    result = None
    try:
        async with asyncio.timeout(1):
            await admitted.wait()
            stopping = hass.async_create_task(host.async_stop(), "Water dispatch-crossing-unload stop")
            await retired.wait()
            resume.set()
            result = await notifying
            await stopping
    finally:
        resume.set()
        if stopping is not None:
            await stopping
        elif not host.stopped:
            await host.async_stop()

    assert result.output_results[0].outcome is WaterOutputOutcome.FAILED
    assert result.output_results[0].failure_code == "water_safety_host_quiescent"
    assert dispatched == []
    assert host._output_port.quiescent is True


@pytest.mark.asyncio
async def test_queued_logical_action_after_retirement_does_not_mutate(hass, monkeypatch) -> None:
    hass.states.async_set(SENSOR, "off")
    host = _host(hass)
    await host.async_initialize()
    dispatched = _spy_ha_service_dispatch(host._output_port)
    occupy_started = threading.Event()
    occupy_release = threading.Event()
    logical_admitted = asyncio.Event()
    retired = asyncio.Event()
    cleanup_ran = asyncio.Event()
    silence_calls: list[str] = []
    original_silence = host._runtime.silence
    original_cancel_all = host._scheduler.cancel_all
    original_quiesce = host._output_port.quiesce
    original_submit = host._async_submit_runtime

    def occupy() -> None:
        occupy_started.set()
        occupy_release.wait()

    def tracked_silence(*args, **kwargs):
        silence_calls.append("silence")
        return original_silence(*args, **kwargs)

    def tracked_cancel_all() -> None:
        try:
            original_cancel_all()
        finally:
            hass.loop.call_soon_threadsafe(cleanup_ran.set)

    def quiesce_and_signal() -> None:
        original_quiesce()
        retired.set()

    async def submit_and_signal(operation, *args):
        if operation is not occupy:
            logical_admitted.set()
        return await original_submit(operation, *args)

    monkeypatch.setattr(host._runtime, "silence", tracked_silence)
    monkeypatch.setattr(host._scheduler, "cancel_all", tracked_cancel_all)
    monkeypatch.setattr(host._output_port, "quiesce", quiesce_and_signal)
    occupy_task = hass.async_create_task(host._async_submit_runtime(occupy), "Water occupy executor")
    stopping = None
    silence_task = None
    try:
        await hass.async_add_executor_job(occupy_started.wait)
        monkeypatch.setattr(host, "_async_submit_runtime", submit_and_signal)
        silence_task = hass.async_create_task(host.silence(), "Water queued logical silence")
        await logical_admitted.wait()
        stopping = hass.async_create_task(host.async_stop(), "Water retire queued logical work")
        await retired.wait()
        occupy_release.set()
        async with asyncio.timeout(1):
            with pytest.raises(RuntimeError, match="quiescent"):
                await silence_task
            await cleanup_ran.wait()
            await stopping
            await occupy_task
    finally:
        occupy_release.set()
        if silence_task is not None and not silence_task.done():
            silence_task.cancel()
        if stopping is not None:
            await stopping
        elif not host.stopped:
            await host.async_stop()
        if not occupy_task.done():
            await occupy_task

    assert silence_calls == []
    assert dispatched == []
    assert host._scheduler.released is True
    assert host._executor.closed is True
    assert host.stopped is True


@pytest.mark.asyncio
async def test_permanent_remove_entry_completes_pending_water_cleanup(hass, monkeypatch) -> None:
    monkeypatch.setattr(water_host_module, "RESOURCE_CLEANUP_TIMEOUT_SECONDS", 0.01)
    entry, _moisture, _phone = await _activate_heating_and_water_with_notification(
        hass,
        title="Water permanent removal cleanup",
        notify_name="permanent_remove_cleanup",
        platform="permanent-remove-cleanup",
    )
    water_host = entry.runtime_data.water_safety_host
    owner = water_safety_lifecycle_owner(hass, entry.entry_id)
    entry_id = entry.entry_id
    close_started = asyncio.Event()
    close_can_finish = asyncio.Event()
    original_close = water_host._executor.async_close

    async def held_close() -> None:
        close_started.set()
        await close_can_finish.wait()
        await original_close()

    monkeypatch.setattr(water_host._executor, "async_close", held_close)
    await hass.config_entries.async_remove(entry.entry_id)
    await close_started.wait()
    assert hass.config_entries.async_get_entry(entry_id) is None
    owners = hass.data.get(WATER_SAFETY_LIFECYCLE_OWNERS_KEY)
    assert owners is not None
    assert owners.get(entry_id) is owner
    assert owner.pending_cleanup_hosts == (water_host,)
    completion = owner.completion_task
    assert completion is not None
    assert completion.done() is False
    assert water_host.stopped is False
    assert water_host._executor.closed is False

    close_can_finish.set()
    async with asyncio.timeout(1):
        await completion
    assert completion.cancelled() is False
    assert completion.result() is None
    assert owner.completion_task is None
    assert water_host.stopped is True
    assert water_host._executor.closed is True
    remaining_owners = hass.data.get(WATER_SAFETY_LIFECYCLE_OWNERS_KEY)
    assert remaining_owners in (None, {})
    assert entry_id not in (remaining_owners or {})
