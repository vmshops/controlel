"""Home Assistant panel registration for the Controlel frontend shell.

Serves the existing Controlel frontend (the integration's ``frontend/``
directory, the single source of truth for the runtime shell) as a static
path and registers it as a Home Assistant sidebar panel using the standard
custom-integration pattern (``panel_custom.async_register_panel`` with a
``module_url``), mirroring the KNX/Dynalite panel architecture.

The panel is read-only: it reuses the existing Frontend API v1 WebSocket
transport and the existing authenticated Home Assistant connection. No new
endpoints, control actions, or authentication are introduced here.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

# The shell lives in the integration's ``frontend/`` directory, which is the
# single source of truth for the runtime assets. HACS ships the integration
# directory, so these assets are available at runtime.
FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

FRONTEND_URL_PATH = DOMAIN
FRONTEND_STATIC_URL_BASE = f"/{DOMAIN}_static"
FRONTEND_WEBCOMPONENT_NAME = "controlel-panel"
FRONTEND_MODULE_URL = f"{FRONTEND_STATIC_URL_BASE}/ha-panel.js"
FRONTEND_SIDEBAR_TITLE = "Controlel"
FRONTEND_SIDEBAR_ICON = "mdi:fire"

_STATIC_PATH_REGISTERED_KEY = f"{DOMAIN}_static_path_registered"


async def async_register_controlel_panel(hass: HomeAssistant, config_entry_id: str) -> None:
    """Serve the packaged frontend and register the Controlel sidebar panel.

    Idempotent: the static path is registered once per process, and the panel
    is only registered if it is not already present (so a reload does not
    duplicate it).
    """
    if not hass.data.get(_STATIC_PATH_REGISTERED_KEY):
        await hass.http.async_register_static_paths([StaticPathConfig(FRONTEND_STATIC_URL_BASE, FRONTEND_DIR)])
        hass.data[_STATIC_PATH_REGISTERED_KEY] = True

    if not frontend.async_panel_exists(hass, FRONTEND_URL_PATH):
        await panel_custom.async_register_panel(
            hass=hass,
            frontend_url_path=FRONTEND_URL_PATH,
            webcomponent_name=FRONTEND_WEBCOMPONENT_NAME,
            sidebar_title=FRONTEND_SIDEBAR_TITLE,
            sidebar_icon=FRONTEND_SIDEBAR_ICON,
            module_url=FRONTEND_MODULE_URL,
            config={"config_entry_id": config_entry_id},
        )


def async_remove_controlel_panel(hass: HomeAssistant) -> None:
    """Remove the Controlel sidebar panel (idempotent)."""
    frontend.async_remove_panel(hass, FRONTEND_URL_PATH)
