import asyncio

import pytest

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
from custom_components.controlel.event_loop_bridge import (
    EventLoopBridgeThreadError,
    HomeAssistantEventLoopBridge,
)
from custom_components.controlel.heat_source import (
    HomeAssistantHeatSourcePort,
    HomeAssistantServiceCallError,
)
from custom_components.controlel.runtime_executor import HomeAssistantRuntimeExecutor


class FakeServices:
    def __init__(self):
        self.calls: list[tuple[object, ...]] = []
        self.error: Exception | None = None
        self.on_call = None

    async def async_call(
        self,
        domain,
        service,
        service_data=None,
        blocking=False,
        *,
        target=None,
    ):
        self.calls.append((domain, service, service_data, blocking, target))
        if self.on_call is not None:
            self.on_call()
        if self.error is not None:
            raise self.error


class FakeHass:
    def __init__(self):
        self.services = FakeServices()


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
def test_maps_action_to_blocking_service_call(action: HeatingAction, expected_service: str):
    async def scenario():
        hass = FakeHass()
        successes: list[None] = []
        executor = HomeAssistantRuntimeExecutor()
        port = HomeAssistantHeatSourcePort(
            hass,
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            binding(),
            lambda: successes.append(None),
        )
        await executor.async_submit(port.execute, command(action))
        await executor.async_close()
        return hass.services.calls, successes

    calls, successes = asyncio.run(scenario())

    assert calls == [
        (
            "switch",
            expected_service,
            {},
            True,
            {"entity_id": "switch.boiler"},
        )
    ]
    assert successes == [None]


def test_service_failure_preserves_context_and_original_exception():
    async def scenario():
        hass = FakeHass()
        error = RuntimeError("service failed")
        hass.services.error = error
        executor = HomeAssistantRuntimeExecutor()
        port = HomeAssistantHeatSourcePort(
            hass,
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            binding(),
            lambda: None,
        )
        with pytest.raises(HomeAssistantServiceCallError) as raised:
            await executor.async_submit(
                port.execute,
                command(HeatingAction.ENABLE_HEATING),
            )
        await executor.async_close()
        return raised.value, error

    raised, original = asyncio.run(scenario())

    assert raised.action is HeatingAction.ENABLE_HEATING
    assert raised.domain == "switch"
    assert raised.service == "turn_on"
    assert raised.target_entity_id == "switch.boiler"
    assert raised.original_error is original
    assert raised.__cause__ is original


def test_service_failure_does_not_update_applied_core_state():
    async def scenario():
        hass = FakeHass()
        hass.services.error = RuntimeError("service failed")
        executor = HomeAssistantRuntimeExecutor()
        state_store = HeatSourceStateStore()
        port = HomeAssistantHeatSourcePort(
            hass,
            HomeAssistantEventLoopBridge(asyncio.get_running_loop()),
            binding(),
            lambda: None,
        )
        dispatcher = HeatSourceCommandDispatcher(port, state_store)
        with pytest.raises(HomeAssistantServiceCallError):
            await executor.async_submit(
                dispatcher.dispatch,
                command(HeatingAction.ENABLE_HEATING),
            )
        await executor.async_close()
        return state_store.get()

    assert asyncio.run(scenario()) is None


def test_blocking_bridge_rejects_event_loop_thread():
    async def scenario():
        bridge = HomeAssistantEventLoopBridge(asyncio.get_running_loop())

        async def operation():
            return None

        with pytest.raises(EventLoopBridgeThreadError):
            bridge.run_coroutine(operation)

    asyncio.run(scenario())


def test_service_caused_state_event_can_queue_without_waiting_for_worker():
    async def scenario():
        hass = FakeHass()
        executor = HomeAssistantRuntimeExecutor()
        bridge = HomeAssistantEventLoopBridge(asyncio.get_running_loop())
        port = HomeAssistantHeatSourcePort(hass, bridge, binding(), lambda: None)
        order: list[str] = []
        queued_tasks: list[asyncio.Task[object]] = []

        def queue_state_event():
            order.append("state_event_queued")
            queued_tasks.append(
                asyncio.create_task(executor.async_submit(lambda: order.append("state_event_processed")))
            )

        hass.services.on_call = queue_state_event

        def execute():
            order.append("command_started")
            port.execute(command(HeatingAction.ENABLE_HEATING))
            order.append("command_finished")

        await executor.async_submit(execute)
        await asyncio.gather(*queued_tasks)
        await executor.async_close()
        return order

    assert asyncio.run(scenario()) == [
        "command_started",
        "state_event_queued",
        "command_finished",
        "state_event_processed",
    ]
