"""Home Assistant adapter for truthful Water Safety output requests."""

import logging
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, Protocol

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from controlel.application.water_safety.model import (
    WaterOutputAction,
    WaterOutputCommand,
    WaterOutputCommandResult,
    WaterOutputKind,
    WaterOutputOutcome,
)

from .event_loop_bridge import HomeAssistantEventLoopBridge

WATER_SAFETY_DEFAULT_MESSAGES: dict[str, dict[str, str]] = {
    "water_safety.wet": {
        "cs": "­čĺž Detekov├ína vlhkost!",
        "en": "­čĺž Moisture detected!",
    },
    "water_safety.recovery": {
        "cs": "Ôťů Vlhkost ustoupila",
        "en": "Ôťů Moisture cleared",
    },
    "water_safety.sensor_fault": {
        "cs": "ÔÜá´ŞĆ Porucha senzoru vlhkosti",
        "en": "ÔÜá´ŞĆ Moisture sensor fault",
    },
}

WATER_SAFETY_DEFAULT_TITLES: dict[str, str] = {
    "cs": "Bezpe─Źnost vody",
    "en": "Water Safety",
}


class ServiceRegistryLike(Protocol):
    def async_call(
        self,
        domain: str,
        service: str,
        service_data: dict[str, object] | None = None,
        blocking: bool = False,
        *,
        target: dict[str, str] | None = None,
    ) -> Coroutine[Any, Any, Any]: ...


class ConfigLike(Protocol):
    language: str


class StateLike(Protocol):
    state: str


class StateMachineLike(Protocol):
    def get(self, entity_id: str) -> StateLike | None: ...


class HomeAssistantLike(Protocol):
    services: ServiceRegistryLike
    config: ConfigLike
    states: StateMachineLike


class SirenUnavailableError(RuntimeError):
    """The configured siren has no currently usable HA state."""


class ShutoffValveUnavailableError(RuntimeError):
    """The configured shutoff valve has no currently usable HA state."""


class HomeAssistantWaterSafetyOutputPort:
    """Dispatch notification, siren, and valve requests; physical state remains unknown."""

    def __init__(
        self,
        hass: HomeAssistantLike,
        bridge: HomeAssistantEventLoopBridge,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._hass = hass
        self._bridge = bridge
        self._logger = logger or logging.getLogger(__name__)

    def request(self, command: WaterOutputCommand) -> WaterOutputCommandResult:
        try:
            if command.output_kind is WaterOutputKind.NOTIFICATION:
                self._bridge.run_coroutine(lambda: self._async_notify(command))
            elif command.output_kind is WaterOutputKind.SIREN:
                self._bridge.run_coroutine(lambda: self._async_siren(command))
            else:
                self._bridge.run_coroutine(lambda: self._async_close_shutoff_valve(command))
        except SirenUnavailableError:
            failure_code = "home_assistant_siren_unavailable"
            self._logger.warning(
                "Water Safety siren request was not sent because the target is unavailable (role=%s, action=%s)",
                command.target_role,
                command.action.value,
            )
            return WaterOutputCommandResult(
                command_id=command.command_id,
                occurred_at=datetime.now(UTC),
                outcome=WaterOutputOutcome.FAILED,
                failure_code=failure_code,
            )
        except ShutoffValveUnavailableError:
            failure_code = "home_assistant_shutoff_valve_unavailable"
            self._logger.warning(
                "Water Safety shutoff valve close request was not sent because the target is unavailable (role=%s)",
                command.target_role,
            )
            return WaterOutputCommandResult(
                command_id=command.command_id,
                occurred_at=datetime.now(UTC),
                outcome=WaterOutputOutcome.FAILED,
                failure_code=failure_code,
            )
        except Exception:
            self._logger.exception(
                "Water Safety output service request failed (kind=%s, role=%s, action=%s)",
                command.output_kind.value,
                command.target_role,
                command.action.value,
            )
            return WaterOutputCommandResult(
                command_id=command.command_id,
                occurred_at=datetime.now(UTC),
                outcome=WaterOutputOutcome.FAILED,
                failure_code="home_assistant_service_call_failed",
            )
        return WaterOutputCommandResult(
            command_id=command.command_id,
            occurred_at=datetime.now(UTC),
            outcome=WaterOutputOutcome.ACCEPTED,
        )

    async def _async_notify(self, command: WaterOutputCommand) -> None:
        locator = command.target.current_locator
        if locator is None or "." not in locator:
            raise ValueError("notification target requires a notify service locator")
        domain, service = locator.split(".", 1)
        if domain != "notify":
            raise ValueError("notification target must use the notify domain")
        message = command.custom_message or _default_message(command.message_code, self._hass.config.language)
        title = _default_title(self._hass.config.language)
        await self._hass.services.async_call(
            "notify",
            service,
            {"title": title, "message": message},
            blocking=True,
        )

    async def _async_siren(self, command: WaterOutputCommand) -> None:
        entity_id = command.target.current_locator
        if entity_id is None or "." not in entity_id:
            raise ValueError("siren target requires an entity locator")
        state = self._hass.states.get(entity_id)
        if state is None or state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
            raise SirenUnavailableError(f"siren target is unavailable: {entity_id}")
        domain = entity_id.split(".", 1)[0]
        if domain == "switch":
            service = "turn_on" if command.action is WaterOutputAction.REQUEST_SIREN_ON else "turn_off"
            await self._hass.services.async_call(
                domain,
                service,
                blocking=True,
                target={"entity_id": entity_id},
            )
            return
        if domain == "siren":
            service = "turn_on" if command.action is WaterOutputAction.REQUEST_SIREN_ON else "turn_off"
            await self._hass.services.async_call(
                domain,
                service,
                blocking=True,
                target={"entity_id": entity_id},
            )
            return
        raise ValueError(f"unsupported siren entity domain: {domain}")

    async def _async_close_shutoff_valve(self, command: WaterOutputCommand) -> None:
        entity_id = command.target.current_locator
        if entity_id is None or "." not in entity_id:
            raise ValueError("shutoff valve target requires an entity locator")
        if command.action is not WaterOutputAction.REQUEST_VALVE_CLOSE:
            raise ValueError("shutoff valve target requires a close request")
        state = self._hass.states.get(entity_id)
        if state is None or state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
            raise ShutoffValveUnavailableError(f"shutoff valve target is unavailable: {entity_id}")
        domain = entity_id.split(".", 1)[0]
        if domain != "valve":
            raise ValueError(f"unsupported shutoff valve entity domain: {domain}")
        await self._hass.services.async_call(
            "valve",
            "close_valve",
            blocking=True,
            target={"entity_id": entity_id},
        )


def _default_message(message_code: str | None, language: str) -> str:
    if message_code is None:
        raise ValueError("notification requires message_code when custom_message is absent")
    messages = WATER_SAFETY_DEFAULT_MESSAGES.get(message_code)
    if messages is None:
        raise ValueError(f"unsupported water safety message code: {message_code}")
    locale = "cs" if language.casefold().startswith("cs") else "en"
    return messages[locale]


def _default_title(language: str) -> str:
    locale = "cs" if language.casefold().startswith("cs") else "en"
    return WATER_SAFETY_DEFAULT_TITLES[locale]
