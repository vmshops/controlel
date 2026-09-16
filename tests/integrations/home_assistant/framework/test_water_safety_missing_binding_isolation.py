"""P0 regression: missing Water Safety notification bindings must not kill the entry."""

from __future__ import annotations

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
from custom_components.controlel import config_flow as cf
from custom_components.controlel import water_safety_activation as activation
from custom_components.controlel.diagnostics import async_get_config_entry_diagnostics
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.lifecycle_diagnostics import lifecycle_failures_for_entry

from .test_config_flow import (
    _activate_new_heating,
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


@pytest.mark.asyncio
async def test_unavailable_notification_defaults_clear_on_save_and_activation_recovers(hass) -> None:
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
    assert _defaults(form)[cf.WATER_NOTIFICATION_TARGETS] == []
    assert phone in form["description_placeholders"]["unavailable_notification_targets"]
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
