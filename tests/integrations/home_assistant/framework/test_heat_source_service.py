import asyncio
from unittest.mock import patch

import pytest
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from pytest_homeassistant_custom_component.common import MockConfigEntry

from controlel.application.services.heat_source_command_dispatcher import (
    HeatSourceCommandDispatcher,
)
from controlel.application.state.heat_source_state_store import HeatSourceStateStore
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from custom_components.controlel.config import (
    HomeAssistantHeatSourceBinding,
    HomeAssistantServiceCall,
)
from custom_components.controlel.const import (
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_TEMPERATURE_ENTITY_ID,
    DOMAIN,
)
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.heat_source import (
    HomeAssistantHeatSourcePort,
    HomeAssistantServiceCallError,
)
from custom_components.controlel.runtime_executor import HomeAssistantRuntimeExecutor


def binding() -> HomeAssistantHeatSourceBinding:
    return HomeAssistantHeatSourceBinding(
        enable_heating=HomeAssistantServiceCall("switch", "turn_on", "switch.boiler"),
        disable_heating=HomeAssistantServiceCall("switch", "turn_off", "switch.boiler"),
    )


def command(action: HeatingAction) -> HeatSourceCommand:
    return HeatSourceCommand(
        command_type=CommandFamily.HEATING,
        action=action,
    )


@pytest.mark.parametrize(
    ("action", "expected_service"),
    [
        (HeatingAction.ENABLE_HEATING, "turn_on"),
        (HeatingAction.DISABLE_HEATING, "turn_off"),
    ],
)
@pytest.mark.asyncio
async def test_real_service_registry_receives_exact_blocking_call_and_target(
    hass,
    action,
    expected_service,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    completed: list[str] = []
    successes: list[None] = []
    registry_calls: list[tuple[object, ...]] = []

    async def service_handler(call) -> None:
        entered.set()
        await release.wait()
        completed.append(call.service)

    hass.services.async_register("switch", expected_service, service_handler)
    registry_type = type(hass.services)
    original_async_call = registry_type.async_call

    async def record_async_call(
        self,
        domain,
        service,
        service_data=None,
        blocking=False,
        context=None,
        target=None,
        return_response=False,
    ):
        registry_calls.append((domain, service, service_data, blocking, target))
        return await original_async_call(
            self,
            domain,
            service,
            service_data,
            blocking,
            context,
            target,
            return_response,
        )

    executor = HomeAssistantRuntimeExecutor()
    port = HomeAssistantHeatSourcePort(
        hass=hass,
        bridge=HomeAssistantEventLoopBridge(hass.loop),
        binding=binding(),
        on_success=lambda: successes.append(None),
    )

    with patch.object(registry_type, "async_call", record_async_call):
        execution = hass.async_create_task(executor.async_submit(port.execute, command(action)))
        await entered.wait()
        assert execution.done() is False
        release.set()
        await execution

    assert registry_calls == [
        (
            "switch",
            expected_service,
            {},
            True,
            {"entity_id": "switch.boiler"},
        )
    ]
    assert completed == [expected_service]
    assert successes == [None]
    await executor.async_close()


@pytest.mark.parametrize("failure_kind", ["missing", "failing"])
@pytest.mark.asyncio
async def test_real_missing_or_failing_service_preserves_original_exception(
    hass,
    failure_kind,
) -> None:
    if failure_kind == "failing":
        original = HomeAssistantError("real service failure")

        async def fail_service(call) -> None:
            raise original

        hass.services.async_register("switch", "turn_on", fail_service)

    executor = HomeAssistantRuntimeExecutor()
    port = HomeAssistantHeatSourcePort(
        hass=hass,
        bridge=HomeAssistantEventLoopBridge(hass.loop),
        binding=binding(),
        on_success=lambda: None,
    )

    with pytest.raises(HomeAssistantServiceCallError) as raised:
        await executor.async_submit(port.execute, command(HeatingAction.ENABLE_HEATING))

    if failure_kind == "missing":
        assert isinstance(raised.value.original_error, ServiceNotFound)
    else:
        assert raised.value.original_error is original
    assert raised.value.__cause__ is raised.value.original_error
    await executor.async_close()


@pytest.mark.asyncio
async def test_real_service_failure_does_not_update_applied_core_state(hass) -> None:
    original = HomeAssistantError("failed")

    async def fail_service(call) -> None:
        raise original

    hass.services.async_register("switch", "turn_on", fail_service)
    executor = HomeAssistantRuntimeExecutor()
    state_store = HeatSourceStateStore()
    dispatcher = HeatSourceCommandDispatcher(
        HomeAssistantHeatSourcePort(
            hass=hass,
            bridge=HomeAssistantEventLoopBridge(hass.loop),
            binding=binding(),
            on_success=lambda: None,
        ),
        state_store,
    )

    with pytest.raises(HomeAssistantServiceCallError):
        await executor.async_submit(
            dispatcher.dispatch,
            command(HeatingAction.ENABLE_HEATING),
        )

    assert state_store.get() is None
    await executor.async_close()


@pytest.mark.asyncio
async def test_service_caused_state_change_queues_behind_active_runtime_without_deadlock(
    hass,
    entry_data,
) -> None:
    calls: list[str] = []
    temperature_entity_id = entry_data[CONF_TEMPERATURE_ENTITY_ID]
    entry_data[CONF_INDETERMINATE_GRACE_PERIOD] = 0.0

    async def enable_service(call) -> None:
        calls.append(call.service)
        hass.states.async_set(
            temperature_entity_id,
            "22",
            {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
        )

    async def disable_service(call) -> None:
        calls.append(call.service)

    hass.services.async_register("switch", "turn_on", enable_service)
    hass.services.async_register("switch", "turn_off", disable_service)
    hass.states.async_set(
        temperature_entity_id,
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    host = entry.runtime_data.host
    assert host is not None
    assert calls == ["turn_on", "turn_off"]
    assert host.accepting is True
    assert host._fatal_error is None
    assert await hass.config_entries.async_unload(entry.entry_id) is True
