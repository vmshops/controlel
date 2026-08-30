"""Regression tests for fresh Controlel install bootstrap."""

import pytest
from homeassistant.components import frontend
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
from custom_components.controlel.const import DOMAIN
from custom_components.controlel.core_capabilities import water_safety_core_available
from custom_components.controlel.frontend_api_websocket import (
    FRONTEND_API_V1_DIAGNOSTICS,
    FRONTEND_API_V1_HEATING,
    FRONTEND_API_V1_OVERVIEW,
    FRONTEND_API_V1_SETUP,
    FRONTEND_API_V1_WATER_SAFETY,
)
from custom_components.controlel.panel import FRONTEND_URL_PATH


async def _read(client, command: str, entry_id: str) -> dict[str, object]:
    await client.send_json_auto_id({"type": command, "config_entry_id": entry_id})
    response = await client.receive_json()
    assert response["success"] is True
    return response["result"]


@pytest.fixture
async def http_component(hass) -> None:
    assert await async_setup_component(hass, "http", {}) is True
    assert hass.http is not None


@pytest.mark.asyncio
async def test_empty_entry_setup_registers_frontend_api_and_panel_without_heating_runtime(
    hass,
    hass_ws_client,
    http_component,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Controlel", data={}, options={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    assert await hass.config_entries.async_setup(entry.entry_id) is True

    runtime = entry.runtime_data
    assert runtime.host is None
    assert runtime.config is None
    assert runtime.frontend_api_unregister is not None
    assert frontend.async_panel_exists(hass, FRONTEND_URL_PATH) is True

    client = await hass_ws_client(hass)
    overview = await _read(client, FRONTEND_API_V1_OVERVIEW, entry.entry_id)
    heating = await _read(client, FRONTEND_API_V1_HEATING, entry.entry_id)
    diagnostics = await _read(client, FRONTEND_API_V1_DIAGNOSTICS, entry.entry_id)
    setup = await _read(client, FRONTEND_API_V1_SETUP, entry.entry_id)

    assert overview["frontend_api_version"] == 1
    assert overview["system"]["status"] == "stopped"
    assert overview["system"]["operating_mode"] == "UNCONFIGURED"
    expected_modules = [
        {"module_id": "heating", "status": "inactive", "reason": "heating_not_configured"},
    ]
    if water_safety_core_available():
        expected_modules.append(
            {
                "module_id": "water_safety",
                "status": "inactive",
                "reason": "water_safety_not_configured",
            },
        )
    assert overview["modules"] == expected_modules
    assert heating["zones"] == []
    assert heating["building"]["heat_source"]["permission"] == "unknown"
    assert diagnostics["health"]["runtime_status"] == "stopped"
    assert diagnostics["recent_events"] == []
    assert setup["readiness"] == {"state": "ready", "reason_code": None}

    if water_safety_core_available():
        water = await _read(client, FRONTEND_API_V1_WATER_SAFETY, entry.entry_id)
        assert water["state"] == "DISABLED"
        assert water["processing_enabled"] is False
        assert water["actions_available"] == []


@pytest.mark.asyncio
async def test_empty_entry_unload_removes_frontend_api_provider(
    hass,
    hass_ws_client,
    http_component,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Controlel", data={}, options={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    client = await hass_ws_client(hass)
    await _read(client, FRONTEND_API_V1_OVERVIEW, entry.entry_id)

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await client.send_json_auto_id({"type": FRONTEND_API_V1_OVERVIEW, "config_entry_id": entry.entry_id})
    missing = await client.receive_json()
    assert missing["success"] is False
    assert missing["error"]["code"] == "not_found"
    assert "unavailable for this config entry" in missing["error"]["message"]


@pytest.mark.asyncio
async def test_configured_heating_setup_unchanged_after_empty_bootstrap_fix(
    hass,
    hass_ws_client,
    entry_data,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    assert entry.runtime_data.host is not None

    client = await hass_ws_client(hass)
    overview = await _read(client, FRONTEND_API_V1_OVERVIEW, entry.entry_id)
    assert overview["system"]["status"] == "active"
    assert overview["modules"][0] == {"module_id": "heating", "status": "active", "reason": None}
