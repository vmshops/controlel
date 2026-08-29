"""Real Home Assistant transport tests for the read-only Frontend API v1 bridge."""

import json

import pytest
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from pytest_homeassistant_custom_component.common import MockConfigEntry

from controlel.frontend_api.v1 import (
    MissingConfigurationEvidenceV1,
    ScopeV1,
    SetupEvidenceV1,
)
from custom_components.controlel.const import (
    CONF_HEAT_DEMAND_CONFIRMATION_DURATION,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_MINIMUM_HEATING_OFF_TIME,
    CONF_MINIMUM_HEATING_ON_TIME,
    CONF_TEMPERATURE_ENTITY_ID,
    DOMAIN,
)
from custom_components.controlel.frontend_api import (
    _command_outcome,
    _event_command_outcome,
    create_frontend_api_provider_v1,
)
from custom_components.controlel.frontend_api_websocket import (
    FRONTEND_API_V1_DIAGNOSTICS,
    FRONTEND_API_V1_HEATING,
    FRONTEND_API_V1_OVERVIEW,
    FRONTEND_API_V1_SETUP,
    FrontendApiRegistryV1,
    register_frontend_api_provider_v1,
)
from custom_components.controlel.operational import CommandOutcome


async def _read(client, command: str, entry_id: str) -> dict[str, object]:
    await client.send_json_auto_id({"type": command, "config_entry_id": entry_id})
    response = await client.receive_json()
    assert response["success"] is True
    return response["result"]


def test_registry_supports_multiple_entries_and_stale_safe_cleanup() -> None:
    registry = FrontendApiRegistryV1()
    first = object()
    replacement = object()
    second = object()

    unregister_first = registry.register("entry-1", first)  # type: ignore[arg-type]
    unregister_second = registry.register("entry-2", second)  # type: ignore[arg-type]
    unregister_replacement = registry.register("entry-1", replacement)  # type: ignore[arg-type]

    unregister_first()
    assert registry.get("entry-1") is replacement
    assert registry.get("entry-2") is second
    unregister_second()
    unregister_replacement()
    assert registry.providers == {}


def test_bridge_preserves_deferred_and_held_current_and_event_outcomes() -> None:
    assert _command_outcome(CommandOutcome.DEFERRED) == "deferred"
    assert _command_outcome(CommandOutcome.HELD) == "held"
    assert _event_command_outcome("deferred") == "deferred"
    assert _event_command_outcome("held") == "held"


@pytest.mark.asyncio
async def test_authenticated_reads_use_real_evidence_without_control_mutation(
    hass,
    hass_ws_client,
    entry_data,
    service_calls,
) -> None:
    entry_data.update(
        {
            CONF_HEAT_DEMAND_CONFIRMATION_DURATION: 0.0,
            CONF_INDETERMINATE_GRACE_PERIOD: 0.0,
            CONF_MINIMUM_HEATING_ON_TIME: 0.0,
            CONF_MINIMUM_HEATING_OFF_TIME: 0.0,
        }
    )
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "22",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    host = entry.runtime_data.host
    assert host is not None
    client = await hass_ws_client(hass)

    before = (
        host.snapshot_source.current.revision,
        host.snapshot_source.total_trace_records,
        host.operational_event_diagnostics()["total_emitted"],
        tuple(service_calls),
    )
    overview = await _read(client, FRONTEND_API_V1_OVERVIEW, entry.entry_id)
    heating = await _read(client, FRONTEND_API_V1_HEATING, entry.entry_id)
    diagnostics = await _read(client, FRONTEND_API_V1_DIAGNOSTICS, entry.entry_id)
    setup = await _read(client, FRONTEND_API_V1_SETUP, entry.entry_id)
    after = (
        host.snapshot_source.current.revision,
        host.snapshot_source.total_trace_records,
        host.operational_event_diagnostics()["total_emitted"],
        tuple(service_calls),
    )

    assert overview["frontend_api_version"] == 1
    assert overview["system"]["status"] == "active"
    assert overview["modules"] == [
        {"module_id": "heating", "status": "active", "reason": None},
        {"module_id": "water_safety", "status": "inactive", "reason": "water_safety_not_configured"},
    ]
    assert heating["zones"][0]["zone_id"] == entry_data["zone_id"]
    assert heating["zones"][0]["current_temperature_c"] == 22.0
    assert heating["zones"][0]["measurement_state"] == "fresh"
    assert heating["building"]["heat_source"]["reported_state"] == "DISABLED"
    assert heating["building"]["heat_source"]["physical_state"] == "unknown"
    assert diagnostics["health"]["event_stream"]["total_emitted"] >= 1
    assert setup["readiness"] == {"state": "ready", "reason_code": None}
    assert before == after

    serialized = json.dumps((overview, heating, diagnostics, setup))
    assert "entity_id" not in serialized
    assert entry_data[CONF_TEMPERATURE_ENTITY_ID] not in serialized
    assert "switch.boiler" not in serialized


@pytest.mark.asyncio
async def test_unknown_heating_and_incomplete_setup_remain_explicit(
    hass,
    hass_ws_client,
    entry_data,
    service_calls,
) -> None:
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
    client = await hass_ws_client(hass)

    heating = await _read(client, FRONTEND_API_V1_HEATING, entry.entry_id)
    assert heating["zones"][0]["current_temperature_c"] is None
    assert heating["zones"][0]["measurement_state"] == "missing"
    assert heating["zones"][0]["demand_state"] == "indeterminate"

    unregister = register_frontend_api_provider_v1(
        hass,
        entry.entry_id,
        create_frontend_api_provider_v1(
            host,
            setup_source=lambda: SetupEvidenceV1(
                state="incomplete",
                reason_code="zone_primary_sensor_missing",
                missing_configuration=(
                    MissingConfigurationEvidenceV1(
                        code="zone_primary_sensor_missing",
                        scope=ScopeV1(type="zone", zone_id=entry_data["zone_id"]),
                        severity="error",
                    ),
                ),
            ),
        ),
    )
    setup = await _read(client, FRONTEND_API_V1_SETUP, entry.entry_id)
    assert setup["readiness"] == {
        "state": "incomplete",
        "reason_code": "zone_primary_sensor_missing",
    }
    assert setup["missing_configuration"] == [
        {
            "code": "zone_primary_sensor_missing",
            "scope": {
                "type": "zone",
                "module_id": None,
                "zone_id": entry_data["zone_id"],
                "sensor_id": None,
                "source_id": None,
            },
            "severity": "error",
        }
    ]
    unregister()
    assert service_calls == []


@pytest.mark.asyncio
async def test_unload_reload_registry_has_no_stale_or_duplicate_entry(
    hass,
    hass_ws_client,
    entry_data,
    service_calls,
) -> None:
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "21",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    client = await hass_ws_client(hass)
    await _read(client, FRONTEND_API_V1_OVERVIEW, entry.entry_id)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await client.send_json_auto_id({"type": FRONTEND_API_V1_OVERVIEW, "config_entry_id": entry.entry_id})
    missing = await client.receive_json()
    assert missing["success"] is False
    assert missing["error"]["code"] == "not_found"

    assert await hass.config_entries.async_setup(entry.entry_id)
    reloaded = await _read(client, FRONTEND_API_V1_OVERVIEW, entry.entry_id)
    assert reloaded["frontend_api_version"] == 1
    assert service_calls == []
