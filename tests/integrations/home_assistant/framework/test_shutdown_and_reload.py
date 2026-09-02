import asyncio
from threading import Event as ThreadEvent
from threading import get_ident
from unittest.mock import patch

import pytest
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    EVENT_HOMEASSISTANT_STOP,
    UnitOfTemperature,
)
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import controlel.application.runtime.control_runtime_assembly as runtime_assembly_module
import custom_components.controlel as component
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.infrastructure.home_assistant import ACTIVE_REFERENCE_KEY
from custom_components.controlel import config_flow as cf
from custom_components.controlel.const import (
    CONF_DISABLE_TARGET_ENTITY_ID,
    CONF_ENABLE_TARGET_ENTITY_ID,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_TEMPERATURE_ENTITY_ID,
    DOMAIN,
)
from custom_components.controlel.runtime_executor import HomeAssistantRuntimeExecutor

from .test_state_ingestion import RecordingRuntime, make_host, wait_until

ControlRuntime = component.ControlRuntime


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


def _defaults(result) -> dict[str, object]:
    values: dict[str, object] = {}
    for marker in result["data_schema"].schema:
        suggested = marker.description.get("suggested_value") if marker.description else None
        if suggested is not None:
            values[marker.schema] = suggested
            continue
        if marker.default is None:
            continue
        try:
            values[marker.schema] = marker.default()
        except (TypeError, ValueError):
            pass
    return values


def _register_entry_bindings(hass) -> tuple[str, str]:
    registry = er.async_get(hass)
    sensor = registry.async_get_or_create(
        "sensor",
        "shutdown-reload-test",
        "living-room-temperature",
        suggested_object_id="living_room_temperature",
        original_device_class="temperature",
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    source = registry.async_get_or_create(
        "switch",
        "shutdown-reload-test",
        "boiler",
        suggested_object_id="boiler",
    )
    hass.states.async_set(source.entity_id, "off")
    return sensor.entity_id, source.entity_id


async def _choose(hass, result, step_id: str):
    return await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"next_step_id": step_id},
    )


async def _open_heating_menu(hass, entry):
    hub = await hass.config_entries.options.async_init(entry.entry_id)
    return await _choose(hass, hub, "heating")


async def _save_and_prepare_activation(hass, result):
    assert result["step_id"] == "heating"
    review = await _choose(hass, result, "heating_review")
    assert review["step_id"] == "heating_review"
    return await hass.config_entries.options.async_configure(review["flow_id"], {})


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
        patch.object(runtime_assembly_module, "ControlRuntime", ReloadRuntime),
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
    assert service_calls == []


@pytest.mark.asyncio
async def test_explicit_canonical_activations_reload_once_and_leave_one_runtime(
    hass,
    entry_data,
    service_calls,
) -> None:
    ReloadRuntime.instances.clear()
    ReloadRuntime.lifecycle.clear()
    CapturingHost.instances.clear()
    first_entity, source_entity = _register_entry_bindings(hass)
    entry_data[CONF_TEMPERATURE_ENTITY_ID] = first_entity
    entry_data[CONF_ENABLE_TARGET_ENTITY_ID] = source_entity
    entry_data[CONF_DISABLE_TARGET_ENTITY_ID] = source_entity
    hass.states.async_set(
        first_entity,
        "20",
        {
            ATTR_DEVICE_CLASS: "temperature",
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Living room",
        data=entry_data,
        options={},
    )
    entry.add_to_hass(hass)

    with (
        patch.object(runtime_assembly_module, "ControlRuntime", ReloadRuntime),
        patch.object(component, "HomeAssistantControlelHost", CapturingHost),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        first_host = entry.runtime_data.host

        initial = await _open_heating_menu(hass, entry)
        convert = await _choose(hass, initial, "convert_legacy")
        review = await hass.config_entries.options.async_configure(convert["flow_id"], {})
        activate = await _save_and_prepare_activation(hass, review)
        await hass.config_entries.options.async_configure(activate["flow_id"], {})
        await wait_until(lambda: len(ReloadRuntime.instances) == 2)
        await hass.async_block_till_done()
        second_host = entry.runtime_data.host

        initial = await _open_heating_menu(hass, entry)
        edit = await _choose(hass, initial, "edit_active")
        assert edit["step_id"] == "heating"
        zone_form = await _choose(hass, edit, "zone")
        zone = _defaults(zone_form)
        zone[cf.TARGET_TEMPERATURE] = 21.5
        edit = await hass.config_entries.options.async_configure(zone_form["flow_id"], zone)
        activate = await _save_and_prepare_activation(hass, edit)
        await hass.config_entries.options.async_configure(activate["flow_id"], {})
        await wait_until(lambda: len(ReloadRuntime.instances) == 3)
        await hass.async_block_till_done()
        final_host = entry.runtime_data.host

        assert set(entry.data) == {ACTIVE_REFERENCE_KEY}
        assert entry.options == {}
        assert entry.runtime_data.config.sensor_name == "Living room temperature"
        assert entry.runtime_data.config.temperature_entity_id == first_entity
        assert entry.runtime_data.config.target_temperature.value == 21.5
        assert first_host is not None and first_host.stopped
        assert second_host is not None and second_host.stopped
        assert final_host is not None and final_host.accepting
        assert sum(host.accepting for host in CapturingHost.instances) == 1
        assert len(ReloadRuntime.instances) == 3

        assert await hass.config_entries.async_unload(entry.entry_id)
        assert final_host.stopped

        assert await hass.config_entries.async_setup(entry.entry_id)
        restarted_host = entry.runtime_data.host
        assert restarted_host is not None and restarted_host.accepting
        assert entry.runtime_data.config.sensor_name == "Living room temperature"
        assert entry.runtime_data.config.sensor_id == SensorId("living_room_temperature")
        assert await hass.config_entries.async_unload(entry.entry_id)
        await component.async_remove_entry(hass, entry)


@pytest.mark.asyncio
async def test_invalid_canonical_draft_edit_does_not_reload_runtime(
    hass,
    entry_data,
    service_calls,
) -> None:
    ReloadRuntime.instances.clear()
    sensor_entity, source_entity = _register_entry_bindings(hass)
    entry_data[CONF_TEMPERATURE_ENTITY_ID] = sensor_entity
    entry_data[CONF_ENABLE_TARGET_ENTITY_ID] = source_entity
    entry_data[CONF_DISABLE_TARGET_ENTITY_ID] = source_entity
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20",
        {
            ATTR_DEVICE_CLASS: "temperature",
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    hass.states.async_set("sensor.not_temperature", "20")
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data, options={})
    entry.add_to_hass(hass)

    with patch.object(runtime_assembly_module, "ControlRuntime", ReloadRuntime):
        assert await hass.config_entries.async_setup(entry.entry_id)
        initial = await _open_heating_menu(hass, entry)
        convert = await _choose(hass, initial, "convert_legacy")
        result = await hass.config_entries.options.async_configure(convert["flow_id"], {})
        assert result["step_id"] == "heating"
        sensor_form = await _choose(hass, result, "sensor")
        sensor = _defaults(sensor_form)
        sensor[cf.TEMPERATURE_ENTITY] = "sensor.not_temperature"
        result = await hass.config_entries.options.async_configure(sensor_form["flow_id"], sensor)

        assert result["step_id"] == "sensor"
        assert result["errors"] == {"base": "invalid_configuration"}
        assert len(ReloadRuntime.instances) == 1
        assert ACTIVE_REFERENCE_KEY not in entry.data
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_stop_rejects_new_events_waits_for_accepted_work_then_stops_on_worker(hass) -> None:
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
