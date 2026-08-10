"""Generic Home Assistant climate adapter for zone setpoint assist."""

from collections.abc import Coroutine
from typing import Any, Protocol

from controlel.domain.heat_delivery import HeatDeliveryCommand, HeatDeliveryCommandKind

from .event_loop_bridge import HomeAssistantEventLoopBridge


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


class HomeAssistantLike(Protocol):
    services: ServiceRegistryLike


class HomeAssistantHeatDeliveryPort:
    """Dispatch only truthful climate target-temperature commands."""

    def __init__(self, hass: HomeAssistantLike, bridge: HomeAssistantEventLoopBridge, entity_id: str) -> None:
        if not entity_id.startswith("climate."):
            raise ValueError("setpoint-assist actuator must be a climate entity")
        self._hass = hass
        self._bridge = bridge
        self._entity_id = entity_id

    def execute(self, command: HeatDeliveryCommand) -> None:
        if command.kind is not HeatDeliveryCommandKind.SET_TARGET_TEMPERATURE:
            raise ValueError(f"unsupported Home Assistant heat-delivery command: {command.kind}")

        async def async_execute() -> None:
            await self._hass.services.async_call(
                "climate",
                "set_temperature",
                {"temperature": command.value},
                blocking=True,
                target={"entity_id": self._entity_id},
            )

        self._bridge.run_coroutine(async_execute)
