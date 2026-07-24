import asyncio
from threading import Event as ThreadEvent
from threading import get_ident
from unittest.mock import patch

import pytest
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    EVENT_HOMEASSISTANT_STOP,
    UnitOfTemperature,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.domain.value_objects.sensor_id import SensorId
from custom_components.controlel.const import (
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_TEMPERATURE_ENTITY_ID,
    DOMAIN,
)
from custom_components.controlel.runtime_executor import HomeAssistantRuntimeExecutor

from .test_state_ingestion import RecordingRuntime, make_host, wait_until


class ReloadRuntime(ControlRuntime):
    instances: list["ReloadRuntime"] = []
    lifecycle: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.instance_number = len(self.__class__.instances)
        self.__class__.instances.append(self)
        self.__class__.lifecycle.append(f"construct-{self.instance_number}")

    def stop(self) -> None:
        self.__class__.lifecycle.append(f"stop-{self.instance_number}")
        super().stop()


class CapturingExecutor(HomeAssistantRuntimeExecutor):
    instances: list["CapturingExecutor"] = []

    def __init__(self) -> None:
        super().__init__()
        self.__class__.instances.append(self)


class CapturingHost(component.HomeAssistantControlelHost):
    instances: list["CapturingHost"] = []

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.__class__.instances.append(self)


@pytest.mark.asyncio
async def test_real_reload_fully_unloads_then_constructs_fresh_in_memory_runtime(
    hass,
    entry_data,
    service_calls,
) -> None:
    ReloadRuntime.instances.clear()
    ReloadRuntime.lifecycle.clear()
    CapturingExecutor.instances.clear()
    CapturingHost.instances.clear()
    entry_data[CONF_INDETERMINATE_GRACE_PERIOD] = 0.0
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)

    with (
        patch.object(component, "ControlRuntime", ReloadRuntime),
        patch.object(component, "HomeAssistantRuntimeExecutor", CapturingExecutor),
        patch.object(component, "HomeAssistantControlelHost", CapturingHost),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is True
        first_host = entry.runtime_data.host
        first_runtime = ReloadRuntime.instances[0]
        first_executor = CapturingExecutor.instances[0]

        assert await hass.config_entries.async_reload(entry.entry_id) is True
        second_host = entry.runtime_data.host
        second_runtime = ReloadRuntime.instances[1]
        second_executor = CapturingExecutor.instances[1]

        assert await hass.config_entries.async_unload(entry.entry_id) is True

    assert first_host is not second_host
    assert first_runtime is not second_runtime
    assert first_executor is not second_executor
    assert ReloadRuntime.lifecycle.index("stop-0") < ReloadRuntime.lifecycle.index("construct-1")
    assert first_host.stopped is True
    assert first_executor.closed is True
    assert first_runtime._stopped is True
    assert second_host.stopped is True
    assert second_executor.closed is True
    assert second_runtime._stopped is True
    assert first_runtime.state_store is not second_runtime.state_store
    assert first_runtime.zone_demand_store is not second_runtime.zone_demand_store
    assert first_runtime.heat_demand_safety_state_store is not second_runtime.heat_demand_safety_state_store
    assert first_runtime.heat_source_state_store is not second_runtime.heat_source_state_store
    first_measurement = first_runtime.state_store.get_latest(SensorId("living_room_temperature"))
    second_measurement = second_runtime.state_store.get_latest(SensorId("living_room_temperature"))
    assert first_measurement is not None
    assert second_measurement is not None
    assert first_measurement is not second_measurement
    assert first_measurement.timestamp == second_measurement.timestamp
    assert [service for service, _ in service_calls] == ["turn_on", "turn_on"]


@pytest.mark.asyncio
async def test_stop_rejects_new_events_waits_for_accepted_work_then_stops_on_worker(hass) -> None:
    hass.states.async_set("sensor.living_room_temperature", "unknown")
    runtime = RecordingRuntime()
    entered = ThreadEvent()
    release = ThreadEvent()
    runtime.process_gates[20.0] = (entered, release)
    host = make_host(hass, runtime)
    await host.async_initialize()
    loop_thread = get_ident()

    hass.states.async_set(
        "sensor.living_room_temperature",
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    await asyncio.to_thread(entered.wait)
    stop_task = hass.async_create_task(host.async_stop())
    await wait_until(lambda: host.accepting is False)
    hass.states.async_set(
        "sensor.living_room_temperature",
        "21",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    release.set()
    await stop_task
    await hass.async_block_till_done()

    assert [
        value.value.value if operation == "temperature" else operation for operation, value in runtime.operations
    ] == ["start", 20.0, "stop"]
    assert len(set(runtime.threads)) == 1
    assert runtime.threads[0] != loop_thread
    assert host.stopped is True
    assert host._executor.closed is True

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    hass.states.async_set(
        "sensor.living_room_temperature",
        "22",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    await hass.async_block_till_done()
    assert [operation for operation, _ in runtime.operations].count("stop") == 1


@pytest.mark.asyncio
async def test_real_home_assistant_stop_event_uses_idempotent_host_stop_path(hass) -> None:
    runtime = RecordingRuntime()
    host = make_host(hass, runtime)
    await host.async_initialize()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await wait_until(lambda: host.stopped)
    await host.async_stop()

    assert host.accepting is False
    assert host._executor.closed is True
    assert [operation for operation, _ in runtime.operations].count("stop") == 1
