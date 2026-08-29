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
from controlel.application.setup import ActivationState, DraftRevision, SetupConflictError, SetupNotFoundError
from controlel.domain.value_objects.temperature import Temperature
from controlel.infrastructure.home_assistant import ACTIVE_REFERENCE_KEY, HomeAssistantDiscoveryAdapter
from custom_components.controlel.activation_backend import async_activate_canonical_revision
from custom_components.controlel.canonical_runtime import async_compile_canonical_runtime
from custom_components.controlel.config import integration_config_from_entry
from custom_components.controlel.const import CONF_TARGET_TEMPERATURE, CONF_TEMPERATURE_ENTITY_ID, DOMAIN
from custom_components.controlel.legacy_config_converter import convert_legacy_heating_config
from custom_components.controlel.setup_backend import async_get_setup_backend
from custom_components.controlel.setup_write_websocket import (
    CONFIGURATION_V3_ABANDON,
    CONFIGURATION_V3_ACTIVATE,
    CONFIGURATION_V3_ACTIVE,
    CONFIGURATION_V3_CANONICALIZE,
    CONFIGURATION_V3_CONVERT_LEGACY,
    CONFIGURATION_V3_CONVERT_V2,
    CONFIGURATION_V3_DRAFT,
    CONFIGURATION_V3_DRAFTS,
    CONFIGURATION_V3_EDIT,
    CONFIGURATION_V3_START,
    CONFIGURATION_V3_UPDATE,
    CONFIGURATION_V3_VALIDATE,
    ERR_CANONICAL_V3_DRAFT_STALE,
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
        integration_version="0.14.0",
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
        integration_version="0.14.0",
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
    await async_activate_canonical_revision(
        hass,
        entry,
        revision_id=first_candidate.revision_id,
        semantic_configuration_fingerprint=first_candidate.semantic_configuration_fingerprint,
        expected_active_revision_id=None,
        expected_active_generation=0,
        attempt_id="attempt-1",
    )
    first_host = entry.runtime_data.host
    assert first_host is not None

    candidate, _ = await _canonical_candidate(
        hass,
        entry,
        entry_data,
        revision_id="canonical-2",
        target_temperature=23.0,
    )

    result = await async_activate_canonical_revision(
        hass,
        entry,
        revision_id=candidate.revision_id,
        semantic_configuration_fingerprint=candidate.semantic_configuration_fingerprint,
        expected_active_revision_id=first_candidate.revision_id,
        expected_active_generation=1,
        attempt_id="attempt-2",
    )

    assert result.state is ActivationState.COMMITTED
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
    with pytest.raises(ValueError, match="Home Assistant instance"):
        await async_activate_canonical_revision(
            hass,
            entry,
            revision_id=candidate.revision_id,
            semantic_configuration_fingerprint=candidate.semantic_configuration_fingerprint,
            expected_active_revision_id=None,
            expected_active_generation=0,
            attempt_id="attempt-invalid",
        )
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
    with pytest.raises(SetupConflictError):
        await async_activate_canonical_revision(
            hass,
            entry,
            revision_id=candidate.revision_id,
            semantic_configuration_fingerprint=candidate.semantic_configuration_fingerprint,
            expected_active_revision_id=None,
            expected_active_generation=0,
            attempt_id="attempt-legacy",
        )
    assert entry.runtime_data.host is legacy_host
    assert legacy_host.stopped is False
    assert ACTIVE_REFERENCE_KEY not in entry.data
    assert await backend.repository.list_non_terminal_attempts() == ()


@pytest.mark.asyncio
async def test_v1_activation_rejection_is_admin_only_and_requires_v3(
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
    assert wrong_entry["error"]["code"] == "canonical_v3_required"


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
    assert default_start["error"]["code"] == "canonical_v3_required"

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
            "snapshot_id": "canonicalize-v3-edit",
            "created_at": NOW.isoformat(),
            "actor": "test:admin",
            "source": "configuration_v3_api",
            "change_kind": "UPDATE",
            "reason": "adjust_target",
            "core_version": "0.17.0",
            "integration_version": "0.14.0",
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


@pytest.mark.asyncio
async def test_v3_draft_reopens_after_restart_and_abandon_preserves_active_authority(
    hass,
    hass_ws_client,
    hass_read_only_access_token,
    entry_data,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Durable v3 draft", data={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    active_v3, backend = await _canonical_v3_candidate(
        hass,
        entry,
        entry_data,
        revision_id="canonical-v3-draft-base",
        target_temperature=22.0,
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_ACTIVATE,
            "config_entry_id": entry.entry_id,
            "revision_id": active_v3.revision_id,
            "semantic_configuration_fingerprint": active_v3.semantic_configuration_fingerprint,
            "expected_active_revision_id": None,
            "expected_active_generation": 0,
            "attempt_id": "activate-v3-draft-base",
        }
    )
    assert (await client.receive_json())["success"] is True
    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_EDIT,
            "config_entry_id": entry.entry_id,
            "draft_id": "durable-v3-draft",
            "created_at": NOW.isoformat(),
            "expected_active_generation": 1,
        }
    )
    created_response = await client.receive_json()
    assert created_response["success"] is True, created_response
    created = created_response["result"]["result"]
    scopes = {
        "heating": created["heating"],
        "diagnostics": created["diagnostics"],
        "notifications": created["notifications"],
    }
    scopes["heating"]["zones"][0]["demand_policy"]["target_temperature_celsius"] = 22.25
    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_UPDATE,
            "config_entry_id": entry.entry_id,
            "draft_id": created["draft_id"],
            "expected_revision": created["revision"],
            "updated_at": NOW.isoformat(),
            "configuration_scopes": scopes,
        }
    )
    updated_response = await client.receive_json()
    assert updated_response["success"] is True, updated_response
    created = updated_response["result"]["result"]
    assert created["revision"] == 2
    active_data_before = dict(entry.data)

    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.data.pop(f"{DOMAIN}_setup_backend", None)
    assert await hass.config_entries.async_setup(entry.entry_id)

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_DRAFT,
            "config_entry_id": entry.entry_id,
            "draft_id": created["draft_id"],
        }
    )
    reopened_response = await client.receive_json()
    assert reopened_response["success"] is True, reopened_response
    assert reopened_response["result"]["result"] == created

    await client.send_json_auto_id({"type": CONFIGURATION_V3_DRAFTS, "config_entry_id": entry.entry_id})
    listed_response = await client.receive_json()
    assert listed_response["success"] is True, listed_response
    assert listed_response["result"]["result"] == [created]

    read_only = await hass_ws_client(hass, hass_read_only_access_token)
    for unauthorized_message in (
        {
            "type": CONFIGURATION_V3_DRAFT,
            "config_entry_id": entry.entry_id,
            "draft_id": created["draft_id"],
        },
        {"type": CONFIGURATION_V3_DRAFTS, "config_entry_id": entry.entry_id},
        {
            "type": CONFIGURATION_V3_ABANDON,
            "config_entry_id": entry.entry_id,
            "draft_id": created["draft_id"],
            "expected_revision": created["revision"],
        },
    ):
        await read_only.send_json_auto_id(unauthorized_message)
        unauthorized = await read_only.receive_json()
        assert unauthorized["success"] is False
        assert unauthorized["error"]["code"] == "unauthorized"

    abandon = {
        "type": CONFIGURATION_V3_ABANDON,
        "config_entry_id": entry.entry_id,
        "draft_id": created["draft_id"],
    }
    await client.send_json_auto_id({**abandon, "expected_revision": created["revision"] + 1})
    stale = await client.receive_json()
    assert stale["success"] is False
    assert stale["error"]["code"] == ERR_CANONICAL_V3_DRAFT_STALE

    await client.send_json_auto_id({**abandon, "expected_revision": created["revision"]})
    abandoned = await client.receive_json()
    assert abandoned["success"] is True, abandoned
    assert abandoned["result"]["result"] == {
        "draft_id": created["draft_id"],
        "abandoned_revision": created["revision"],
    }
    assert dict(entry.data) == active_data_before
    active = await backend.repository.get_active_reference(active_v3.scope_key)
    assert active is not None
    assert active.canonical_revision_id == active_v3.revision_id

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_DRAFT,
            "config_entry_id": entry.entry_id,
            "draft_id": created["draft_id"],
        }
    )
    missing = await client.receive_json()
    assert missing["success"] is False
    assert missing["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_v3_canonicalization_revalidates_live_reference_health(
    hass,
    hass_ws_client,
    entry_data,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Fresh v3 validation", data={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    active_v3, backend = await _canonical_v3_candidate(
        hass,
        entry,
        entry_data,
        revision_id="canonical-v3-freshness-base",
        target_temperature=22.0,
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_ACTIVATE,
            "config_entry_id": entry.entry_id,
            "revision_id": active_v3.revision_id,
            "semantic_configuration_fingerprint": active_v3.semantic_configuration_fingerprint,
            "expected_active_revision_id": None,
            "expected_active_generation": 0,
            "attempt_id": "activate-v3-freshness-base",
        }
    )
    assert (await client.receive_json())["success"] is True
    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_EDIT,
            "config_entry_id": entry.entry_id,
            "draft_id": "freshness-v3-draft",
            "created_at": NOW.isoformat(),
            "expected_active_generation": 1,
        }
    )
    draft_response = await client.receive_json()
    assert draft_response["success"] is True, draft_response
    draft = draft_response["result"]["result"]
    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_VALIDATE,
            "config_entry_id": entry.entry_id,
            "draft_id": draft["draft_id"],
            "report_id": "freshness-ready-report",
            "snapshot_id": "freshness-ready-snapshot",
            "evaluated_at": NOW.isoformat(),
        }
    )
    validation_response = await client.receive_json()
    assert validation_response["success"] is True, validation_response
    validation = validation_response["result"]["result"]
    assert validation["activation_ready"] is True

    registry = er.async_get(hass)
    sensor_entity_id = registry.async_get_entity_id(
        "sensor",
        "canonical-test",
        "living-temperature",
    )
    assert sensor_entity_id is not None
    registry.async_remove(sensor_entity_id)

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_CANONICALIZE,
            "config_entry_id": entry.entry_id,
            "draft_id": draft["draft_id"],
            "validation_report_id": validation["report_id"],
            "revision_id": "must-not-canonicalize-stale-health",
            "snapshot_id": "freshness-final-snapshot",
            "created_at": NOW.isoformat(),
            "actor": "test:admin",
            "source": "configuration_v3_api",
            "change_kind": "UPDATE",
            "reason": "reference_removed_after_validation",
            "core_version": "0.17.0",
            "integration_version": "0.14.0",
        }
    )
    canonicalize_response = await client.receive_json()
    assert canonicalize_response["success"] is False
    assert canonicalize_response["error"]["code"] == "setup_conflict"
    with pytest.raises(SetupNotFoundError):
        await backend.repository.get_canonical_revision_v3("must-not-canonicalize-stale-health")


@pytest.mark.asyncio
async def test_greenfield_v3_authoring_validates_canonicalizes_activates_and_restarts(
    hass,
    hass_ws_client,
    entry_data,
    service_calls,
) -> None:
    registry = er.async_get(hass)
    sensor = registry.async_get_or_create(
        "sensor",
        "greenfield-test",
        "living-temperature",
        suggested_object_id="greenfield_temperature",
        original_device_class="temperature",
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    source = registry.async_get_or_create(
        "switch",
        "greenfield-test",
        "boiler",
        suggested_object_id="greenfield_boiler",
    )
    hass.states.async_set(
        sensor.entity_id,
        "20.5",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Greenfield heating", data={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    snapshot = await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
        hass,
        snapshot_id="greenfield-bindings",
        captured_at=NOW,
    )
    by_locator = {item.current_locator: item for item in snapshot.objects if item.current_locator is not None}
    sensor_reference = by_locator[sensor.entity_id].model_dump(mode="json")
    source_reference = by_locator[source.entity_id].model_dump(mode="json")
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_START,
            "config_entry_id": entry.entry_id,
            "draft_id": "greenfield-v3-draft",
            "snapshot_id": "greenfield-start",
            "created_at": NOW.isoformat(),
            "bindings": {
                "zone_display_name": "Living room",
                "primary_sensor_display_name": "Living temperature",
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
    start_response = await client.receive_json()
    assert start_response["success"] is True, start_response
    draft = start_response["result"]["result"]
    assert draft["base_active_revision_id"] is None
    assert draft["base_active_generation"] == 0
    assert draft["schema_version"] == 3
    assert draft["canonical_revision"] == 1
    assert draft["heating"]["zones"][0]["demand_policy"]["target_temperature_celsius"] == 21.0
    assert draft["heating"]["zones"][0]["zone_id"] != sensor_reference["native_id"]
    assert ACTIVE_REFERENCE_KEY not in entry.data

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_VALIDATE,
            "config_entry_id": entry.entry_id,
            "draft_id": draft["draft_id"],
            "report_id": "greenfield-validation",
            "snapshot_id": "greenfield-validation",
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
            "revision_id": "greenfield-v3-canonical",
            "snapshot_id": "greenfield-v3-canonicalize",
            "created_at": NOW.isoformat(),
            "actor": "test:admin",
            "source": "configuration_v3_api",
            "change_kind": "CREATE",
            "reason": "greenfield_setup",
            "core_version": "0.17.0",
            "integration_version": "0.14.0",
        }
    )
    canonical_response = await client.receive_json()
    assert canonical_response["success"] is True, canonical_response
    candidate = canonical_response["result"]["result"]
    assert candidate["revision"] == 1
    assert candidate["parent_revision_id"] is None
    assert ACTIVE_REFERENCE_KEY not in entry.data

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_ACTIVATE,
            "config_entry_id": entry.entry_id,
            "revision_id": candidate["revision_id"],
            "semantic_configuration_fingerprint": candidate["semantic_configuration_fingerprint"],
            "expected_active_revision_id": None,
            "expected_active_generation": 0,
            "attempt_id": "activate-greenfield-v3",
        }
    )
    activation_response = await client.receive_json()
    assert activation_response["success"] is True, activation_response
    await hass.async_block_till_done()
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == candidate["revision_id"]
    assert entry.runtime_data.config.target_temperature == Temperature(21.0)

    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.data.pop(f"{DOMAIN}_setup_backend", None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == candidate["revision_id"]


@pytest.mark.asyncio
async def test_active_v2_conversion_is_idempotent_and_switches_wholly_on_explicit_v3_activation(
    hass,
    hass_ws_client,
    entry_data,
    service_calls,
) -> None:
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20.5",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, title="V2 conversion", data={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    source, backend = await _canonical_candidate(
        hass,
        entry,
        entry_data,
        revision_id="active-v2-conversion-source",
        target_temperature=19.5,
    )
    client = await hass_ws_client(hass)
    source_activation = await async_activate_canonical_revision(
        hass,
        entry,
        revision_id=source.revision_id,
        semantic_configuration_fingerprint=source.semantic_configuration_fingerprint,
        expected_active_revision_id=None,
        expected_active_generation=0,
        attempt_id="activate-v2-conversion-source",
    )
    assert source_activation.state is ActivationState.COMMITTED
    await hass.async_block_till_done()
    source_runtime = entry.runtime_data
    assert source_runtime.config.target_temperature == Temperature(19.5)

    conversion_request = {
        "type": CONFIGURATION_V3_CONVERT_V2,
        "config_entry_id": entry.entry_id,
        "source_revision_id": source.revision_id,
        "draft_id": "active-v2-to-v3-draft",
        "projection_revision_id": "active-v2-to-v3-projection",
        "snapshot_id": "active-v2-to-v3-conversion",
        "created_at": NOW.isoformat(),
        "expected_active_revision_id": source.revision_id,
        "expected_active_generation": 1,
    }
    await client.send_json_auto_id(conversion_request)
    first_response = await client.receive_json()
    assert first_response["success"] is True, first_response
    first_review = first_response["result"]["result"]
    assert first_review["conversion_ready"] is True
    assert first_review["activated"] is False
    draft = first_review["draft"]
    assert draft["base_active_revision_id"] == source.revision_id
    assert draft["base_active_generation"] == 1
    assert draft["parent_revision_id"] == source.revision_id
    assert draft["canonical_revision"] == source.revision + 1
    assert draft["heating"]["zones"][0]["demand_policy"]["target_temperature_celsius"] == 19.5
    assert entry.runtime_data is source_runtime
    source_scope = (source.environment_id, source.module_key, source.module_instance_id)
    active = await backend.repository.get_active_reference(source_scope)
    assert active is not None
    assert active.canonical_revision_id == source.revision_id

    await client.send_json_auto_id(conversion_request)
    repeated_response = await client.receive_json()
    assert repeated_response["success"] is True, repeated_response
    assert repeated_response["result"]["result"] == first_review

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_VALIDATE,
            "config_entry_id": entry.entry_id,
            "draft_id": draft["draft_id"],
            "report_id": "active-v2-to-v3-validation",
            "snapshot_id": "active-v2-to-v3-validation",
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
            "revision_id": "active-v2-to-v3-canonical",
            "snapshot_id": "active-v2-to-v3-canonicalize",
            "created_at": NOW.isoformat(),
            "actor": "test:admin",
            "source": "canonical_v2_conversion_api",
            "change_kind": "MIGRATE",
            "reason": "explicit_v2_conversion",
            "core_version": "0.17.0",
            "integration_version": "0.14.0",
        }
    )
    canonical_response = await client.receive_json()
    assert canonical_response["success"] is True, canonical_response
    candidate = canonical_response["result"]["result"]
    assert entry.runtime_data is source_runtime
    assert (candidate["environment_id"], "heating", candidate["configuration_id"]) == source_scope

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_ACTIVATE,
            "config_entry_id": entry.entry_id,
            "revision_id": candidate["revision_id"],
            "semantic_configuration_fingerprint": candidate["semantic_configuration_fingerprint"],
            "expected_active_revision_id": source.revision_id,
            "expected_active_generation": 1,
            "attempt_id": "activate-active-v2-to-v3",
        }
    )
    activation_response = await client.receive_json()
    assert activation_response["success"] is True, activation_response
    await hass.async_block_till_done()
    assert entry.runtime_data is not source_runtime
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == candidate["revision_id"]
    assert entry.runtime_data.config == replace(source_runtime.config, debug_duration=None)


@pytest.mark.asyncio
async def test_explicit_legacy_to_v2_to_v3_conversion_preserves_runtime_until_activation(
    hass,
    hass_ws_client,
    entry_data,
    service_calls,
) -> None:
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "legacy-conversion-test",
        "living-temperature",
        suggested_object_id="living_room_temperature",
        original_device_class="temperature",
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    hass.states.async_remove("switch.boiler")
    registry.async_get_or_create(
        "switch",
        "legacy-conversion-test",
        "boiler",
        suggested_object_id="boiler",
    )
    hass.states.async_set("switch.boiler", "off")
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20.5",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Legacy heating", data=entry_data)
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    assert await hass.config_entries.async_setup(entry.entry_id)
    original_data = dict(entry.data)
    original_runtime = entry.runtime_data
    expected_converted_config = replace(original_runtime.config, debug_duration=None)
    client = await hass_ws_client(hass)

    conversion_request = {
        "type": CONFIGURATION_V3_CONVERT_LEGACY,
        "config_entry_id": entry.entry_id,
        "draft_id": "legacy-v3-draft",
        "v2_revision_id": "legacy-v2-projection",
        "projection_revision_id": "legacy-v3-projection",
        "snapshot_id": "legacy-v3-conversion",
        "created_at": NOW.isoformat(),
        "core_version": "0.17.0",
        "integration_version": "0.14.0",
    }
    await client.send_json_auto_id(conversion_request)
    conversion_response = await client.receive_json()
    assert conversion_response["success"] is True, conversion_response
    review = conversion_response["result"]["result"]
    assert review["source_kind"] == "legacy_home_assistant"
    assert review["conversion_ready"] is True
    assert review["activated"] is False
    draft = review["draft"]
    assert draft is not None
    assert draft["schema_version"] == 3
    assert draft["migration_provenance"]["conversion_contract"] == ("home_assistant_integration_config_to_heating_v2")
    assert draft["migration_provenance"]["v2_to_v3"]["historical_values_preserved"] is True
    assert all(item["reference"]["identity_quality"] == "EPHEMERAL" for item in review["source_reference_health"])
    assert all(item["status"] == "RESOLVED" for item in review["source_reference_health"])
    assert dict(entry.data) == original_data
    assert entry.runtime_data is original_runtime
    assert entry.runtime_data.loaded_configuration is None
    backend = await async_get_setup_backend(hass, entry)
    with pytest.raises(SetupNotFoundError):
        await backend.repository.get_canonical_revision("legacy-v2-projection")

    await client.send_json_auto_id(conversion_request)
    repeated_response = await client.receive_json()
    assert repeated_response["success"] is True, repeated_response
    assert repeated_response["result"]["result"] == review

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_VALIDATE,
            "config_entry_id": entry.entry_id,
            "draft_id": draft["draft_id"],
            "report_id": "legacy-v3-validation",
            "snapshot_id": "legacy-v3-validation",
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
            "revision_id": "legacy-v3-canonical",
            "snapshot_id": "legacy-v3-canonicalize",
            "created_at": NOW.isoformat(),
            "actor": "test:admin",
            "source": "legacy_conversion_api",
            "change_kind": "MIGRATE",
            "reason": "explicit_legacy_conversion",
            "core_version": "0.17.0",
            "integration_version": "0.14.0",
        }
    )
    canonical_response = await client.receive_json()
    assert canonical_response["success"] is True, canonical_response
    candidate = canonical_response["result"]["result"]
    assert dict(entry.data) == original_data
    assert entry.runtime_data is original_runtime

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_ACTIVATE,
            "config_entry_id": entry.entry_id,
            "revision_id": candidate["revision_id"],
            "semantic_configuration_fingerprint": candidate["semantic_configuration_fingerprint"],
            "expected_active_revision_id": None,
            "expected_active_generation": 0,
            "attempt_id": "activate-legacy-v3",
        }
    )
    activation_response = await client.receive_json()
    assert activation_response["success"] is True, activation_response
    await hass.async_block_till_done()
    assert set(entry.data) == {ACTIVE_REFERENCE_KEY}
    assert dict(entry.options) == {}
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == candidate["revision_id"]
    assert entry.runtime_data.config == expected_converted_config

    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.data.pop(f"{DOMAIN}_setup_backend", None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == candidate["revision_id"]
    assert entry.runtime_data.config == expected_converted_config


@pytest.mark.asyncio
async def test_legacy_conversion_surfaces_ephemeral_missing_bindings_without_a_v3_draft(
    hass,
    hass_ws_client,
    entry_data,
) -> None:
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20.5",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Unregistered legacy heating", data=entry_data)
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    assert await hass.config_entries.async_setup(entry.entry_id)
    original_data = dict(entry.data)
    original_runtime = entry.runtime_data
    original_config = entry.runtime_data.config
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_START,
            "config_entry_id": entry.entry_id,
            "draft_id": "must-not-greenfield-over-legacy",
            "snapshot_id": "must-not-greenfield-over-legacy",
            "created_at": NOW.isoformat(),
            "bindings": {},
        }
    )
    greenfield_response = await client.receive_json()
    assert greenfield_response["success"] is False
    assert greenfield_response["error"]["code"] == "setup_conflict"

    await client.send_json_auto_id(
        {
            "type": CONFIGURATION_V3_CONVERT_LEGACY,
            "config_entry_id": entry.entry_id,
            "draft_id": "unresolved-legacy-v3-draft",
            "v2_revision_id": "unresolved-legacy-v2-projection",
            "projection_revision_id": "unresolved-legacy-v3-projection",
            "snapshot_id": "unresolved-legacy-v3-conversion",
            "created_at": NOW.isoformat(),
            "core_version": "0.17.0",
            "integration_version": "0.14.0",
        }
    )
    response = await client.receive_json()
    assert response["success"] is True, response
    review = response["result"]["result"]
    assert review["conversion_ready"] is False
    assert review["activated"] is False
    assert review["draft"] is None
    assert review["issue_codes"] == ["canonical_v3.conversion.missing"]
    assert review["reference_health"]
    assert review["source_reference_health"] == review["reference_health"]
    assert all(item["reference"]["identity_quality"] == "EPHEMERAL" for item in review["reference_health"])
    assert all(item["status"] == "MISSING" for item in review["reference_health"])
    assert dict(entry.data) == original_data
    assert entry.runtime_data is original_runtime
    assert entry.runtime_data.config == original_config

    provider_instance_id = await async_get_instance_id(hass)
    sensor_override = {
        "provider": "home_assistant",
        "provider_instance_id": provider_instance_id,
        "object_kind": "home_assistant.entity",
        "native_id": "reviewed-missing-temperature-registry-id",
        "identity_quality": "STABLE",
        "current_locator": entry_data[CONF_TEMPERATURE_ENTITY_ID],
    }
    source_override = {
        "provider": "home_assistant",
        "provider_instance_id": provider_instance_id,
        "object_kind": "home_assistant.entity",
        "native_id": "reviewed-missing-source-registry-id",
        "identity_quality": "STABLE",
        "current_locator": "switch.boiler",
    }
    reviewed_request = {
        "type": CONFIGURATION_V3_CONVERT_LEGACY,
        "config_entry_id": entry.entry_id,
        "draft_id": "unresolved-legacy-v3-draft",
        "v2_revision_id": "unresolved-legacy-v2-projection",
        "projection_revision_id": "unresolved-legacy-v3-projection",
        "snapshot_id": "unresolved-legacy-v3-conversion",
        "created_at": NOW.isoformat(),
        "core_version": "0.17.0",
        "integration_version": "0.14.0",
        "binding_overrides": {
            "heating.primary_temperature": sensor_override,
            "heating.source.enable_target": source_override,
            "heating.source.disable_target": source_override,
            "heating.source.reported_state": source_override,
        },
    }
    await client.send_json_auto_id(reviewed_request)
    reviewed_response = await client.receive_json()
    assert reviewed_response["success"] is True, reviewed_response
    reviewed = reviewed_response["result"]["result"]
    assert reviewed["conversion_ready"] is True
    assert reviewed["draft"] is not None
    assert reviewed["issue_codes"] == ["canonical_v3.reference.missing"]
    assert all(item["status"] == "MISSING" for item in reviewed["reference_health"])
    assert dict(entry.data) == original_data
    assert entry.runtime_data is original_runtime
