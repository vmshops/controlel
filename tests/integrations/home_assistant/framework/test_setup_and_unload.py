from dataclasses import replace
from datetime import UTC, datetime
from threading import get_ident
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from pytest_homeassistant_custom_component.common import MockConfigEntry

import controlel.application.runtime.control_runtime_assembly as runtime_assembly_module
import custom_components.controlel as component
import custom_components.controlel.setup_write_websocket as setup_transport
from controlel.application.setup import ActiveReference
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.runtime_supervision import CommandAuthority, SupervisorPhase
from controlel.domain.source_control import ReportedSourceState, SourceOwnership
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.infrastructure.home_assistant import MODULE_ACTIVE_REFERENCES_KEY
from custom_components.controlel import ControlelEntryRuntime
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

    def record_runtime_started(self) -> None:
        self.operations.append("start")
        self.threads.append(get_ident())
        super().record_runtime_started()

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
        patch.object(runtime_assembly_module, "ControlRuntime", InstrumentedRuntime),
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

        def record_runtime_started(self) -> None:
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
        patch.object(runtime_assembly_module, "ControlRuntime", FailingRuntime),
        patch.object(component, "HomeAssistantControlelHost", CapturingHost),
    ):
        assert await component.async_setup_entry(hass, entry)

    host = hosts[0]
    runtime = FailingRuntime.instances[0]
    assert isinstance(entry.runtime_data, ControlelEntryRuntime)
    assert entry.runtime_data.host is None
    assert entry.runtime_data.module_errors["heating"] == "heating_lifecycle_failed:RuntimeError"
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

    assert await component.async_setup_entry(hass, entry)

    assert entry.runtime_data.host is None
    assert entry.runtime_data.module_errors["heating"] == "heating_lifecycle_failed:HomeAssistantConfigurationError"


def _water_active_reference() -> ActiveReference:
    return ActiveReference(
        environment_id="ha-installation-id",
        module_key="water_safety",
        module_instance_id="utility-water",
        canonical_revision_id="water-canonical-1",
        semantic_configuration_fingerprint="b" * 64,
        generation=1,
        committing_operation_id="water-attempt-1",
    )


def _water_activation_message(entry_id: str) -> dict[str, object]:
    return {
        "id": 7,
        "config_entry_id": entry_id,
        "module_key": "water_safety",
        "draft_id": "water-draft",
        "snapshot_id": "snapshot-1",
        "captured_at": datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        "report_id": "report-1",
        "notification_roles": [],
        "siren_roles": ["water_safety.siren.primary"],
        "preferred_area_id": "utility-room",
        "preferred_floor_id": None,
        "canonical_revision_id": "water-revision",
        "attempt_id": "attempt-1",
    }


@pytest.mark.asyncio
async def test_empty_entry_loads_shell_and_never_unloads_unforwarded_platforms(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    with (
        patch.object(component, "water_safety_core_available", return_value=False),
        patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()) as forward,
        patch.object(hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=True)) as unload,
    ):
        assert await component.async_setup_entry(hass, entry)
        assert entry.runtime_data.host is None
        assert entry.runtime_data.loaded_platforms == ()
        assert forward.await_count == 0

        assert await component.async_unload_entry(hass, entry)
        assert await component.async_unload_entry(hass, entry)
        assert unload.await_count == 0


@pytest.mark.asyncio
async def test_water_only_restart_does_not_construct_or_forward_heating(hass) -> None:
    water_host = AsyncMock()
    active = _water_active_reference()
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={MODULE_ACTIVE_REFERENCES_KEY: {"water_safety": active.model_dump(mode="json")}},
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.controlel.water_safety_activation."
            "WaterSafetyActivationService.async_start_from_active_reference",
            new=AsyncMock(return_value=water_host),
        ) as start_water,
        patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()) as forward,
    ):
        assert await component.async_setup_entry(hass, entry)

    assert entry.runtime_data.host is None
    assert entry.runtime_data.water_safety_host is water_host
    assert start_water.await_count == 1
    assert forward.await_count == 0


@pytest.mark.asyncio
async def test_heating_and_water_load_independently(hass, entry_data) -> None:
    water_host = AsyncMock()
    active = _water_active_reference()
    entry_data[MODULE_ACTIVE_REFERENCES_KEY] = {"water_safety": active.model_dump(mode="json")}
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.controlel.water_safety_activation."
        "WaterSafetyActivationService.async_start_from_active_reference",
        new=AsyncMock(return_value=water_host),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)

    assert entry.runtime_data.host is not None
    assert entry.runtime_data.water_safety_host is water_host
    assert entry.runtime_data.loaded_platforms == ("sensor", "binary_sensor")


@pytest.mark.asyncio
async def test_failed_water_restart_preserves_heating_and_reports_degraded_module(hass, entry_data) -> None:
    active = _water_active_reference()
    entry_data[MODULE_ACTIVE_REFERENCES_KEY] = {"water_safety": active.model_dump(mode="json")}
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.controlel.water_safety_activation."
        "WaterSafetyActivationService.async_start_from_active_reference",
        new=AsyncMock(side_effect=RuntimeError("water candidate failed")),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)

    assert entry.runtime_data.host is not None
    assert entry.runtime_data.water_safety_host is None
    assert entry.runtime_data.module_errors["water_safety"] == "water_safety_lifecycle_failed:RuntimeError"
    assert entry.runtime_data.loaded_platforms == ("sensor", "binary_sensor")


@pytest.mark.asyncio
async def test_empty_entry_can_activate_water_without_loading_heating(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    with patch(
        "custom_components.controlel.panel.async_register_controlel_panel",
        new=AsyncMock(),
    ):
        assert await component.async_setup_entry(hass, entry)

    candidate = AsyncMock()
    service = AsyncMock()
    service.validate_water_draft.return_value = {"status": "valid"}
    connection = Mock()
    with (
        patch.object(setup_transport, "water_safety_core_available", return_value=True),
        patch.object(setup_transport, "async_get_setup_service", new=AsyncMock(return_value=service)),
        patch(
            "custom_components.controlel.water_safety_activation."
            "WaterSafetyActivationService.activate_canonical_revision",
            new=AsyncMock(return_value=candidate),
        ),
    ):
        await setup_transport._activate_water_setup(
            hass,
            connection,
            _water_activation_message(entry.entry_id),
        )

    assert entry.runtime_data.host is None
    assert entry.runtime_data.water_safety_host is candidate
    assert entry.runtime_data.loaded_platforms == ()
    assert entry.runtime_data.frontend_api_unregister is not None
    connection.send_error.assert_not_called()
    connection.send_result.assert_called_once()


@pytest.mark.asyncio
async def test_failed_water_activation_preserves_shell_heating_and_previous_water(hass, entry_data) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.controlel.panel.async_register_controlel_panel",
        new=AsyncMock(),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)

    heating_host = entry.runtime_data.host
    previous_water_host = AsyncMock()
    entry.runtime_data.water_safety_host = previous_water_host
    frontend_api_unregister = entry.runtime_data.frontend_api_unregister
    service = AsyncMock()
    service.validate_water_draft.return_value = {"status": "valid"}
    connection = Mock()
    with (
        patch.object(setup_transport, "water_safety_core_available", return_value=True),
        patch.object(setup_transport, "async_get_setup_service", new=AsyncMock(return_value=service)),
        patch(
            "custom_components.controlel.water_safety_activation."
            "WaterSafetyActivationService.activate_canonical_revision",
            new=AsyncMock(side_effect=RuntimeError("candidate failed")),
        ),
    ):
        await setup_transport._activate_water_setup(
            hass,
            connection,
            _water_activation_message(entry.entry_id),
        )

    assert entry.runtime_data.host is heating_host
    assert entry.runtime_data.water_safety_host is previous_water_host
    assert entry.runtime_data.frontend_api_unregister is frontend_api_unregister
    previous_water_host.async_stop.assert_not_awaited()
    connection.send_result.assert_not_called()
    connection.send_error.assert_called_once_with(
        7,
        setup_transport.websocket_api.ERR_HOME_ASSISTANT_ERROR,
        "Water Safety activation failed; the previous configuration remains active",
    )
