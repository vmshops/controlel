"""Real HA coverage for canonical Heating authority and activation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.instance_id import async_get as async_get_instance_id
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
from controlel.application.configuration import migrate_heating_v2_revision_to_v3
from controlel.application.configuration.heating_setup_adapter import HeatingSetupAdapter
from controlel.application.setup import ActivationState, DraftRevision
from controlel.domain.value_objects.temperature import Temperature
from controlel.infrastructure.home_assistant import ACTIVE_REFERENCE_KEY, HomeAssistantDiscoveryAdapter
from custom_components.controlel.canonical_runtime import async_compile_canonical_runtime
from custom_components.controlel.config import integration_config_from_entry
from custom_components.controlel.const import CONF_TARGET_TEMPERATURE, CONF_TEMPERATURE_ENTITY_ID, DOMAIN
from custom_components.controlel.legacy_config_converter import convert_legacy_heating_config
from custom_components.controlel.setup_backend import async_get_setup_backend
from custom_components.controlel.setup_write_websocket import (
    CONFIGURATION_V3_ACTIVATE,
    CONFIGURATION_V3_ACTIVE,
    CONFIGURATION_V3_CANONICALIZE,
    CONFIGURATION_V3_EDIT,
    CONFIGURATION_V3_UPDATE,
    CONFIGURATION_V3_VALIDATE,
    SETUP_WRITE_V1_ACTIVATE,
    SETUP_WRITE_V1_START,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


async def _canonical_candidate(
    hass,
    entry,
    entry_data: dict[str, object],
    *,
    revision_id: str,
    target_temperature: float,
    environment_id: str | None = None,
):
    provider_instance_id = await async_get_instance_id(hass)
    registry = er.async_get(hass)
    temperature_entry = registry.async_get_or_create(
        "sensor",
        "canonical-test",
        "living-temperature",
        suggested_object_id="living_room_temperature",
        original_device_class="temperature",
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    source_entry = registry.async_get_or_create(
        "switch",
        "canonical-test",
        "boiler",
        suggested_object_id="boiler",
    )
    legacy = integration_config_from_entry(entry_data, {})
    converted = convert_legacy_heating_config(
        replace(legacy, target_temperature=Temperature(target_temperature)),
        environment_id=environment_id or provider_instance_id,
        provider_instance_id=environment_id or provider_instance_id,
        module_instance_id="main-heating",
        configuration_id="configuration-1",
        revision_id=revision_id,
        created_at=NOW,
        core_version="0.14.0",
        integration_version="0.13.0",
    )
    target_environment = environment_id or provider_instance_id
    snapshot = await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
        hass,
        snapshot_id=f"candidate:{revision_id}",
        captured_at=NOW,
    )
    references_by_locator = {
        reference.current_locator: reference for reference in snapshot.objects if reference.current_locator is not None
    }
    runtime_locators = {
        entry_data[CONF_TEMPERATURE_ENTITY_ID]: temperature_entry.entity_id,
        "switch.boiler": source_entry.entity_id,
    }
    stable_bindings = tuple(
        binding.model_copy(
            update={
                "reference": references_by_locator[runtime_locators[binding.reference.current_locator]].model_copy(
                    update={"provider_instance_id": target_environment}
                )
            }
        )
        for binding in converted.canonical_revision.bindings
    )
    draft = DraftRevision(
        draft_id=f"draft:{revision_id}",
        revision=1,
        environment_id=target_environment,
        module_key="heating",
        module_instance_id="main-heating",
        module_schema_version=2,
        created_at=NOW,
        updated_at=NOW,
        settings=converted.canonical_revision.module_payload,
        bindings=stable_bindings,
    )
    adapter = HeatingSetupAdapter()
    report = adapter.validate(draft, report_id=f"report:{revision_id}", evaluated_at=NOW)
    candidate = adapter.canonicalize(
        draft,
        report,
        configuration_id="configuration-1",
        revision_id=revision_id,
        revision=1,
        provider="home_assistant",
        provider_instance_id=target_environment,
        created_at=NOW,
        actor="test:admin",
        source="test",
        change_kind="CREATE",
        reason="canonical_runtime_test",
        core_version="0.14.0",
        integration_version="0.13.0",
    )
    backend = await async_get_setup_backend(hass, entry)
    await backend.repository.add_canonical_revision(candidate)
    return candidate, backend


async def _canonical_v3_candidate(
    hass,
    entry,
    entry_data: dict[str, object],
    *,
    revision_id: str,
    target_temperature: float,
):
    v2, backend = await _canonical_candidate(
        hass,
        entry,
        entry_data,
        revision_id=f"{revision_id}-v2-source",
        target_temperature=target_temperature,
    )
    v3 = migrate_heating_v2_revision_to_v3(
        v2,
        revision_id=revision_id,
        created_at=NOW,
        actor="test:admin",
        source="explicit_test_conversion",
        reason="canonical_v3_lifecycle_test",
    )
    await backend.repository.add_canonical_revision_v3(v3)
    return v3, backend


@pytest.mark.asyncio
async def test_explicit_activation_starts_canonical_authority_and_hands_over_safely(
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
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    first_candidate, backend = await _canonical_candidate(
        hass,
        entry,
        entry_data,
        revision_id="canonical-1",
        target_temperature=22.0,
    )
    prepared = await async_compile_canonical_runtime(hass, first_candidate, activation_attempt_id="preflight")
    assert prepared.config.target_temperature == Temperature(22.0)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_ACTIVATE,
            "config_entry_id": entry.entry_id,
            "revision_id": first_candidate.revision_id,
            "semantic_configuration_fingerprint": first_candidate.semantic_configuration_fingerprint,
            "expected_active_revision_id": None,
            "expected_active_generation": 0,
            "attempt_id": "attempt-1",
        }
    )
    first_response = await client.receive_json()
    assert first_response["success"] is True, first_response
    first_host = entry.runtime_data.host
    assert first_host is not None

    candidate, _ = await _canonical_candidate(
        hass,
        entry,
        entry_data,
        revision_id="canonical-2",
        target_temperature=23.0,
    )

    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_ACTIVATE,
            "config_entry_id": entry.entry_id,
            "revision_id": candidate.revision_id,
            "semantic_configuration_fingerprint": candidate.semantic_configuration_fingerprint,
            "expected_active_revision_id": first_candidate.revision_id,
            "expected_active_generation": 1,
            "attempt_id": "attempt-2",
        }
    )
    response = await client.receive_json()

    assert response["success"] is True, response
    assert response["result"]["operation"] == "activate"
    assert response["result"]["result"]["state"] == ActivationState.COMMITTED.value
    assert first_host.stopped is True
    assert entry.runtime_data.host is not first_host
    assert entry.runtime_data.config.target_temperature == Temperature(23.0)
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == candidate.revision_id
    assert set(entry.data) == {ACTIVE_REFERENCE_KEY}
    assert dict(entry.options) == {}
    active = await backend.repository.get_active_reference(
        (candidate.environment_id, candidate.module_key, candidate.module_instance_id)
    )
    assert active is not None
    assert active.canonical_revision_id == candidate.revision_id
    assert active.generation == 2
    assert service_calls == []

    hass.config_entries.async_update_entry(entry, options={CONF_TARGET_TEMPERATURE: 16.0})
    await hass.async_block_till_done()
    assert entry.runtime_data.config.target_temperature == Temperature(23.0)


@pytest.mark.asyncio
async def test_invalid_candidate_never_creates_runtime_authority(
    hass,
    hass_ws_client,
    entry_data,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    candidate, backend = await _canonical_candidate(
        hass,
        entry,
        entry_data,
        revision_id="wrong-environment",
        target_temperature=23.0,
        environment_id="another-home-assistant-instance",
    )
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_ACTIVATE,
            "config_entry_id": entry.entry_id,
            "revision_id": candidate.revision_id,
            "semantic_configuration_fingerprint": candidate.semantic_configuration_fingerprint,
            "expected_active_revision_id": None,
            "expected_active_generation": 0,
            "attempt_id": "attempt-invalid",
        }
    )
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"
    assert not hasattr(entry, "runtime_data")
    assert ACTIVE_REFERENCE_KEY not in entry.data
    assert await backend.repository.list_non_terminal_attempts() == ()


@pytest.mark.asyncio
async def test_activation_never_auto_migrates_or_stops_a_legacy_runtime(
    hass,
    hass_ws_client,
    entry_data,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    legacy_host = entry.runtime_data.host
    candidate, backend = await _canonical_candidate(
        hass,
        entry,
        entry_data,
        revision_id="canonical-inactive",
        target_temperature=23.0,
    )
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_ACTIVATE,
            "config_entry_id": entry.entry_id,
            "revision_id": candidate.revision_id,
            "semantic_configuration_fingerprint": candidate.semantic_configuration_fingerprint,
            "expected_active_revision_id": None,
            "expected_active_generation": 0,
            "attempt_id": "attempt-legacy",
        }
    )
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "setup_conflict"
    assert entry.runtime_data.host is legacy_host
    assert legacy_host.stopped is False
    assert ACTIVE_REFERENCE_KEY not in entry.data
    assert await backend.repository.list_non_terminal_attempts() == ()


@pytest.mark.asyncio
async def test_activation_command_is_admin_only_and_entry_scoped(
    hass,
    hass_ws_client,
    hass_read_only_access_token,
    entry_data,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    client = await hass_ws_client(hass, hass_read_only_access_token)
    message = {
        "type": SETUP_WRITE_V1_ACTIVATE,
        "config_entry_id": entry.entry_id,
        "revision_id": "canonical-1",
        "semantic_configuration_fingerprint": "a" * 64,
        "expected_active_revision_id": None,
        "expected_active_generation": 0,
        "attempt_id": "attempt-unauthorized",
    }

    await client.send_json_auto_id(message)
    unauthorized = await client.receive_json()
    assert unauthorized["success"] is False
    assert unauthorized["error"]["code"] == "unauthorized"

    admin = await hass_ws_client(hass)
    await admin.send_json_auto_id({**message, "config_entry_id": "not-this-entry"})
    wrong_entry = await admin.receive_json()
    assert wrong_entry["success"] is False
    assert wrong_entry["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_canonical_v3_edit_activate_read_and_restart_lifecycle(
    hass,
    hass_ws_client,
    entry_data,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    active_v3, _backend = await _canonical_v3_candidate(
        hass,
        entry,
        entry_data,
        revision_id="canonical-v3-active",
        target_temperature=22.0,
    )
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "config_entry_id": entry.entry_id,
            "type": CONFIGURATION_V3_ACTIVATE,
            "revision_id": active_v3.revision_id,
            "semantic_configuration_fingerprint": active_v3.semantic_configuration_fingerprint,
            "expected_active_revision_id": None,
            "expected_active_generation": 0,
            "attempt_id": "activate-v3-initial",
        }
    )
    initial_activation = await client.receive_json()
    assert initial_activation["success"] is True, initial_activation
    assert set(entry.data) == {ACTIVE_REFERENCE_KEY}
    assert dict(entry.options) == {}

    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_START,
            "config_entry_id": entry.entry_id,
            "draft_id": "must-not-start-from-defaults",
            "module_instance_id": "main-heating",
            "created_at": NOW.isoformat(),
            "snapshot_id": "must-not-discover-defaults",
            "report_id": "must-not-validate-defaults",
        }
    )
    default_start = await client.receive_json()
    assert default_start["success"] is False
    assert default_start["error"]["code"] == "setup_conflict"

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_ACTIVE,
            "config_entry_id": entry.entry_id,
            "snapshot_id": "read-v3-active",
            "captured_at": NOW.isoformat(),
        }
    )
    read_response = await client.receive_json()
    assert read_response["success"] is True, read_response
    active = read_response["result"]["result"]
    assert active["active_reference"]["canonical_revision_id"] == active_v3.revision_id
    assert active["active_reference"]["generation"] == 1
    assert active["canonical_revision"]["semantic_configuration_fingerprint"] == (
        active_v3.semantic_configuration_fingerprint
    )
    assert active["runtime_evidence"]["authority_loaded"] is True
    assert active["runtime_evidence"]["host_ready"] is True
    assert all(item["status"] == "RESOLVED" for item in active["reference_health"])

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_EDIT,
            "config_entry_id": entry.entry_id,
            "draft_id": "edit-v3-active",
            "created_at": NOW.isoformat(),
            "expected_active_generation": 1,
        }
    )
    edit_response = await client.receive_json()
    assert edit_response["success"] is True, edit_response
    draft = edit_response["result"]["result"]
    assert draft["base_active_revision_id"] == active_v3.revision_id
    assert draft["base_active_generation"] == 1

    scopes = active["configuration_scopes"]
    scopes["heating"]["zones"][0]["demand_policy"]["target_temperature_celsius"] = 23.5
    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_UPDATE,
            "config_entry_id": entry.entry_id,
            "draft_id": draft["draft_id"],
            "expected_revision": draft["revision"],
            "updated_at": NOW.isoformat(),
            "configuration_scopes": scopes,
        }
    )
    update_response = await client.receive_json()
    assert update_response["success"] is True, update_response
    updated = update_response["result"]["result"]
    assert updated["heating"]["zones"][0]["demand_policy"]["target_temperature_celsius"] == 23.5
    assert updated["diagnostics"] == draft["diagnostics"]
    assert updated["notifications"] == draft["notifications"]

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_VALIDATE,
            "config_entry_id": entry.entry_id,
            "draft_id": draft["draft_id"],
            "report_id": "validate-v3-edit",
            "snapshot_id": "validate-v3-edit",
            "evaluated_at": NOW.isoformat(),
        }
    )
    validation_response = await client.receive_json()
    assert validation_response["success"] is True, validation_response
    validation = validation_response["result"]["result"]
    assert validation["activation_ready"] is True

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_CANONICALIZE,
            "config_entry_id": entry.entry_id,
            "draft_id": draft["draft_id"],
            "validation_report_id": validation["report_id"],
            "revision_id": "canonical-v3-edited",
            "created_at": NOW.isoformat(),
            "actor": "test:admin",
            "source": "configuration_v3_api",
            "change_kind": "UPDATE",
            "reason": "adjust_target",
            "core_version": "0.15.0",
            "integration_version": "0.13.0",
        }
    )
    canonicalize_response = await client.receive_json()
    assert canonicalize_response["success"] is True, canonicalize_response
    candidate = canonicalize_response["result"]["result"]
    assert candidate["parent_revision_id"] == active_v3.revision_id
    assert candidate["revision"] == active_v3.revision + 1

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_ACTIVATE,
            "config_entry_id": entry.entry_id,
            "revision_id": candidate["revision_id"],
            "semantic_configuration_fingerprint": candidate["semantic_configuration_fingerprint"],
            "expected_active_revision_id": active_v3.revision_id,
            "expected_active_generation": 1,
            "attempt_id": "activate-v3-edit",
        }
    )
    activate_response = await client.receive_json()
    assert activate_response["success"] is True, activate_response
    assert entry.runtime_data.config.target_temperature == Temperature(23.5)
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == candidate["revision_id"]

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_ACTIVE,
            "config_entry_id": entry.entry_id,
            "snapshot_id": "read-v3-edited",
            "captured_at": NOW.isoformat(),
        }
    )
    after_response = await client.receive_json()
    assert after_response["success"] is True, after_response
    after = after_response["result"]["result"]
    assert after["canonical_revision"] == candidate
    assert after["active_reference"]["generation"] == 2
    assert after["configuration_scopes"]["heating"]["zones"][0]["demand_policy"]["target_temperature_celsius"] == 23.5

    hass.config_entries.async_update_entry(entry, options={CONF_TARGET_TEMPERATURE: 16.0})
    await hass.async_block_till_done()
    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_EDIT,
            "config_entry_id": entry.entry_id,
            "draft_id": "must-not-mix-legacy-options",
            "created_at": NOW.isoformat(),
            "expected_active_generation": 2,
        }
    )
    mixed_response = await client.receive_json()
    assert mixed_response["success"] is False
    assert mixed_response["error"]["code"] == "setup_conflict"
    assert entry.runtime_data.config.target_temperature == Temperature(23.5)
    hass.config_entries.async_update_entry(entry, options={})
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.data.pop(f"{DOMAIN}_setup_backend", None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == candidate["revision_id"]
    assert entry.runtime_data.config.target_temperature == Temperature(23.5)
