"""Authenticated Home Assistant-local WebSocket transport for Frontend API v1."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api

from controlel.frontend_api.v1 import FrontendApiProviderV1, frontend_response_to_dict

from .const import DOMAIN

FRONTEND_API_V1_OVERVIEW = f"{DOMAIN}/frontend_api/v1/overview"
FRONTEND_API_V1_HEATING = f"{DOMAIN}/frontend_api/v1/heating"
FRONTEND_API_V1_DIAGNOSTICS = f"{DOMAIN}/frontend_api/v1/diagnostics"
FRONTEND_API_V1_SETUP = f"{DOMAIN}/frontend_api/v1/setup"
_REGISTRY_KEY = f"{DOMAIN}_frontend_api_v1_registry"
_TRANSPORT_KEY = f"{DOMAIN}_frontend_api_v1_transport_registered"


@dataclass(slots=True)
class FrontendApiRegistryV1:
    """Route loaded config entries without retaining unloaded providers."""

    providers: dict[str, FrontendApiProviderV1] = field(default_factory=dict)

    def register(self, entry_id: str, provider: FrontendApiProviderV1) -> Callable[[], None]:
        self.providers[entry_id] = provider
        removed = False

        def unregister() -> None:
            nonlocal removed
            if removed:
                return
            removed = True
            if self.providers.get(entry_id) is provider:
                self.providers.pop(entry_id, None)

        return unregister

    def get(self, entry_id: str) -> FrontendApiProviderV1 | None:
        return self.providers.get(entry_id)


def async_register_frontend_api_v1(hass: Any) -> FrontendApiRegistryV1:
    """Register the process-wide WS command types exactly once."""

    registry = hass.data.get(_REGISTRY_KEY)
    if not isinstance(registry, FrontendApiRegistryV1):
        registry = FrontendApiRegistryV1()
        hass.data[_REGISTRY_KEY] = registry
    if hass.data.get(_TRANSPORT_KEY):
        return registry
    for handler in (_overview, _heating, _diagnostics, _setup):
        websocket_api.async_register_command(hass, handler)
    hass.data[_TRANSPORT_KEY] = True
    return registry


def register_frontend_api_provider_v1(
    hass: Any,
    entry_id: str,
    provider: FrontendApiProviderV1,
) -> Callable[[], None]:
    """Register one loaded entry and return an idempotent stale-safe cleanup."""

    return async_register_frontend_api_v1(hass).register(entry_id, provider)


def _schema(command_type: str) -> dict[vol.Marker, object]:
    return {
        vol.Required("type"): command_type,
        vol.Required("config_entry_id"): str,
    }


async def _send(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    operation: str,
) -> None:
    registry = hass.data.get(_REGISTRY_KEY)
    provider = registry.get(msg["config_entry_id"]) if isinstance(registry, FrontendApiRegistryV1) else None
    if provider is None:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_NOT_FOUND,
            "Controlel Frontend API v1 config entry is not loaded",
        )
        return
    response = getattr(provider, operation)()
    connection.send_result(msg["id"], frontend_response_to_dict(response))


@websocket_api.websocket_command(_schema(FRONTEND_API_V1_OVERVIEW))
@websocket_api.async_response
async def _overview(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send(hass, connection, msg, "overview")


@websocket_api.websocket_command(_schema(FRONTEND_API_V1_HEATING))
@websocket_api.async_response
async def _heating(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send(hass, connection, msg, "heating")


@websocket_api.websocket_command(_schema(FRONTEND_API_V1_DIAGNOSTICS))
@websocket_api.async_response
async def _diagnostics(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send(hass, connection, msg, "diagnostics")


@websocket_api.websocket_command(_schema(FRONTEND_API_V1_SETUP))
@websocket_api.async_response
async def _setup(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send(hass, connection, msg, "setup")
