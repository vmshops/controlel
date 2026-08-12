from dataclasses import replace
from datetime import UTC, datetime
from threading import get_ident
from unittest.mock import patch

import pytest
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.runtime_supervision import CommandAuthority, SupervisorPhase
from controlel.domain.source_control import ReportedSourceState, SourceOwnership
from controlel.domain.value_objects.sensor_id import SensorId
from custom_components.controlel import ControlelEntryRuntime
from custom_components.controlel.config import HomeAssistantConfigurationError
from custom_components.controlel.const import (
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_MINIMUM_HEATING_OFF_TIME,
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
    assert host._runtime_supervisor is not None
    assert runtime.source_ownership is SourceOwnership.CONTROLEL_OWNED
    assert runtime.reported_source_evidence is not None
    assert runtime.reported_source_evidence.state is ReportedSourceState.DISABLED
    assert runtime.operations[:2] == ["start", "temperature"]
    assert len(set(runtime.threads)) == 1
    assert runtime.threads[0] != loop_thread
    measurement = runtime.state_store.get_latest(SensorId("living_room_temperature"))
    assert measurement is not None
    assert measurement.timestamp is initial_state.last_updated
    assert service_calls == []

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    assert host.accepting is False
    assert host.stopped is True
    assert host._executor.closed is True
    assert runtime.operations[-1] == "stop"
    assert runtime._scheduled_handle is None


@pytest.mark.asyncio
async def test_reported_source_and_supervised_fatal_recovery_use_core_authority(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry_data[CONF_INDETERMINATE_GRACE_PERIOD] = 0.0
    entry_data[CONF_MINIMUM_HEATING_OFF_TIME] = 0.0
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "unknown",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    host = entry.runtime_data.host
    assert host is not None
    supervisor = host._runtime_supervisor
    assert supervisor is not None
    original_runtime = host._runtime

    assert supervisor.state.phase is SupervisorPhase.NORMAL
    assert original_runtime.reported_source_evidence.state is ReportedSourceState.DISABLED
    assert service_calls == []

    hass.states.async_set("switch.boiler", "on")
    await hass.async_block_till_done()
    assert supervisor._reported_evidence.state is ReportedSourceState.ENABLED
    assert host._runtime.reported_source_evidence.state is ReportedSourceState.ENABLED

    for raw, expected in (
        ("unknown", ReportedSourceState.UNKNOWN),
        ("unavailable", ReportedSourceState.UNAVAILABLE),
    ):
        hass.states.async_set("switch.boiler", raw)
        await hass.async_block_till_done()
        assert supervisor._reported_evidence.state is expected
        assert host._runtime.reported_source_evidence.state is expected

    host.request_fatal_shutdown(RuntimeError("normalized-only fatal"))
    await hass.async_block_till_done()
    assert host.accepting is True
    assert host.stopped is False
    assert original_runtime._stopped is True
    assert supervisor.state.phase is SupervisorPhase.FAILSAFE
    assert supervisor.state.command_authority is CommandAuthority.FAILSAFE
    assert service_calls == [("turn_off", {"entity_id": "switch.boiler"})]

    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "19",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    await hass.async_block_till_done()
    assert service_calls[-1] == ("turn_on", {"entity_id": "switch.boiler"})

    def make_restart_eligible():
        supervisor.state = replace(supervisor.state, next_restart_at=datetime.min.replace(tzinfo=UTC))
        return supervisor.request_restart()

    recovered = await host._executor.async_submit(make_restart_eligible)
    assert recovered is host._runtime
    assert recovered is not original_runtime
    assert supervisor.state.phase is SupervisorPhase.NORMAL
    assert supervisor.state.command_authority is CommandAuthority.NORMAL

    diagnostics = host.runtime_supervision_diagnostics()
    assert diagnostics is not None
    assert diagnostics["supervisor_state"] == "normal"
    assert diagnostics["command_authority"] == "normal"
    assert diagnostics["restart_attempt_count"] == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert host._unsubscribe_source is None
    assert host._executor.closed is True


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
