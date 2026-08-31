"""Real Home Assistant coverage for truthful Water Safety output requests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError

from controlel.application.setup import IdentityQuality, ProviderReference
from controlel.application.water_safety import (
    WaterOutputAction,
    WaterOutputCommand,
    WaterOutputKind,
    WaterOutputOutcome,
    WaterOutputOwner,
)
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.water_safety_output import HomeAssistantWaterSafetyOutputPort

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
OWNER = WaterOutputOwner(environment_id="home", module_key="water_safety", module_instance_id="utility-water")


def _reference(entity_id: str) -> ProviderReference:
    return ProviderReference(
        provider="home_assistant",
        provider_instance_id="home",
        object_kind="home_assistant.entity",
        native_id=f"registry-{entity_id}",
        identity_quality=IdentityQuality.STABLE,
        current_locator=entity_id,
    )


def _siren_command(entity_id: str, action: WaterOutputAction, *, sequence: int) -> WaterOutputCommand:
    return WaterOutputCommand(
        command_id=f"utility-water:command:{sequence}",
        requested_at=NOW,
        owner=OWNER,
        output_kind=WaterOutputKind.SIREN,
        action=action,
        target_role=f"water_safety.siren.target_{sequence}",
        target=_reference(entity_id),
    )


def _notification_command() -> WaterOutputCommand:
    return WaterOutputCommand(
        command_id="utility-water:command:notification",
        requested_at=NOW,
        owner=OWNER,
        output_kind=WaterOutputKind.NOTIFICATION,
        action=WaterOutputAction.NOTIFY_WET,
        target_role="water_safety.notification.primary",
        target=_reference("notify.phone"),
        message_code="water_safety.wet",
    )


@pytest.mark.asyncio
async def test_siren_on_and_off_are_requests_without_physical_state_claim(hass) -> None:
    calls: list[tuple[str, str]] = []

    async def record(call) -> None:
        calls.append((call.service, call.data[ATTR_ENTITY_ID]))

    hass.services.async_register("siren", "turn_on", record)
    hass.services.async_register("siren", "turn_off", record)
    hass.states.async_set("siren.hall", "off")
    port = HomeAssistantWaterSafetyOutputPort(hass, HomeAssistantEventLoopBridge(hass.loop))

    activated = await hass.async_add_executor_job(
        port.request,
        _siren_command("siren.hall", WaterOutputAction.REQUEST_SIREN_ON, sequence=1),
    )
    cleared = await hass.async_add_executor_job(
        port.request,
        _siren_command("siren.hall", WaterOutputAction.REQUEST_SIREN_OFF, sequence=2),
    )

    assert activated.outcome is WaterOutputOutcome.ACCEPTED
    assert cleared.outcome is WaterOutputOutcome.ACCEPTED
    assert calls == [("turn_on", "siren.hall"), ("turn_off", "siren.hall")]
    assert hass.states.get("siren.hall").state == "off"


@pytest.mark.asyncio
async def test_unavailable_and_failed_sirens_are_isolated_from_other_outputs(hass, caplog) -> None:
    siren_calls: list[str] = []
    notifications: list[str] = []

    async def siren_handler(call) -> None:
        entity_id = call.data[ATTR_ENTITY_ID]
        siren_calls.append(entity_id)
        if entity_id == "siren.failed":
            raise HomeAssistantError("test service failure")

    async def notify_handler(call) -> None:
        notifications.append(call.data["message"])

    hass.services.async_register("siren", "turn_on", siren_handler)
    hass.services.async_register("notify", "phone", notify_handler)
    hass.states.async_set("siren.unavailable", STATE_UNAVAILABLE)
    hass.states.async_set("siren.failed", "off")
    hass.states.async_set("siren.working", "off")
    port = HomeAssistantWaterSafetyOutputPort(hass, HomeAssistantEventLoopBridge(hass.loop))

    unavailable = await hass.async_add_executor_job(
        port.request,
        _siren_command("siren.unavailable", WaterOutputAction.REQUEST_SIREN_ON, sequence=1),
    )
    failed = await hass.async_add_executor_job(
        port.request,
        _siren_command("siren.failed", WaterOutputAction.REQUEST_SIREN_ON, sequence=2),
    )
    working = await hass.async_add_executor_job(
        port.request,
        _siren_command("siren.working", WaterOutputAction.REQUEST_SIREN_ON, sequence=3),
    )
    notified = await hass.async_add_executor_job(port.request, _notification_command())

    assert unavailable.outcome is WaterOutputOutcome.FAILED
    assert unavailable.failure_code == "home_assistant_siren_unavailable"
    assert failed.outcome is WaterOutputOutcome.FAILED
    assert failed.failure_code == "home_assistant_service_call_failed"
    assert working.outcome is WaterOutputOutcome.ACCEPTED
    assert notified.outcome is WaterOutputOutcome.ACCEPTED
    assert siren_calls == ["siren.failed", "siren.working"]
    assert len(notifications) == 1
    assert "unavailable" in caplog.text
    assert "service request failed" in caplog.text
