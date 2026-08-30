"""Authenticated Home Assistant-local WebSocket transport for Frontend API v1."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import voluptuous as vol
from homeassistant.components import websocket_api

from controlel.frontend_api.v1 import FrontendApiProviderV1, frontend_response_to_dict

from .const import DOMAIN
from .core_capabilities import water_safety_core_available

FRONTEND_API_V1_OVERVIEW = f"{DOMAIN}/frontend_api/v1/overview"
FRONTEND_API_V1_HEATING = f"{DOMAIN}/frontend_api/v1/heating"
FRONTEND_API_V1_DIAGNOSTICS = f"{DOMAIN}/frontend_api/v1/diagnostics"
FRONTEND_API_V1_SETUP = f"{DOMAIN}/frontend_api/v1/setup"
FRONTEND_API_V1_WATER_SAFETY = f"{DOMAIN}/frontend_api/v1/water_safety"
WATER_SAFETY_V1_SILENCE = f"{DOMAIN}/water_safety/v1/silence"
WATER_SAFETY_V1_DISABLE = f"{DOMAIN}/water_safety/v1/disable"
WATER_SAFETY_V1_ENABLE = f"{DOMAIN}/water_safety/v1/enable"
WATER_SAFETY_V1_TEST_NOTIFICATION = f"{DOMAIN}/water_safety/v1/test_notification"
WATER_SAFETY_V1_TEST_SIREN = f"{DOMAIN}/water_safety/v1/test_siren"
_REGISTRY_KEY = f"{DOMAIN}_frontend_api_v1_registry"
_TRANSPORT_KEY = f"{DOMAIN}_frontend_api_v1_transport_registered"
_WATER_SAFETY_ACTION_KEY = f"{DOMAIN}_water_safety_v1_action_registry"
_WATER_SAFETY_TRANSPORT_KEY = f"{DOMAIN}_water_safety_v1_transport_registered"

WaterSafetyActionHandler = Callable[[str], Awaitable[dict[str, object]]]


class WaterSafetyActionHostV1(Protocol):
    async def async_frontend_api_water_safety_action(self, action: str) -> dict[str, object]: ...


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


@dataclass(slots=True)
class WaterSafetyActionRegistryV1:
    """Route Water Safety command handlers for loaded config entries."""

    handlers: dict[str, WaterSafetyActionHandler] = field(default_factory=dict)

    def register(self, entry_id: str, handler: WaterSafetyActionHandler) -> Callable[[], None]:
        self.handlers[entry_id] = handler
        removed = False

        def unregister() -> None:
            nonlocal removed
            if removed:
                return
            removed = True
            if self.handlers.get(entry_id) is handler:
                self.handlers.pop(entry_id, None)

        return unregister

    def get(self, entry_id: str) -> WaterSafetyActionHandler | None:
        return self.handlers.get(entry_id)


def async_register_frontend_api_v1(hass: Any) -> FrontendApiRegistryV1:
    """Register the process-wide WS command types exactly once."""

    registry = hass.data.get(_REGISTRY_KEY)
    if not isinstance(registry, FrontendApiRegistryV1):
        registry = FrontendApiRegistryV1()
        hass.data[_REGISTRY_KEY] = registry
    if not hass.data.get(_TRANSPORT_KEY):
        for handler in (_overview, _heating, _diagnostics, _setup, _water_safety):
            websocket_api.async_register_command(hass, handler)
        hass.data[_TRANSPORT_KEY] = True
    if not hass.data.get(_WATER_SAFETY_TRANSPORT_KEY):
        for handler in (
            _water_safety_silence,
            _water_safety_disable,
            _water_safety_enable,
            _water_safety_test_notification,
            _water_safety_test_siren,
        ):
            websocket_api.async_register_command(hass, handler)
        hass.data[_WATER_SAFETY_TRANSPORT_KEY] = True
    return registry


def register_frontend_api_provider_v1(
    hass: Any,
    entry_id: str,
    provider: FrontendApiProviderV1,
) -> Callable[[], None]:
    """Register one loaded entry and return an idempotent stale-safe cleanup."""

    return async_register_frontend_api_v1(hass).register(entry_id, provider)


def register_water_safety_action_handler_v1(
    hass: Any,
    entry_id: str,
    handler: WaterSafetyActionHandler,
) -> Callable[[], None]:
    """Register one loaded entry's Water Safety action handler."""

    async_register_frontend_api_v1(hass)
    registry = hass.data.get(_WATER_SAFETY_ACTION_KEY)
    if not isinstance(registry, WaterSafetyActionRegistryV1):
        registry = WaterSafetyActionRegistryV1()
        hass.data[_WATER_SAFETY_ACTION_KEY] = registry
    return registry.register(entry_id, handler)


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
            "Controlel Frontend API v1 is unavailable for this config entry",
        )
        return
    response = getattr(provider, operation)()
    connection.send_result(msg["id"], frontend_response_to_dict(response))


async def _send_water_safety_action(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    action: str,
) -> None:
    registry = hass.data.get(_WATER_SAFETY_ACTION_KEY)
    handler = registry.get(msg["config_entry_id"]) if isinstance(registry, WaterSafetyActionRegistryV1) else None
    if handler is None:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_NOT_FOUND,
            "Controlel Water Safety is not available for this config entry",
        )
        return
    if not water_safety_core_available():
        connection.send_error(
            msg["id"],
            websocket_api.ERR_HOME_ASSISTANT_ERROR,
            "Water Safety requires Controlel core with water_safety APIs",
        )
        return
    try:
        result = await handler(action)
    except RuntimeError as error:
        connection.send_error(msg["id"], websocket_api.ERR_HOME_ASSISTANT_ERROR, str(error))
        return
    except (TypeError, ValueError):
        connection.send_error(
            msg["id"],
            websocket_api.ERR_INVALID_FORMAT,
            "Controlel Water Safety action request is invalid",
        )
        return
    connection.send_result(msg["id"], result)


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


@websocket_api.websocket_command(_schema(FRONTEND_API_V1_WATER_SAFETY))
@websocket_api.async_response
async def _water_safety(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not water_safety_core_available():
        connection.send_error(
            msg["id"],
            websocket_api.ERR_HOME_ASSISTANT_ERROR,
            "Water Safety requires Controlel core with water_safety APIs",
        )
        return
    await _send(hass, connection, msg, "water_safety")


@websocket_api.websocket_command(_schema(WATER_SAFETY_V1_SILENCE))
@websocket_api.require_admin
@websocket_api.async_response
async def _water_safety_silence(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send_water_safety_action(hass, connection, msg, "silence")


@websocket_api.websocket_command(_schema(WATER_SAFETY_V1_DISABLE))
@websocket_api.require_admin
@websocket_api.async_response
async def _water_safety_disable(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send_water_safety_action(hass, connection, msg, "disable")


@websocket_api.websocket_command(_schema(WATER_SAFETY_V1_ENABLE))
@websocket_api.require_admin
@websocket_api.async_response
async def _water_safety_enable(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send_water_safety_action(hass, connection, msg, "enable")


@websocket_api.websocket_command(_schema(WATER_SAFETY_V1_TEST_NOTIFICATION))
@websocket_api.require_admin
@websocket_api.async_response
async def _water_safety_test_notification(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await _send_water_safety_action(hass, connection, msg, "test_notification")


@websocket_api.websocket_command(_schema(WATER_SAFETY_V1_TEST_SIREN))
@websocket_api.require_admin
@websocket_api.async_response
async def _water_safety_test_siren(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send_water_safety_action(hass, connection, msg, "test_siren")
