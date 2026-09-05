"""Real Home Assistant coverage for Water Safety notification Unicode payloads."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from controlel.application.setup import IdentityQuality, ProviderReference
from controlel.application.water_safety import (
    WaterOutputAction,
    WaterOutputCommand,
    WaterOutputKind,
    WaterOutputOwner,
)
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.water_safety_messages import WATER_SAFETY_MOJIBAKE_FRAGMENTS
from custom_components.controlel.water_safety_output import HomeAssistantWaterSafetyOutputPort

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
OWNER = WaterOutputOwner(environment_id="home", module_key="water_safety", module_instance_id="utility-water")


def _reference(entity_id: str) -> ProviderReference:
    return ProviderReference(
        provider="home_assistant",
        provider_instance_id="home",
        object_kind="home_assistant.endpoint",
        native_id=f"registry-{entity_id}",
        identity_quality=IdentityQuality.STABLE,
        current_locator=entity_id,
    )


def _notify_command(message_code: str) -> WaterOutputCommand:
    return WaterOutputCommand(
        command_id=f"utility-water:command:{message_code}",
        requested_at=NOW,
        owner=OWNER,
        output_kind=WaterOutputKind.NOTIFICATION,
        action=WaterOutputAction.NOTIFY_WET if message_code.endswith(".wet") else WaterOutputAction.NOTIFY_RECOVERY,
        target_role="water_safety.notification.primary",
        target=_reference("notify.phone"),
        message_code=message_code,
    )


@pytest.mark.asyncio
async def test_unicode_survives_notification_construction_unchanged(hass) -> None:
    payloads: list[dict[str, object]] = []

    async def notify_handler(call) -> None:
        payloads.append(dict(call.data))

    hass.config.language = "cs"
    hass.services.async_register("notify", "phone", notify_handler)
    port = HomeAssistantWaterSafetyOutputPort(
        hass,
        HomeAssistantEventLoopBridge(hass.loop),
        area_name="Technická místnost",
    )

    wet = await hass.async_add_executor_job(port.request, _notify_command("water_safety.wet"))
    dry = await hass.async_add_executor_job(port.request, _notify_command("water_safety.recovery"))

    assert wet.outcome.value == "ACCEPTED"
    assert dry.outcome.value == "ACCEPTED"
    assert payloads == [
        {
            "title": "Controlel – únik vody",
            "message": "Detekována voda nebo vlhkost v oblasti „Technická místnost“.",
        },
        {
            "title": "Controlel – únik vody",
            "message": "Vlhkost v oblasti „Technická místnost“ již není detekována.",
        },
    ]
    for payload in payloads:
        for value in payload.values():
            assert isinstance(value, str)
            assert value.encode("utf-8").decode("utf-8") == value
            for fragment in WATER_SAFETY_MOJIBAKE_FRAGMENTS:
                assert fragment not in value
