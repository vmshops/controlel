from __future__ import annotations

import asyncio

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, EntityCategory, UnitOfTemperature
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.controlel.const import (
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_PRIMARY_MEASUREMENT_MAX_AGE,
    CONF_TARGET_TEMPERATURE,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_ZONE_NAME,
    DOMAIN,
)
from custom_components.controlel.diagnostics import async_get_config_entry_diagnostics
from custom_components.controlel.operational import SafetyState

EXPECTED_SENSOR_KEYS = {
    "core_version",
    "current_temperature",
    "duplicate_commands_suppressed",
    "grace_remaining",
    "heat_demand",
    "integration_version",
    "last_command_outcome",
    "last_command_time",
    "last_decision",
    "last_decision_reason",
    "last_meaningful_event",
    "last_requested_command",
    "measurement_age",
    "measurement_status",
    "runtime_status",
    "safety_state",
    "target_temperature",
}
EXPECTED_BINARY_SENSOR_KEYS = {
    "fatal_failure",
    "heat_required",
    "measurement_valid",
    "recoverable_failure",
    "runtime_active",
}
PRIMARY_KEYS = {
    "current_temperature",
    "target_temperature",
    "heat_demand",
    "heat_required",
    "safety_state",
}


def _key(entry_id: str, unique_id: str) -> str:
    return unique_id.removeprefix(f"{entry_id}_")


async def _setup_entry(hass, entry_data) -> MockConfigEntry:
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_device_entities_states_unique_ids_and_unload(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry = await _setup_entry(hass, entry_data)
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    by_key = {_key(entry.entry_id, item.unique_id): item for item in entries}

    assert set(by_key) == EXPECTED_SENSOR_KEYS | EXPECTED_BINARY_SENSOR_KEYS
    assert len(entries) == 22
    assert {item.platform for item in entries} == {DOMAIN}
    assert {item.unique_id for item in entries} == {f"{entry.entry_id}_{key}" for key in by_key}
    assert {key for key, item in by_key.items() if item.entity_category is None} == PRIMARY_KEYS
    assert all(
        item.entity_category is EntityCategory.DIAGNOSTIC for key, item in by_key.items() if key not in PRIMARY_KEYS
    )

    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass),
        entry.entry_id,
    )
    assert len(devices) == 1
    assert devices[0].identifiers == {(DOMAIN, entry.entry_id)}
    assert devices[0].name == "Controlel — Living room"

    assert hass.states.get(by_key["current_temperature"].entity_id).state == "20.0"
    assert hass.states.get(by_key["target_temperature"].entity_id).state == "21.0"
    assert hass.states.get(by_key["measurement_status"].entity_id).state == "valid"
    assert hass.states.get(by_key["heat_demand"].entity_id).state == "heat_required"
    assert hass.states.get(by_key["heat_required"].entity_id).state == "on"
    assert hass.states.get(by_key["runtime_active"].entity_id).state == "on"
    assert hass.states.get(by_key["integration_version"].entity_id).state == "0.3.0"
    assert hass.states.get(by_key["core_version"].entity_id).state == "0.1.0"

    entity_ids = [item.entity_id for item in entries]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert all(hass.states.get(entity_id).state == "unavailable" for entity_id in entity_ids)
    assert not hasattr(entry, "runtime_data")


async def test_reload_rename_and_target_change_keep_one_stable_entity_set(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry = await _setup_entry(hass, entry_data)
    registry = er.async_get(hass)
    original = {item.unique_id: item.entity_id for item in er.async_entries_for_config_entry(registry, entry.entry_id)}

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_ZONE_NAME: "Upstairs",
            CONF_TARGET_TEMPERATURE: 22.5,
        },
    )
    await hass.async_block_till_done()

    current_entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert {item.unique_id: item.entity_id for item in current_entries} == original
    assert len(current_entries) == 22
    target = next(item for item in current_entries if item.unique_id.endswith("_target_temperature"))
    assert hass.states.get(target.entity_id).state == "22.5"
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    assert devices[0].name == "Controlel — Upstairs"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unknown_measurement_and_valid_recovery_update_entities(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry = await _setup_entry(hass, entry_data)
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    by_key = {_key(entry.entry_id, item.unique_id): item.entity_id for item in entries}

    hass.states.async_set(entry_data[CONF_TEMPERATURE_ENTITY_ID], "unknown")
    await hass.async_block_till_done()
    assert hass.states.get(by_key["measurement_status"]).state == "unknown"
    assert hass.states.get(by_key["measurement_valid"]).state == "off"
    assert hass.states.get(by_key["current_temperature"]).state == "unknown"

    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "22",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    await hass.async_block_till_done()
    assert hass.states.get(by_key["measurement_status"]).state == "valid"
    assert hass.states.get(by_key["measurement_valid"]).state == "on"
    assert hass.states.get(by_key["current_temperature"]).state == "22.0"
    assert hass.states.get(by_key["heat_demand"]).state == "no_heat_required"
    assert hass.states.get(by_key["heat_required"]).state == "off"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_stale_timeout_duplicate_suppression_and_recovery_are_truthful(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry_data[CONF_PRIMARY_MEASUREMENT_MAX_AGE] = 0.5
    entry_data[CONF_INDETERMINATE_GRACE_PERIOD] = 0.0
    entry = await _setup_entry(hass, entry_data)
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    by_key = {_key(entry.entry_id, item.unique_id): item.entity_id for item in entries}
    host = entry.runtime_data.host
    assert host is not None
    initial_suppressions = host.snapshot_source.current.duplicate_commands_suppressed

    async with asyncio.timeout(2):
        while host.snapshot_source.current.safety_state is not SafetyState.TIMEOUT_ACTION_APPLIED:
            await asyncio.sleep(0.01)
    await host.async_reevaluate()
    await hass.async_block_till_done()

    assert hass.states.get(by_key["measurement_status"]).state == "stale"
    assert hass.states.get(by_key["heat_demand"]).state == "indeterminate"
    assert hass.states.get(by_key["safety_state"]).state == "timeout_action_applied"
    assert hass.states.get(by_key["last_requested_command"]).state == "disable_heating"
    assert hass.states.get(by_key["last_command_outcome"]).state == "suppressed_duplicate"
    assert int(hass.states.get(by_key["duplicate_commands_suppressed"]).state) == (initial_suppressions + 1)

    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "19",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    await hass.async_block_till_done()

    assert host.snapshot_source.current.safety_state is SafetyState.NORMAL
    assert host.snapshot_source.current.grace_deadline is None
    assert hass.states.get(by_key["measurement_status"]).state == "valid"
    assert hass.states.get(by_key["heat_demand"]).state == "heat_required"
    assert hass.states.get(by_key["safety_state"]).state == "normal"
    assert hass.states.get(by_key["last_command_outcome"]).state == "dispatched"
    assert [service for service, _ in service_calls] == [
        "turn_on",
        "turn_off",
        "turn_on",
    ]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_diagnostics_are_allowlisted_json_safe_and_redact_unknown_entry_data(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry_data["password"] = "must-not-appear"
    entry_data["token"] = "must-not-appear"
    entry = await _setup_entry(hass, entry_data)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    serialized = repr(diagnostics)

    assert diagnostics["versions"] == {
        "integration": "0.3.0",
        "core": "0.1.0",
    }
    assert diagnostics["operational_snapshot"]["runtime_status"] == "active"
    assert diagnostics["operational_snapshot"]["safety_state"] == "normal"
    assert len(diagnostics["entity_ids"]) == 22
    assert diagnostics["decision_trace"]
    assert diagnostics["active_issue_ids"] == []
    assert "must-not-appear" not in serialized
    assert "password" not in serialized
    assert "token" not in serialized
    assert await hass.config_entries.async_unload(entry.entry_id)
