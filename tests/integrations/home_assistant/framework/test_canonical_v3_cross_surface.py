"""Cross-surface integration coverage for canonical v3 configuration authority.

Exercises the same persisted canonical configuration through:
- Setup Wizard (WebSocket greenfield authoring)
- HA Configure (native options flow)
- Heating/Settings (WebSocket edit-from-active)

Each surface reads and mutates the shared backend draft/authority; activation is
explicit and restart-safe.
"""

from __future__ import annotations

from copy import deepcopy

import pytest
from homeassistant import data_entry_flow
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
from controlel.domain.value_objects.temperature import Temperature
from controlel.infrastructure.home_assistant import ACTIVE_REFERENCE_KEY, HomeAssistantDiscoveryAdapter
from custom_components.controlel import config_flow as cf
from custom_components.controlel.const import CONF_TARGET_TEMPERATURE, DOMAIN
from custom_components.controlel.setup_backend import async_get_setup_backend
from custom_components.controlel.setup_write_websocket import (
    CONFIGURATION_V3_ACTIVATE,
    CONFIGURATION_V3_ACTIVE,
    CONFIGURATION_V3_CANONICALIZE,
    CONFIGURATION_V3_EDIT,
    CONFIGURATION_V3_START,
    CONFIGURATION_V3_UPDATE,
    CONFIGURATION_V3_VALIDATE,
    SETUP_WRITE_V1_START,
)

NOW = __import__("datetime").datetime(2026, 8, 28, 12, 0, tzinfo=__import__("datetime").UTC)


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


def _register_bindings(hass, *, platform: str = "cross-surface-test") -> tuple[str, str]:
    registry = er.async_get(hass)
    sensor = registry.async_get_or_create(
        "sensor",
        platform,
        "living-temperature",
        suggested_object_id="living_room_temperature",
        original_device_class="temperature",
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    source = registry.async_get_or_create(
        "switch",
        platform,
        "boiler",
        suggested_object_id="boiler",
    )
    hass.states.async_set(
        sensor.entity_id,
        "20.5",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    hass.states.async_set(source.entity_id, "off")
    return sensor.entity_id, source.entity_id


async def _empty_entry(hass, *, title: str = "Cross-surface heating") -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title=title, data={}, options={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    assert await hass.config_entries.async_setup(entry.entry_id)
    return entry


async def _choose(hass, result, step_id: str):
    return await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"next_step_id": step_id},
    )


async def _open_heating_menu(hass, entry):
    hub = await hass.config_entries.options.async_init(entry.entry_id)
    return await _choose(hass, hub, "heating")


async def _save_draft(hass, result):
    del hass
    assert result["type"] is data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "heating"
    return result


async def _prepare_activation(hass, saved):
    review = await _choose(hass, saved, "heating_review")
    assert review["step_id"] == "heating_review"
    activate = await hass.config_entries.options.async_configure(review["flow_id"], {})
    assert activate["step_id"] == "heating_activate"
    return activate


async def _activate_configure_flow(hass, activate):
    completed = await hass.config_entries.options.async_configure(activate["flow_id"], {})
    assert completed["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def _ws_receive(client, *, expect_success: bool = True) -> dict:
    response = await client.receive_json()
    if expect_success:
        assert response["success"] is True, response
    return response


async def _ws_active(client, entry) -> dict:
    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_ACTIVE,
            "config_entry_id": entry.entry_id,
            "snapshot_id": "cross-surface-read-active",
            "captured_at": NOW.isoformat(),
        }
    )
    return (await _ws_receive(client))["result"]["result"]


async def _ws_validate_canonicalize_activate(
    client,
    hass,
    entry,
    *,
    draft_id: str,
    revision_id: str,
    expected_active_revision_id: str | None,
    expected_active_generation: int,
    attempt_id: str,
    source: str = "configuration_v3_api",
    change_kind: str = "UPDATE",
) -> dict:
    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_VALIDATE,
            "config_entry_id": entry.entry_id,
            "draft_id": draft_id,
            "report_id": f"validate-{attempt_id}",
            "snapshot_id": f"validate-{attempt_id}",
            "evaluated_at": NOW.isoformat(),
        }
    )
    validation = (await _ws_receive(client))["result"]["result"]
    assert validation["activation_ready"] is True

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_CANONICALIZE,
            "config_entry_id": entry.entry_id,
            "draft_id": draft_id,
            "validation_report_id": validation["report_id"],
            "revision_id": revision_id,
            "snapshot_id": f"canonicalize-{attempt_id}",
            "created_at": NOW.isoformat(),
            "actor": "test:admin",
            "source": source,
            "change_kind": change_kind,
            "reason": attempt_id,
            "core_version": "0.17.0",
            "integration_version": "0.14.0",
        }
    )
    candidate = (await _ws_receive(client))["result"]["result"]

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_ACTIVATE,
            "config_entry_id": entry.entry_id,
            "revision_id": candidate["revision_id"],
            "semantic_configuration_fingerprint": candidate["semantic_configuration_fingerprint"],
            "expected_active_revision_id": expected_active_revision_id,
            "expected_active_generation": expected_active_generation,
            "attempt_id": attempt_id,
        }
    )
    assert (await _ws_receive(client))["success"] is True
    await hass.async_block_till_done()
    return candidate


async def _wizard_greenfield_activate(hass, entry, client, sensor_id: str, source_id: str) -> dict:
    snapshot = await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
        hass,
        snapshot_id="wizard-greenfield-bindings",
        captured_at=NOW,
    )
    by_locator = {item.current_locator: item for item in snapshot.objects if item.current_locator is not None}
    sensor_reference = by_locator[sensor_id].model_dump(mode="json")
    source_reference = by_locator[source_id].model_dump(mode="json")

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_START,
            "config_entry_id": entry.entry_id,
            "draft_id": "wizard-cross-surface-draft",
            "snapshot_id": "wizard-greenfield-start",
            "created_at": NOW.isoformat(),
            "bindings": {
                "zone_display_name": "Living room",
                "primary_sensor_display_name": "Living room temperature",
                "topology": {"area_reference": None, "floor_reference": None},
                "primary_temperature_sensor_reference": sensor_reference,
                "heat_source_display_name": "Boiler permission",
                "heat_source_reference": source_reference,
                "command_strategy": {
                    "mode": "simple",
                    "enable_permission": {
                        "domain": "switch",
                        "service": "turn_on",
                        "command_target_reference": source_reference,
                    },
                    "disable_permission": {
                        "domain": "switch",
                        "service": "turn_off",
                        "command_target_reference": source_reference,
                    },
                },
                "observations": {
                    "reported_actuator_state_reference": source_reference,
                    "physical_operation_reference": None,
                },
            },
        }
    )
    draft = (await _ws_receive(client))["result"]["result"]
    assert draft["heating"]["zones"][0]["demand_policy"]["target_temperature_celsius"] == 21.0
    assert draft["heating"]["zones"][0]["display_name"] == "Living room"

    return await _ws_validate_canonicalize_activate(
        client,
        hass,
        entry,
        draft_id=draft["draft_id"],
        revision_id="wizard-cross-surface-revision",
        expected_active_revision_id=None,
        expected_active_generation=0,
        attempt_id="wizard-activate",
        source="controlel_setup_wizard",
        change_kind="CREATE",
    )


async def _configure_edit_target(hass, entry, *, expected_target: float, new_target: float) -> None:
    initial = await _open_heating_menu(hass, entry)
    assert "edit_active" in initial["menu_options"]
    edit = await _choose(hass, initial, "edit_active")
    assert edit["step_id"] == "heating"
    zone = await _choose(hass, edit, "zone")
    zone_defaults = _defaults(zone)
    assert zone_defaults[cf.ZONE_NAME] == "Living room"
    assert zone_defaults[cf.TARGET_TEMPERATURE] == expected_target
    zone_defaults[cf.TARGET_TEMPERATURE] = new_target
    edited = await hass.config_entries.options.async_configure(zone["flow_id"], zone_defaults)

    saved = await _save_draft(hass, edited)
    activate = await _prepare_activation(hass, saved)
    await _activate_configure_flow(hass, activate)


async def _heating_edit_hysteresis(hass, client, entry, *, expected_target: float, new_turn_on_diff: float) -> dict:
    active = await _ws_active(client, entry)
    scopes = active["configuration_scopes"]
    policy = scopes["heating"]["zones"][0]["demand_policy"]
    assert policy["target_temperature_celsius"] == expected_target

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_EDIT,
            "config_entry_id": entry.entry_id,
            "draft_id": "heating-cross-surface-edit",
            "created_at": NOW.isoformat(),
            "expected_active_generation": active["active_reference"]["generation"],
        }
    )
    draft = (await _ws_receive(client))["result"]["result"]
    edit_scopes = {
        "heating": draft["heating"],
        "diagnostics": draft["diagnostics"],
        "notifications": draft["notifications"],
    }
    edit_scopes["heating"]["zones"][0]["demand_policy"]["heating_turn_on_differential_celsius"] = new_turn_on_diff
    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_UPDATE,
            "config_entry_id": entry.entry_id,
            "draft_id": draft["draft_id"],
            "expected_revision": draft["revision"],
            "updated_at": NOW.isoformat(),
            "configuration_scopes": edit_scopes,
        }
    )
    updated = (await _ws_receive(client))["result"]["result"]
    assert updated["heating"]["zones"][0]["demand_policy"]["heating_turn_on_differential_celsius"] == new_turn_on_diff
    assert updated["heating"]["zones"][0]["demand_policy"]["target_temperature_celsius"] == expected_target

    return await _ws_validate_canonicalize_activate(
        client,
        hass,
        entry,
        draft_id=draft["draft_id"],
        revision_id="heating-cross-surface-revision",
        expected_active_revision_id=active["active_reference"]["canonical_revision_id"],
        expected_active_generation=active["active_reference"]["generation"],
        attempt_id="heating-activate",
        source="controlel_heating_settings",
    )


@pytest.mark.asyncio
async def test_wizard_configure_heating_cross_surface_lifecycle_preserves_authority_through_restart(
    hass,
    hass_ws_client,
    service_calls,
) -> None:
    sensor_id, source_id = _register_bindings(hass)
    entry = await _empty_entry(hass)
    client = await hass_ws_client(hass)

    # 1. Setup Wizard creates and activates a single-zone configuration at 21 °C.
    wizard_revision = await _wizard_greenfield_activate(hass, entry, client, sensor_id, source_id)
    assert set(entry.data) == {ACTIVE_REFERENCE_KEY}
    assert entry.options == {}
    assert entry.runtime_data.config.target_temperature == Temperature(21.0)
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == wizard_revision["revision_id"]
    wizard_generation = 1

    wizard_read = await _ws_active(client, entry)
    assert wizard_read["active_reference"]["generation"] == wizard_generation
    wizard_policy = wizard_read["configuration_scopes"]["heating"]["zones"][0]["demand_policy"]
    assert wizard_policy["target_temperature_celsius"] == 21.0

    # 2. HA Configure reads the same active authority, sees 21 °C, edits to 22 °C, activates.
    await _configure_edit_target(hass, entry, expected_target=21.0, new_target=22.0)
    assert entry.runtime_data.config.target_temperature == Temperature(22.0)
    configure_generation = wizard_generation + 1
    configure_revision_id = entry.runtime_data.loaded_configuration.canonical_revision_id
    assert configure_revision_id != wizard_revision["revision_id"]

    # 3. Heating/Settings reads 22 °C, edits hysteresis, activates.
    heating_revision = await _heating_edit_hysteresis(hass, client, entry, expected_target=22.0, new_turn_on_diff=0.5)
    assert entry.runtime_data.config.target_temperature == Temperature(22.0)
    assert entry.runtime_data.config.heating_turn_on_differential == 0.5
    heating_generation = configure_generation + 1
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == heating_revision["revision_id"]

    # 4. Wizard and HA Configure read the same updated canonical values.
    final_active = await _ws_active(client, entry)
    final_policy = final_active["configuration_scopes"]["heating"]["zones"][0]["demand_policy"]
    assert final_active["active_reference"]["generation"] == heating_generation
    assert final_policy["target_temperature_celsius"] == 22.0
    assert final_policy["heating_turn_on_differential_celsius"] == 0.5
    assert final_active["runtime_evidence"]["authority_loaded"] is True
    assert all(item["status"] == "RESOLVED" for item in final_active["reference_health"])

    configure_read = await _open_heating_menu(hass, entry)
    configure_edit = await _choose(hass, configure_read, "edit_active")
    configure_zone = _defaults(await _choose(hass, configure_edit, "zone"))
    assert configure_zone[cf.TARGET_TEMPERATURE] == 22.0
    assert configure_zone[cf.TURN_ON_DIFFERENTIAL] == 0.5
    hass.config_entries.options.async_abort(configure_edit["flow_id"])

    # Legacy/new-v2 write paths remain rejected after canonical authority is active.
    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_START,
            "config_entry_id": entry.entry_id,
            "draft_id": "must-not-start-v2",
            "module_instance_id": "main-heating",
            "created_at": NOW.isoformat(),
            "snapshot_id": "must-not-discover-v2",
            "report_id": "must-not-validate-v2",
        }
    )
    legacy_start = await client.receive_json()
    assert legacy_start["success"] is False
    assert legacy_start["error"]["code"] == "canonical_v3_required"

    hass.config_entries.async_update_entry(entry, options={CONF_TARGET_TEMPERATURE: 16.0})
    await hass.async_block_till_done()
    assert entry.runtime_data.config.target_temperature == Temperature(22.0)
    hass.config_entries.async_update_entry(entry, options={})
    await hass.async_block_till_done()

    # 5. Reload/restart preserves active canonical revision, values, authority, and bindings.
    active_data_before = deepcopy(dict(entry.data))
    active_revision_id = entry.runtime_data.loaded_configuration.canonical_revision_id

    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.data.pop(f"{DOMAIN}_setup_backend", None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert dict(entry.data) == active_data_before
    assert entry.options == {}
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == active_revision_id
    assert entry.runtime_data.config.target_temperature == Temperature(22.0)
    assert entry.runtime_data.config.heating_turn_on_differential == 0.5
    assert entry.runtime_data.host is not None

    backend = await async_get_setup_backend(hass, entry)
    loaded = entry.runtime_data.loaded_configuration
    active_reference = await backend.repository.get_active_reference(
        (loaded.environment_id, loaded.module_key, loaded.module_instance_id)
    )
    assert active_reference is not None
    assert active_reference.canonical_revision_id == active_revision_id
    assert active_reference.generation == heating_generation

    restarted = await _ws_active(client, entry)
    restarted_policy = restarted["configuration_scopes"]["heating"]["zones"][0]["demand_policy"]
    assert restarted_policy["target_temperature_celsius"] == 22.0
    assert restarted_policy["heating_turn_on_differential_celsius"] == 0.5
    assert service_calls == []
