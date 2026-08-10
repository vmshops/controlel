from threading import get_ident
from unittest.mock import patch

import pytest
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.value_objects.sensor_id import SensorId
from custom_components.controlel import ControlelEntryRuntime
from custom_components.controlel.config import HomeAssistantConfigurationError
from custom_components.controlel.const import (
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_TEMPERATURE_ENTITY_ID,
    DOMAIN,
)

ControlRuntime = component.ControlRuntime


class InstrumentedRuntime(ControlRuntime):
    instances: list["InstrumentedRuntime"] = []

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.operations: list[str] = []
        self.threads: list[int] = []
        self.__class__.instances.append(self)

    def process_temperature(self, measurement):
        self.operations.append("temperature")
        self.threads.append(get_ident())
        return super().process_temperature(measurement)

    def start(self):
        self.operations.append("start")
        self.threads.append(get_ident())
        return super().start()

    def stop(self) -> None:
        self.operations.append("stop")
        self.threads.append(get_ident())
        super().stop()


@pytest.mark.asyncio
async def test_real_setup_initializes_once_starts_then_processes_snapshot_and_unloads(
    hass,
    entry_data,
    service_calls,
) -> None:
    InstrumentedRuntime.instances.clear()
    entry_data[CONF_INDETERMINATE_GRACE_PERIOD] = 0.0
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    initial_state = hass.states.get(entry_data[CONF_TEMPERATURE_ENTITY_ID])
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data=entry_data)
    entry.add_to_hass(hass)
    loop_thread = get_ident()

    with (
        patch.object(component, "SensorRepository", wraps=SensorRepository) as sensor_repositories,
        patch.object(component, "ZoneRepository", wraps=ZoneRepository) as zone_repositories,
        patch.object(component, "ControlRuntime", InstrumentedRuntime),
        patch.object(
            component.HomeAssistantControlelHost,
            "async_initialize",
            autospec=True,
            wraps=component.HomeAssistantControlelHost.async_initialize,
        ) as initialize,
    ):
        assert not hasattr(entry, "runtime_data")
        assert await hass.config_entries.async_setup(entry.entry_id) is True

    assert isinstance(entry.runtime_data, ControlelEntryRuntime)
    host = entry.runtime_data.host
    assert host is not None
    runtime = InstrumentedRuntime.instances[0]
    assert sensor_repositories.call_count == 1
    assert zone_repositories.call_count == 1
    assert len(InstrumentedRuntime.instances) == 1
    assert initialize.call_count == 1
    assert host._executor._executor._max_workers == 1
    assert runtime.operations[:2] == ["start", "temperature"]
    assert len(set(runtime.threads)) == 1
    assert runtime.threads[0] != loop_thread
    measurement = runtime.state_store.get_latest(SensorId("living_room_temperature"))
    assert measurement is not None
    assert measurement.timestamp is initial_state.last_updated
    assert service_calls == [
        (
            "turn_on",
            {"entity_id": "switch.boiler"},
        )
    ]

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    assert host.accepting is False
    assert host.stopped is True
    assert host._executor.closed is True
    assert runtime.operations[-1] == "stop"
    assert runtime._scheduled_handle is None


@pytest.mark.asyncio
async def test_partial_setup_failure_cleans_every_constructed_resource_and_preserves_error(
    hass,
    entry_data,
    service_calls,
) -> None:
    class FailingRuntime(InstrumentedRuntime):
        instances: list["FailingRuntime"] = []

        def start(self):
            self.operations.append("start")
            self.threads.append(get_ident())
            raise RuntimeError("demonstrated setup failure")

    hosts = []

    class CapturingHost(component.HomeAssistantControlelHost):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            hosts.append(self)

    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)

    with (
        patch.object(component, "ControlRuntime", FailingRuntime),
        patch.object(component, "HomeAssistantControlelHost", CapturingHost),
        pytest.raises(RuntimeError, match="demonstrated setup failure"),
    ):
        await component.async_setup_entry(hass, entry)

    host = hosts[0]
    runtime = FailingRuntime.instances[0]
    assert not hasattr(entry, "runtime_data")
    assert host.accepting is False
    assert host.stopped is True
    assert host._executor.closed is True
    assert runtime.operations == ["start", "stop"]

    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "19",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    await hass.async_block_till_done()
    assert runtime.operations == ["start", "stop"]


@pytest.mark.asyncio
async def test_invalid_stored_configuration_is_not_classified_as_transient(hass, entry_data) -> None:
    entry_data["primary_measurement_max_age"] = 0
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)

    with pytest.raises(HomeAssistantConfigurationError):
        await component.async_setup_entry(hass, entry)

    assert not hasattr(entry, "runtime_data")
