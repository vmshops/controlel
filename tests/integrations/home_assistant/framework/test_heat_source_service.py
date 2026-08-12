import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
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
    CONF_HEAT_DEMAND_CONFIRMATION_DURATION,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_MINIMUM_HEATING_OFF_TIME,
    CONF_MINIMUM_HEATING_ON_TIME,
    CONF_TEMPERATURE_ENTITY_ID,
    DOMAIN,
)
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.heat_source import (
    HomeAssistantHeatSourcePort,
    HomeAssistantServiceCallError,
)
from custom_components.controlel.runtime_executor import HomeAssistantRuntimeExecutor


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


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
    hass.states.async_set("switch.boiler", "unavailable")
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)

    clock = MutableClock(datetime.now(UTC) + timedelta(seconds=1))
    with patch.object(component, "SystemClock", return_value=clock):
        assert await hass.config_entries.async_setup(entry.entry_id) is True
        await hass.async_block_till_done()

        host = entry.runtime_data.host
        assert host is not None
        assert calls == []
        clock.current += timedelta(seconds=30)
        await host.async_reevaluate()
        await hass.async_block_till_done()
        assert calls == ["turn_on", "turn_off"]
        assert host.accepting is True
        assert host._fatal_error is None
        assert await hass.config_entries.async_unload(entry.entry_id) is True


@pytest.mark.asyncio
async def test_manual_on_transition_establishes_minimum_on_before_correction(
    hass,
    entry_data,
) -> None:
    calls: list[str] = []
    temperature_entity_id = entry_data[CONF_TEMPERATURE_ENTITY_ID]
    entry_data.update(
        {
            CONF_HEAT_DEMAND_CONFIRMATION_DURATION: 0.0,
            CONF_MINIMUM_HEATING_ON_TIME: 60.0,
            CONF_MINIMUM_HEATING_OFF_TIME: 60.0,
        }
    )

    async def turn_off(call) -> None:
        calls.append(call.service)
        hass.states.async_set("switch.boiler", "off")

    hass.services.async_register("switch", "turn_off", turn_off)
    hass.states.async_set(
        temperature_entity_id,
        "22",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)
    clock = MutableClock(datetime.now(UTC))

    with patch.object(component, "SystemClock", return_value=clock):
        assert await hass.config_entries.async_setup(entry.entry_id) is True
        await hass.async_block_till_done()
        host = entry.runtime_data.host

        hass.states.async_set("switch.boiler", "on")
        source_state = hass.states.get("switch.boiler")
        assert source_state is not None
        changed_at = source_state.last_changed
        clock.current = changed_at + timedelta(microseconds=1)
        await hass.async_block_till_done()

        expected_deadline = changed_at + timedelta(seconds=60)
        assert calls == []
        assert host._reported_source_evidence.transition_at == changed_at
        assert host._runtime.source_control_state.active_lockout_type.value == "minimum_on"
        assert host._runtime.source_control_state.active_lockout_deadline == expected_deadline

        clock.current = expected_deadline
        await host.async_reevaluate()
        await hass.async_block_till_done()
        assert calls == ["turn_off"]

        assert await hass.config_entries.async_unload(entry.entry_id) is True


@pytest.mark.asyncio
async def test_manual_off_transition_establishes_minimum_off_before_corrective_enable(
    hass,
    entry_data,
) -> None:
    calls: list[str] = []
    temperature_entity_id = entry_data[CONF_TEMPERATURE_ENTITY_ID]
    entry_data.update(
        {
            CONF_HEAT_DEMAND_CONFIRMATION_DURATION: 0.0,
            CONF_MINIMUM_HEATING_ON_TIME: 60.0,
            CONF_MINIMUM_HEATING_OFF_TIME: 60.0,
        }
    )

    async def turn_on(call) -> None:
        calls.append(call.service)

    hass.services.async_register("switch", "turn_on", turn_on)
    hass.states.async_set("switch.boiler", "on")
    hass.states.async_set(
        temperature_entity_id,
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)
    clock = MutableClock(datetime.now(UTC))

    with patch.object(component, "SystemClock", return_value=clock):
        assert await hass.config_entries.async_setup(entry.entry_id) is True
        await hass.async_block_till_done()
        host = entry.runtime_data.host
        assert calls == []

        hass.states.async_set("switch.boiler", "off")
        source_state = hass.states.get("switch.boiler")
        assert source_state is not None
        changed_at = source_state.last_changed
        clock.current = changed_at + timedelta(microseconds=1)
        await hass.async_block_till_done()

        expected_deadline = changed_at + timedelta(seconds=60)
        assert calls == []
        assert host._reported_source_evidence.transition_at == changed_at
        assert host._runtime.source_control_state.active_lockout_type.value == "minimum_off"
        assert host._runtime.source_control_state.active_lockout_deadline == expected_deadline

        clock.current = expected_deadline
        await host.async_reevaluate()
        await hass.async_block_till_done()
        assert calls == ["turn_on"]
        assert await hass.config_entries.async_unload(entry.entry_id) is True
