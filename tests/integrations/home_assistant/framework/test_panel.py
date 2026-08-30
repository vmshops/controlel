"""Tests for the Controlel Home Assistant sidebar panel registration.

These tests verify the real HA panel integration:
  - the packaged frontend is served through a registered static path;
  - the sidebar panel is registered with the correct module_url and config;
  - unloading the entry removes the panel;
  - reloading does not duplicate the panel registration;
  - the packaged frontend assets are present and complete.

The panel is a read-only UI convenience: it reuses the existing Frontend API
v1 WebSocket transport and the existing authenticated Home Assistant
connection. No control actions, new endpoints, or custom authentication are
introduced.
"""

import pytest
from homeassistant.components import frontend
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.controlel.const import DOMAIN
from custom_components.controlel.panel import (
    _STATIC_PATH_REGISTERED_KEY,
    FRONTEND_DIR,
    FRONTEND_MODULE_URL,
    FRONTEND_SIDEBAR_ICON,
    FRONTEND_SIDEBAR_TITLE,
    FRONTEND_URL_PATH,
    FRONTEND_WEBCOMPONENT_NAME,
)

# The shell files that must be present for the panel to load.
REQUIRED_FRONTEND_FILES = (
    "ha-panel.js",
    "app.js",
    "api-client.js",
    "components.js",
    "wizard.js",
    "mock-data.js",
    "mock-app-data.js",
    "styles.css",
)


@pytest.fixture
async def http_component(hass) -> None:
    """Load the http component so static paths and panels can be registered."""
    assert await async_setup_component(hass, "http", {}) is True
    assert hass.http is not None


def _panel(hass):
    """Return the registered Controlel panel, or None if absent."""
    return hass.data.get(frontend.DATA_PANELS, {}).get(FRONTEND_URL_PATH)


def _static_path_registered(hass) -> bool:
    """Return True if the Controlel static path is registered on the http app router."""
    from aiohttp.web_urldispatcher import StaticResource

    for resource in hass.http.app.router.resources():
        if isinstance(resource, StaticResource) and resource._directory == FRONTEND_DIR:
            return True
    return False


@pytest.mark.asyncio
async def test_empty_entry_registers_panel_without_heating_runtime(hass, http_component) -> None:
    """A fresh empty shell entry registers the sidebar panel immediately."""
    entry = MockConfigEntry(domain=DOMAIN, title="Controlel", data={}, options={})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    assert entry.runtime_data.host is None
    assert frontend.async_panel_exists(hass, FRONTEND_URL_PATH) is True
    panel = _panel(hass)
    assert panel is not None
    assert panel.config["config_entry_id"] == entry.entry_id


@pytest.mark.asyncio
async def test_panel_registered_with_correct_module_url_and_config(hass, entry_data, http_component) -> None:
    """Setting up a config entry registers the Controlel sidebar panel."""
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data=entry_data)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True

    # The static path is registered exactly once per process.
    assert hass.data.get(_STATIC_PATH_REGISTERED_KEY) is True
    # The static path serves the packaged frontend directory.
    assert _static_path_registered(hass) is True

    # The panel is registered with the expected identity and module_url.
    assert frontend.async_panel_exists(hass, FRONTEND_URL_PATH) is True
    panel = _panel(hass)
    assert panel is not None
    assert panel.frontend_url_path == FRONTEND_URL_PATH
    assert panel.sidebar_title == FRONTEND_SIDEBAR_TITLE
    assert panel.sidebar_icon == FRONTEND_SIDEBAR_ICON
    assert panel.config is not None
    assert panel.config["config_entry_id"] == entry.entry_id
    assert panel.config["_panel_custom"]["module_url"] == FRONTEND_MODULE_URL
    assert panel.config["_panel_custom"]["name"] == FRONTEND_WEBCOMPONENT_NAME
    # The panel runs in the main window (not an iframe) so the shell can use
    # the existing authenticated `window.hass.connection`.
    assert panel.config["_panel_custom"]["embed_iframe"] is False


@pytest.mark.asyncio
async def test_unload_removes_panel(hass, entry_data, http_component) -> None:
    """Unloading the entry removes the Controlel sidebar panel."""
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data=entry_data)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    assert frontend.async_panel_exists(hass, FRONTEND_URL_PATH) is True

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    assert frontend.async_panel_exists(hass, FRONTEND_URL_PATH) is False
    assert _panel(hass) is None


@pytest.mark.asyncio
async def test_reload_does_not_duplicate_panel(hass, entry_data, http_component) -> None:
    """Reloading the entry does not register a second panel."""
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data=entry_data)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    assert frontend.async_panel_exists(hass, FRONTEND_URL_PATH) is True
    first_panel = _panel(hass)

    # Unload and reload: the panel must be re-registered exactly once.
    assert await hass.config_entries.async_unload(entry.entry_id) is True
    assert frontend.async_panel_exists(hass, FRONTEND_URL_PATH) is False

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    assert frontend.async_panel_exists(hass, FRONTEND_URL_PATH) is True
    second_panel = _panel(hass)
    assert second_panel is not None
    assert second_panel.config["config_entry_id"] == entry.entry_id

    # Exactly one panel is registered for the Controlel URL path.
    panels = hass.data.get(frontend.DATA_PANELS, {})
    assert list(panels.keys()).count(FRONTEND_URL_PATH) == 1
    # The static path is still registered exactly once (no duplicate).
    assert hass.data.get(_STATIC_PATH_REGISTERED_KEY) is True
    assert _static_path_registered(hass) is True
    # The first and second registrations are equivalent (idempotent).
    assert first_panel.config["_panel_custom"]["name"] == second_panel.config["_panel_custom"]["name"]
    assert first_panel.config["_panel_custom"]["module_url"] == second_panel.config["_panel_custom"]["module_url"]


@pytest.mark.asyncio
async def test_panel_registration_failure_is_not_fatal(hass, entry_data, monkeypatch: pytest.MonkeyPatch) -> None:
    """Panel registration failures are logged and do not block runtime setup."""
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data=entry_data)
    entry.add_to_hass(hass)

    async def _raise_panel_failure(_hass, _config_entry_id: str) -> None:
        raise RuntimeError("panel registration unavailable")

    monkeypatch.setattr(
        "custom_components.controlel.panel.async_register_controlel_panel",
        _raise_panel_failure,
    )

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    assert entry.runtime_data.host is not None
    assert frontend.async_panel_exists(hass, FRONTEND_URL_PATH) is False


def test_frontend_assets_are_present_and_complete() -> None:
    """The packaged frontend directory contains every file the panel loads."""
    assert FRONTEND_DIR.is_dir(), f"frontend directory missing: {FRONTEND_DIR}"
    for name in REQUIRED_FRONTEND_FILES:
        assert (FRONTEND_DIR / name).is_file(), f"missing frontend asset: {name}"
    # The module_url points at a file that actually exists.
    entrypoint = FRONTEND_MODULE_URL.rsplit("/", 1)[-1]
    assert (FRONTEND_DIR / entrypoint).is_file(), f"missing entrypoint: {entrypoint}"
