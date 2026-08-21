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
from pytest_homeassistant_custom_component.common import MockConfigEntry

import controlel.application.runtime.control_runtime_assembly as runtime_assembly_module
import custom_components.controlel as component
from controlel.domain.value_objects.sensor_id import SensorId
from custom_components.controlel.const import (
    CONF_CONTROLLED_ENTITY_ID,
    CONF_DISABLE_SERVICE_DOMAIN,
    CONF_DISABLE_SERVICE_NAME,
    CONF_DISABLE_TARGET_ENTITY_ID,
    CONF_ENABLE_SERVICE_DOMAIN,
    CONF_ENABLE_SERVICE_NAME,
    CONF_ENABLE_TARGET_ENTITY_ID,
    CONF_HEAT_SOURCE_CONTROL_MODE,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_INDETERMINATE_GRACE_PERIOD_MINUTES,
    CONF_INDETERMINATE_TIMEOUT_ACTION,
    CONF_MAX_FUTURE_SKEW,
    CONF_PRIMARY_MEASUREMENT_MAX_AGE_MINUTES,
    CONF_SENSOR_ID,
    CONF_SENSOR_NAME,
    CONF_TARGET_TEMPERATURE,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_ZONE_ID,
    CONF_ZONE_NAME,
    CONTROL_MODE_CUSTOM,
    CONTROL_MODE_SIMPLE,
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


async def _submit_options(
    hass,
    entry,
    *,
    zone_name: str,
    sensor_name: str,
    temperature_entity_id: str,
    target_temperature: float,
    mode: str,
    controlled_entity_id: str | None,
    max_age_minutes: float,
    future_skew_seconds: float,
    grace_minutes: float,
    timeout_action: str,
    custom_bindings: dict[str, str] | None = None,
) -> None:
    initial = await hass.config_entries.options.async_init(entry.entry_id)
    basic = {
        CONF_ZONE_NAME: zone_name,
        CONF_SENSOR_NAME: sensor_name,
        CONF_TEMPERATURE_ENTITY_ID: temperature_entity_id,
        CONF_TARGET_TEMPERATURE: target_temperature,
        CONF_HEAT_SOURCE_CONTROL_MODE: mode,
    }
    if controlled_entity_id is not None:
        basic[CONF_CONTROLLED_ENTITY_ID] = controlled_entity_id
    advanced = await hass.config_entries.options.async_configure(
        initial["flow_id"],
        basic,
    )
    safety = {
        CONF_PRIMARY_MEASUREMENT_MAX_AGE_MINUTES: max_age_minutes,
        CONF_MAX_FUTURE_SKEW: future_skew_seconds,
        CONF_INDETERMINATE_GRACE_PERIOD_MINUTES: grace_minutes,
        CONF_INDETERMINATE_TIMEOUT_ACTION: timeout_action,
    }
    if custom_bindings is not None:
        safety.update(custom_bindings)
    result = await hass.config_entries.options.async_configure(
        advanced["flow_id"],
        safety,
    )
    assert result["type"].value == "create_entry"


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
async def test_repeated_options_updates_reload_once_and_leave_one_runtime(
    hass,
    entry_data,
    service_calls,
) -> None:
    ReloadRuntime.instances.clear()
    ReloadRuntime.lifecycle.clear()
    CapturingHost.instances.clear()
    first_entity = entry_data[CONF_TEMPERATURE_ENTITY_ID]
    second_entity = "sensor.upstairs_temperature"
    for entity_id, value in ((first_entity, "20"), (second_entity, "21")):
        hass.states.async_set(
            entity_id,
            value,
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

        await _submit_options(
            hass,
            entry,
            zone_name="Upstairs",
            sensor_name="Upstairs temperature",
            temperature_entity_id=second_entity,
            target_temperature=22.5,
            mode=CONTROL_MODE_SIMPLE,
            controlled_entity_id="switch.heat_pump",
            max_age_minutes=10,
            future_skew_seconds=15,
            grace_minutes=3,
            timeout_action="disable_heating",
        )
        await wait_until(lambda: len(ReloadRuntime.instances) == 2)
        await hass.async_block_till_done()
        second_host = entry.runtime_data.host

        await _submit_options(
            hass,
            entry,
            zone_name="Upstairs",
            sensor_name="Upstairs temperature",
            temperature_entity_id=second_entity,
            target_temperature=22.5,
            mode=CONTROL_MODE_CUSTOM,
            controlled_entity_id=None,
            max_age_minutes=10,
            future_skew_seconds=15,
            grace_minutes=3,
            timeout_action="enable_heating",
            custom_bindings={
                CONF_ENABLE_SERVICE_DOMAIN: "switch",
                CONF_ENABLE_SERVICE_NAME: "turn_on",
                CONF_ENABLE_TARGET_ENTITY_ID: "switch.heat_pump",
                CONF_DISABLE_SERVICE_DOMAIN: "switch",
                CONF_DISABLE_SERVICE_NAME: "turn_off",
                CONF_DISABLE_TARGET_ENTITY_ID: "switch.backup_boiler",
            },
        )
        await wait_until(lambda: len(ReloadRuntime.instances) == 3)
        await hass.async_block_till_done()
        third_host = entry.runtime_data.host

        await _submit_options(
            hass,
            entry,
            zone_name="Upstairs",
            sensor_name="Renamed measurement",
            temperature_entity_id=second_entity,
            target_temperature=21.5,
            mode=CONTROL_MODE_SIMPLE,
            controlled_entity_id="switch.backup_boiler",
            max_age_minutes=15,
            future_skew_seconds=30,
            grace_minutes=2,
            timeout_action="disable_heating",
        )
        await wait_until(lambda: len(ReloadRuntime.instances) == 4)
        await hass.async_block_till_done()
        final_host = entry.runtime_data.host

        assert entry.title == "Upstairs"
        assert entry.data[CONF_SENSOR_ID] == "living_room_temperature"
        assert entry.data[CONF_ZONE_ID] == "living_room"
        assert entry.runtime_data.config.sensor_name == "Renamed measurement"
        assert entry.runtime_data.config.temperature_entity_id == second_entity
        assert entry.runtime_data.config.target_temperature.value == 21.5
        assert entry.runtime_data.config.primary_measurement_max_age.total_seconds() == 900
        assert entry.runtime_data.config.max_future_skew.total_seconds() == 30
        assert entry.runtime_data.config.indeterminate_grace_period.total_seconds() == 120
        assert entry.runtime_data.config.heat_source_control_mode == CONTROL_MODE_SIMPLE
        assert entry.runtime_data.config.controlled_entity_id == "switch.backup_boiler"
        assert first_host is not None and first_host.stopped
        assert second_host is not None and second_host.stopped
        assert third_host is not None and third_host.stopped
        assert final_host is not None and final_host.accepting
        assert sum(host.accepting for host in CapturingHost.instances) == 1
        assert len(ReloadRuntime.instances) == 4

        assert await hass.config_entries.async_unload(entry.entry_id)
        assert final_host.stopped

        assert await hass.config_entries.async_setup(entry.entry_id)
        restarted_host = entry.runtime_data.host
        assert restarted_host is not None and restarted_host.accepting
        assert entry.runtime_data.config.sensor_name == "Renamed measurement"
        assert entry.runtime_data.config.sensor_id == SensorId("living_room_temperature")
        assert await hass.config_entries.async_unload(entry.entry_id)
        await component.async_remove_entry(hass, entry)


@pytest.mark.asyncio
async def test_invalid_options_are_rejected_without_runtime_reload(
    hass,
    entry_data,
    service_calls,
) -> None:
    ReloadRuntime.instances.clear()
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20",
        {
            ATTR_DEVICE_CLASS: "temperature",
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data, options={})
    entry.add_to_hass(hass)

    with patch.object(runtime_assembly_module, "ControlRuntime", ReloadRuntime):
        assert await hass.config_entries.async_setup(entry.entry_id)
        initial = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            initial["flow_id"],
            {
                CONF_ZONE_NAME: "Living room",
                CONF_SENSOR_NAME: "Living room temperature",
                CONF_TEMPERATURE_ENTITY_ID: "sensor.not_temperature",
                CONF_TARGET_TEMPERATURE: 21.0,
                CONF_HEAT_SOURCE_CONTROL_MODE: CONTROL_MODE_SIMPLE,
                CONF_CONTROLLED_ENTITY_ID: "switch.boiler",
            },
        )

        assert result["type"].value == "form"
        assert result["errors"] == {CONF_TEMPERATURE_ENTITY_ID: "not_temperature_sensor"}
        assert len(ReloadRuntime.instances) == 1
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
