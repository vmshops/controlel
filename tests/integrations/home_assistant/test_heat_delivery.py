from datetime import UTC, datetime

import pytest

from controlel.domain.heat_delivery import (
    HeatDeliveryActuatorId,
    HeatDeliveryCommand,
    HeatDeliveryCommandKind,
)
from controlel.domain.value_objects.zone_id import ZoneId
from custom_components.controlel.heat_delivery import HomeAssistantHeatDeliveryPort


class Services:
    def __init__(self) -> None:
        self.calls = []

    async def async_call(self, domain, service, service_data=None, blocking=False, *, target=None):
        self.calls.append((domain, service, service_data, blocking, target))


class Hass:
    def __init__(self) -> None:
        self.services = Services()


class Bridge:
    def run_coroutine(self, factory) -> None:
        import asyncio

        asyncio.run(factory())


def command(kind=HeatDeliveryCommandKind.SET_TARGET_TEMPERATURE):
    return HeatDeliveryCommand(
        actuator_id=HeatDeliveryActuatorId("climate.bedroom_trv"),
        zone_id=ZoneId("bedroom"),
        kind=kind,
        value=30.0,
        requested_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_climate_adapter_uses_generic_set_temperature_service() -> None:
    hass = Hass()
    port = HomeAssistantHeatDeliveryPort(hass, Bridge(), "climate.bedroom_trv")
    port.execute(command())
    assert hass.services.calls == [
        ("climate", "set_temperature", {"temperature": 30.0}, True, {"entity_id": "climate.bedroom_trv"})
    ]


def test_climate_adapter_rejects_non_target_commands() -> None:
    port = HomeAssistantHeatDeliveryPort(Hass(), Bridge(), "climate.bedroom_trv")
    with pytest.raises(ValueError, match="unsupported"):
        port.execute(command(HeatDeliveryCommandKind.SET_POSITION))
