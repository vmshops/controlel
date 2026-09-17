"""P0 regression: missing Water Safety notification bindings must not kill the entry."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.helpers import entity_registry as er

from controlel.application.configuration.water_safety_setup_adapter import (
    DEFAULT_NOTIFICATION_ROLE,
    WATER_SAFETY_SENSOR_ROLE,
)
from controlel.domain.water_safety import WaterSafetyState
from controlel.infrastructure.home_assistant import active_reference_for_module
from custom_components.controlel import async_unload_entry
from custom_components.controlel import config_flow as cf
from custom_components.controlel import water_safety_activation as activation
from custom_components.controlel import water_safety_host as water_host_module
from custom_components.controlel.diagnostics import async_get_config_entry_diagnostics
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.lifecycle_diagnostics import lifecycle_failures_for_entry
from custom_components.controlel.water_safety_lifecycle import water_safety_lifecycle_owner

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
from .test_water_safety_release_blockers import SENSOR, _active_entry


async def _reload_loaded(hass, entry) -> None:
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED


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
async def test_incomplete_real_entry_unload_retains_owner_until_retry(hass, monkeypatch) -> None:
    monkeypatch.setattr(water_host_module, "CALLBACK_TASK_TERMINATION_TIMEOUT_SECONDS", 0.01)
    entry = await _empty_entry(hass, title="Water cleanup owner unload")
    await _activate_new_water(hass, entry)
    host = entry.runtime_data.water_safety_host
    owner = water_safety_lifecycle_owner(hass, entry.entry_id)
    assert owner.active_host is host

    callback_started = asyncio.Event()
    callback_cancelled = asyncio.Event()
    callback_can_finish = asyncio.Event()

    async def held_callback() -> None:
        callback_started.set()
        while not callback_can_finish.is_set():
            try:
                await callback_can_finish.wait()
            except asyncio.CancelledError:
                callback_cancelled.set()

    callback_task = hass.async_create_task(held_callback(), "Water Safety incomplete unload callback")
    host._callback_tasks.add(callback_task)
    callback_task.add_done_callback(host._callback_tasks.discard)
    await callback_started.wait()

    assert not await async_unload_entry(hass, entry)
    await callback_cancelled.wait()
    assert entry.runtime_data.water_safety_host is host
    assert owner.active_host is None
    assert owner.pending_cleanup_hosts == (host,)
    assert host._executor.closed is False
    assert host.stopped is False

    callback_can_finish.set()
    await callback_task
    assert await async_unload_entry(hass, entry)
    assert owner.pending_cleanup_hosts == ()
    assert host._executor.closed is True
    assert host.stopped is True
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_reload_does_not_duplicate_water_host_while_predecessor_cleanup_is_pending(
    hass,
    monkeypatch,
) -> None:
    monkeypatch.setattr(water_host_module, "CALLBACK_TASK_TERMINATION_TIMEOUT_SECONDS", 0.01)
    entry, _moisture, _phone = await _activate_heating_and_water_with_notification(
        hass,
        title="Water cleanup owner reload",
        notify_name="cleanup_owner_reload",
        platform="cleanup-owner-reload",
    )
    water_host = entry.runtime_data.water_safety_host
    heating_host = entry.runtime_data.host
    owner = water_safety_lifecycle_owner(hass, entry.entry_id)
    callback_started = asyncio.Event()
    callback_can_finish = asyncio.Event()

    async def held_callback() -> None:
        callback_started.set()
        while not callback_can_finish.is_set():
            try:
                await callback_can_finish.wait()
            except asyncio.CancelledError:
                pass

    callback_task = hass.async_create_task(held_callback(), "Water Safety reload duplicate guard")
    water_host._callback_tasks.add(callback_task)
    callback_task.add_done_callback(water_host._callback_tasks.discard)
    await callback_started.wait()

    original_build = activation.build_water_safety_host
    created_after_pending = 0

    def count_builds(*args, **kwargs):
        nonlocal created_after_pending
        created_after_pending += 1
        return original_build(*args, **kwargs)

    monkeypatch.setattr(activation, "build_water_safety_host", count_builds)
    assert not await async_unload_entry(hass, entry)
    assert created_after_pending == 0
    assert owner.pending_cleanup_hosts == (water_host,)
    assert water_host.stopped is False
    assert heating_host.stopped is True

    callback_can_finish.set()
    await callback_task
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert created_after_pending == 1
    assert owner.pending_cleanup_hosts == ()
    assert owner.active_host is entry.runtime_data.water_safety_host
    assert entry.runtime_data.water_safety_host is not water_host
    assert entry.runtime_data.host is not None
    assert entry.runtime_data.host.accepting is True


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
