"""Real Home Assistant coverage for truthful Water Safety output requests."""

from __future__ import annotations

import asyncio
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


def _spy_output_port_ha_dispatch(port) -> list[tuple[str, str]]:
    dispatched: list[tuple[str, str]] = []

    class _ServiceDispatchSpy:
        def __init__(self, services) -> None:
            self._services = services

        async def async_call(self, domain, service, *args, **kwargs):
            dispatched.append((domain, service))
            return await self._services.async_call(domain, service, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._services, name)

    class _HassDispatchSpy:
        def __init__(self, hass) -> None:
            self._hass = hass
            self.services = _ServiceDispatchSpy(hass.services)

        def __getattr__(self, name):
            return getattr(self._hass, name)

    port._hass = _HassDispatchSpy(port._hass)
    return dispatched


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


def _valve_command(entity_id: str, *, sequence: int) -> WaterOutputCommand:
    return WaterOutputCommand(
        command_id=f"utility-water:command:valve:{sequence}",
        requested_at=NOW,
        owner=OWNER,
        output_kind=WaterOutputKind.SHUTOFF_VALVE,
        action=WaterOutputAction.REQUEST_VALVE_CLOSE,
        target_role=f"water_safety.shutoff_valve.target_{sequence}",
        target=_reference(entity_id),
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


@pytest.mark.asyncio
async def test_valve_close_requests_are_truthful_and_failures_are_isolated(hass, caplog) -> None:
    calls: list[str] = []
    notifications: list[str] = []

    async def valve_handler(call) -> None:
        entity_id = call.data[ATTR_ENTITY_ID]
        calls.append(entity_id)
        if entity_id == "valve.failed":
            raise HomeAssistantError("test close failure")

    async def notify_handler(call) -> None:
        notifications.append(call.data["message"])

    hass.services.async_register("valve", "close_valve", valve_handler)
    hass.services.async_register("notify", "phone", notify_handler)
    hass.states.async_set("valve.unavailable", STATE_UNAVAILABLE)
    hass.states.async_set("valve.failed", "open")
    hass.states.async_set("valve.working", "open")
    port = HomeAssistantWaterSafetyOutputPort(hass, HomeAssistantEventLoopBridge(hass.loop))

    unavailable = await hass.async_add_executor_job(port.request, _valve_command("valve.unavailable", sequence=1))
    failed = await hass.async_add_executor_job(port.request, _valve_command("valve.failed", sequence=2))
    working = await hass.async_add_executor_job(port.request, _valve_command("valve.working", sequence=3))
    notified = await hass.async_add_executor_job(port.request, _notification_command())

    assert unavailable.outcome is WaterOutputOutcome.FAILED
    assert unavailable.failure_code == "home_assistant_shutoff_valve_unavailable"
    assert failed.outcome is WaterOutputOutcome.FAILED
    assert failed.failure_code == "home_assistant_service_call_failed"
    assert working.outcome is WaterOutputOutcome.ACCEPTED
    assert notified.outcome is WaterOutputOutcome.ACCEPTED
    assert calls == ["valve.failed", "valve.working"]
    assert hass.states.get("valve.working").state == "open"
    assert len(notifications) == 1
    assert "unavailable" in caplog.text
    assert "service request failed" in caplog.text


@pytest.mark.asyncio
async def test_quiescent_output_port_rejects_new_actuation_without_calling_ha(hass) -> None:
    calls: list[str] = []

    async def valve_handler(call) -> None:
        calls.append(call.data[ATTR_ENTITY_ID])

    hass.services.async_register("valve", "close_valve", valve_handler)
    hass.states.async_set("valve.utility_main", "open")
    port = HomeAssistantWaterSafetyOutputPort(hass, HomeAssistantEventLoopBridge(hass.loop))

    port.quiesce()
    result = await hass.async_add_executor_job(
        port.request,
        _valve_command("valve.utility_main", sequence=1),
    )

    assert port.quiescent is True
    assert result.outcome is WaterOutputOutcome.FAILED
    assert result.failure_code == "water_safety_host_quiescent"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["notification", "siren", "valve"])
async def test_admitted_ha_dispatch_is_revoked_when_output_is_retired(hass, monkeypatch, kind) -> None:
    recorded: list[tuple[str, str]] = []

    async def record(call) -> None:
        recorded.append((call.domain, call.service))

    if kind == "notification":
        hass.services.async_register("notify", "phone", record)
        command = _notification_command()
    elif kind == "siren":
        hass.services.async_register("siren", "turn_on", record)
        hass.states.async_set("siren.hall", "off")
        command = _siren_command("siren.hall", WaterOutputAction.REQUEST_SIREN_ON, sequence=1)
    else:
        hass.services.async_register("valve", "close_valve", record)
        hass.states.async_set("valve.utility_main", "open")
        command = _valve_command("valve.utility_main", sequence=1)

    port = HomeAssistantWaterSafetyOutputPort(hass, HomeAssistantEventLoopBridge(hass.loop))
    dispatched = _spy_output_port_ha_dispatch(port)
    admitted = asyncio.Event()
    resume = asyncio.Event()
    original_dispatch = port._async_dispatch_ha_service

    async def pause_then_dispatch(*args, **kwargs):
        admitted.set()
        await resume.wait()
        return await original_dispatch(*args, **kwargs)

    monkeypatch.setattr(port, "_async_dispatch_ha_service", pause_then_dispatch)
    job = hass.async_add_executor_job(port.request, command)
    await admitted.wait()
    port.quiesce()
    resume.set()
    result = await job

    assert port.quiescent is True
    assert result.outcome is WaterOutputOutcome.FAILED
    assert result.failure_code == "water_safety_host_quiescent"
    assert dispatched == []
    assert recorded == []
