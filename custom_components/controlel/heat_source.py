"""Home Assistant service-call implementation of the shared heat-source port."""

from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction

from .config import HomeAssistantHeatSourceBinding, HomeAssistantServiceCall
from .const import DOMAIN
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


class HomeAssistantServiceCallError(RuntimeError):
    def __init__(
        self,
        action: HeatingAction,
        service_call: HomeAssistantServiceCall,
        original_error: Exception,
    ) -> None:
        self.action = action
        self.domain = service_call.domain
        self.service = service_call.service
        self.target_entity_id = service_call.target_entity_id
        self.original_error = original_error
        super().__init__(
            f"Home Assistant service {self.domain}.{self.service} failed for {self.target_entity_id}: {original_error}"
        )


class HomeAssistantHeatSourcePort:
    def __init__(
        self,
        hass: HomeAssistantLike,
        bridge: HomeAssistantEventLoopBridge,
        binding: HomeAssistantHeatSourceBinding,
        on_success: Callable[[], None],
    ) -> None:
        for service_call in (binding.enable_heating, binding.disable_heating):
            if service_call.domain == DOMAIN:
                raise ValueError("Controlel cannot call its own integration service domain")
        self._hass = hass
        self._bridge = bridge
        self._binding = binding
        self._on_success = on_success

    def execute(self, command: HeatSourceCommand) -> None:
        service_call = {
            HeatingAction.ENABLE_HEATING: self._binding.enable_heating,
            HeatingAction.DISABLE_HEATING: self._binding.disable_heating,
        }[command.action]

        async def async_execute() -> None:
            await self._hass.services.async_call(
                service_call.domain,
                service_call.service,
                {},
                blocking=True,
                target={"entity_id": service_call.target_entity_id},
            )

        try:
            self._bridge.run_coroutine(async_execute)
        except Exception as error:
            raise HomeAssistantServiceCallError(
                action=command.action,
                service_call=service_call,
                original_error=error,
            ) from error
        self._on_success()
