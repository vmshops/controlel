"""Real Home Assistant coverage for native canonical-v3 Configure."""

from __future__ import annotations

from copy import deepcopy

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
from controlel.application.configuration import ConfigurationEditabilityV3, canonical_field_registry_v3
from controlel.domain.value_objects.temperature import Temperature
from controlel.infrastructure.home_assistant import ACTIVE_REFERENCE_KEY
from custom_components.controlel import config_flow as cf
from custom_components.controlel.const import DOMAIN
from custom_components.controlel.setup_backend import async_get_setup_backend


def _defaults(result) -> dict[str, object]:
    values: dict[str, object] = {}
    for marker in result["data_schema"].schema:
        if marker.default is None:
            continue
        try:
            values[marker.schema] = marker.default()
        except (TypeError, ValueError):
            pass
    return values


def _fields(result) -> set[str]:
    return {marker.schema for marker in result["data_schema"].schema}


def _register_bindings(hass, *, platform: str = "configure-test") -> tuple[str, str]:
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


async def _empty_entry(hass, *, title: str = "Canonical heating") -> MockConfigEntry:
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


async def _through_groups(hass, result, *, target: float | None = None, measurement_age: float | None = None):
    assert result["step_id"] == "zone"
    values = _defaults(result)
    if target is not None:
        values[cf.TARGET_TEMPERATURE] = target
    result = await hass.config_entries.options.async_configure(result["flow_id"], values)

    assert result["step_id"] == "sensor"
    values = _defaults(result)
    if measurement_age is not None:
        values[cf.MEASUREMENT_MAX_AGE] = measurement_age
    result = await hass.config_entries.options.async_configure(result["flow_id"], values)

    for step_id in ("heat_source", "heat_delivery", "safety_timing", "diagnostics", "notifications"):
        assert result["step_id"] == step_id
        result = await hass.config_entries.options.async_configure(result["flow_id"], _defaults(result))
    assert result["step_id"] == "save_draft"
    return result


async def _start_greenfield_draft(hass, entry, sensor_id: str, source_id: str):
    initial = await hass.config_entries.options.async_init(entry.entry_id)
    assert initial["type"] is data_entry_flow.FlowResultType.MENU
    assert initial["menu_options"][0] == "open_wizard"
    start = await _choose(hass, initial, "start_greenfield")
    assert start["step_id"] == "start_greenfield"
    return await hass.config_entries.options.async_configure(
        start["flow_id"],
        {
            cf.ZONE_NAME: "Living room",
            cf.SENSOR_NAME: "Living room temperature",
            cf.TEMPERATURE_ENTITY: sensor_id,
            cf.SOURCE_NAME: "Boiler permission",
            cf.SOURCE_ENTITY: source_id,
            cf.SOURCE_MODE: "simple",
            cf.ENABLE_DOMAIN: "switch",
            cf.ENABLE_SERVICE: "turn_on",
            cf.ENABLE_TARGET: source_id,
            cf.DISABLE_DOMAIN: "switch",
            cf.DISABLE_SERVICE: "turn_off",
            cf.DISABLE_TARGET: source_id,
            cf.REPORTED_SOURCE_STATE: source_id,
        },
    )


async def _save_draft(hass, result):
    saved = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert saved["type"] is data_entry_flow.FlowResultType.MENU
    assert saved["step_id"] == "draft_saved"
    return saved


async def _prepare_activation(hass, saved):
    validate = await _choose(hass, saved, "validate")
    assert validate["step_id"] == "validate"
    validated = await hass.config_entries.options.async_configure(validate["flow_id"], {})
    assert validated["step_id"] == "validation_result"
    canonicalize = await hass.config_entries.options.async_configure(validated["flow_id"], {})
    assert canonicalize["step_id"] == "canonicalize"
    activate = await hass.config_entries.options.async_configure(canonicalize["flow_id"], {})
    assert activate["step_id"] == "activate"
    return activate


@pytest.mark.asyncio
async def test_greenfield_config_entry_is_empty_v3_shell_and_links_to_configure(hass) -> None:
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert initial["type"] is data_entry_flow.FlowResultType.FORM
    assert not _fields(initial)
    assert initial["description_placeholders"]["configure_explanation"] == cf.TOP_EXPLANATION

    result = await hass.config_entries.flow.async_configure(initial["flow_id"], {})
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"] == {}
    assert result["options"] == {}
    assert result["next_flow"][0] is config_entries.FlowType.OPTIONS_FLOW
    assert isinstance(result["next_flow"][1], str)


@pytest.mark.asyncio
async def test_greenfield_save_validate_and_activation_are_separate_and_restart_safe(
    hass,
    service_calls,
) -> None:
    sensor_id, source_id = _register_bindings(hass)
    entry = await _empty_entry(hass)
    result = await _start_greenfield_draft(hass, entry, sensor_id, source_id)
    result = await _through_groups(hass, result, target=22.25, measurement_age=91.25)
    saved = await _save_draft(hass, result)

    backend = await async_get_setup_backend(hass, entry)
    drafts = await backend.configuration_v3.list_drafts()
    assert len(drafts) == 1
    assert drafts[0].schema_version == 3
    assert drafts[0].revision == 2
    assert drafts[0].heating.zones[0].demand_policy.target_temperature_celsius == 22.25
    assert drafts[0].heating.zones[0].demand_policy.primary_measurement_max_age_seconds == 91.25
    assert ACTIVE_REFERENCE_KEY not in entry.data
    assert entry.options == {}
    assert entry.runtime_data.host is None

    activate = await _prepare_activation(hass, saved)
    assert ACTIVE_REFERENCE_KEY not in entry.data
    assert entry.runtime_data.host is None

    completed = await hass.config_entries.options.async_configure(activate["flow_id"], {})
    assert completed["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert set(entry.data) == {ACTIVE_REFERENCE_KEY}
    assert entry.options == {}
    assert entry.runtime_data.config.target_temperature == Temperature(22.25)
    assert entry.runtime_data.config.primary_measurement_max_age.total_seconds() == 91.25
    active_revision_id = entry.runtime_data.loaded_configuration.canonical_revision_id

    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.data.pop(f"{DOMAIN}_setup_backend", None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == active_revision_id
    assert entry.runtime_data.config.target_temperature == Temperature(22.25)
    assert entry.runtime_data.config.primary_measurement_max_age.total_seconds() == 91.25
    assert service_calls == []


@pytest.mark.asyncio
async def test_active_v3_edit_changes_one_field_only_and_requires_explicit_activation(hass, service_calls) -> None:
    sensor_id, source_id = _register_bindings(hass, platform="active-edit-test")
    entry = await _empty_entry(hass)
    created = await _through_groups(
        hass,
        await _start_greenfield_draft(hass, entry, sensor_id, source_id),
    )
    activated = await _prepare_activation(hass, await _save_draft(hass, created))
    await hass.config_entries.options.async_configure(activated["flow_id"], {})
    await hass.async_block_till_done()

    before_reference = deepcopy(entry.data[ACTIVE_REFERENCE_KEY])
    before_runtime = entry.runtime_data
    backend = await async_get_setup_backend(hass, entry)
    before = await backend.repository.get_canonical_revision_v3(
        entry.runtime_data.loaded_configuration.canonical_revision_id
    )

    initial = await hass.config_entries.options.async_init(entry.entry_id)
    edit = await _choose(hass, initial, "edit_active")
    saved = await _save_draft(hass, await _through_groups(hass, edit, target=23.5))

    assert entry.data[ACTIVE_REFERENCE_KEY] == before_reference
    assert entry.options == {}
    assert entry.runtime_data is before_runtime
    assert entry.runtime_data.config.target_temperature == Temperature(21.0)
    draft = (await backend.configuration_v3.list_drafts())[-1]
    assert draft.heating.zones[0].demand_policy.target_temperature_celsius == 23.5
    before_document = before.semantic_data()
    draft_document = draft._semantic_revision().semantic_data()
    before_document["heating"]["zones"][0]["demand_policy"]["target_temperature_celsius"] = 23.5
    assert draft_document == before_document

    activate = await _prepare_activation(hass, saved)
    assert entry.data[ACTIVE_REFERENCE_KEY] == before_reference
    await hass.config_entries.options.async_configure(activate["flow_id"], {})
    await hass.async_block_till_done()
    assert entry.runtime_data is not before_runtime
    assert entry.runtime_data.config.target_temperature == Temperature(23.5)
    assert set(entry.data) == {ACTIVE_REFERENCE_KEY}
    assert service_calls == []


@pytest.mark.asyncio
async def test_durable_draft_can_be_resumed_and_abandoned(hass) -> None:
    sensor_id, source_id = _register_bindings(hass, platform="resume-test")
    entry = await _empty_entry(hass)
    result = await _start_greenfield_draft(hass, entry, sensor_id, source_id)
    backend = await async_get_setup_backend(hass, entry)
    draft = (await backend.configuration_v3.list_drafts())[0]
    hass.config_entries.options.async_abort(result["flow_id"])

    initial = await hass.config_entries.options.async_init(entry.entry_id)
    assert "resume_draft" in initial["menu_options"]
    resume = await _choose(hass, initial, "resume_draft")
    resumed = await hass.config_entries.options.async_configure(resume["flow_id"], {"draft_id": draft.draft_id})
    assert resumed["step_id"] == "zone"
    assert _defaults(resumed)[cf.ZONE_NAME] == "Living room"
    hass.config_entries.options.async_abort(resumed["flow_id"])

    initial = await hass.config_entries.options.async_init(entry.entry_id)
    abandon = await _choose(hass, initial, "abandon_draft")
    abandoned = await hass.config_entries.options.async_configure(abandon["flow_id"], {"draft_id": draft.draft_id})
    assert abandoned["type"] is data_entry_flow.FlowResultType.ABORT
    assert abandoned["reason"] == "draft_abandoned"
    assert await backend.configuration_v3.list_drafts() == ()
    assert entry.data == {}
    assert entry.options == {}


@pytest.mark.asyncio
async def test_legacy_requires_explicit_conversion_and_never_mixes_authorities(
    hass,
    entry_data,
    service_calls,
) -> None:
    sensor_id, source_id = _register_bindings(hass, platform="legacy-flow-test")
    legacy_data = dict(entry_data)
    legacy_data["temperature_entity_id"] = sensor_id
    legacy_data["enable_target_entity_id"] = source_id
    legacy_data["disable_target_entity_id"] = source_id
    entry = MockConfigEntry(domain=DOMAIN, title="Legacy", data=legacy_data, options={"target_temperature": 20.75})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    assert await hass.config_entries.async_setup(entry.entry_id)
    original_data, original_options = deepcopy(dict(entry.data)), deepcopy(dict(entry.options))
    original_runtime = entry.runtime_data

    initial = await hass.config_entries.options.async_init(entry.entry_id)
    assert "convert_legacy" in initial["menu_options"]
    assert "edit_active" not in initial["menu_options"]
    assert "start_greenfield" not in initial["menu_options"]
    convert = await _choose(hass, initial, "convert_legacy")
    review = await hass.config_entries.options.async_configure(convert["flow_id"], {})
    saved = await _save_draft(hass, await _through_groups(hass, review))
    assert entry.data == original_data
    assert entry.options == original_options
    assert entry.runtime_data is original_runtime
    backend = await async_get_setup_backend(hass, entry)
    draft = (await backend.configuration_v3.list_drafts())[0]
    assert draft.migration_provenance["conversion_contract"] == "home_assistant_integration_config_to_heating_v2"

    activate = await _prepare_activation(hass, saved)
    assert entry.data == original_data
    assert entry.options == original_options
    await hass.config_entries.options.async_configure(activate["flow_id"], {})
    await hass.async_block_till_done()
    assert set(entry.data) == {ACTIVE_REFERENCE_KEY}
    assert entry.options == {}
    assert entry.runtime_data is not original_runtime
    assert entry.runtime_data.config.target_temperature == Temperature(20.75)
    assert service_calls == []


def test_native_ha_field_projection_has_full_editable_registry_parity() -> None:
    registry = canonical_field_registry_v3()
    editable = {
        item.canonical_path
        for item in registry
        if item.editability
        in {ConfigurationEditabilityV3.EDITABLE, ConfigurationEditabilityV3.EDITABLE_PROVIDER_BINDING}
    }
    deferred = {
        item.canonical_path for item in registry if item.editability is ConfigurationEditabilityV3.DEFERRED_NON_EDITABLE
    }
    assert set(cf.CANONICAL_V3_HA_EDITABLE_FIELD_PATHS) == editable == set(cf._FORM_PATHS)
    assert deferred == {
        "heating.heat_sources[].observations.physical_operation_reference",
        "diagnostics.debug_policy.until_changed",
    }
    assert deferred.isdisjoint(cf.CANONICAL_V3_HA_EDITABLE_FIELD_PATHS)
    assert set(cf._FORM_PATHS.values()) == {
        cf.ZONE_NAME,
        cf.ZONE_AREA,
        cf.ZONE_FLOOR,
        cf.TARGET_TEMPERATURE,
        cf.TURN_ON_DIFFERENTIAL,
        cf.TURN_OFF_DIFFERENTIAL,
        cf.DEMAND_CONFIRMATION,
        cf.SENSOR_NAME,
        cf.TEMPERATURE_ENTITY,
        cf.MEASUREMENT_MAX_AGE,
        cf.SOURCE_NAME,
        cf.SOURCE_ENTITY,
        cf.SOURCE_MODE,
        cf.ENABLE_DOMAIN,
        cf.ENABLE_SERVICE,
        cf.ENABLE_TARGET,
        cf.DISABLE_DOMAIN,
        cf.DISABLE_SERVICE,
        cf.DISABLE_TARGET,
        cf.REPORTED_SOURCE_STATE,
        cf.DELIVERY_MODE,
        cf.DELIVERY_ACTUATOR,
        cf.DELIVERY_OWNERSHIP,
        cf.DELIVERY_ASSIST_POLICY,
        cf.DELIVERY_ASSIST_TARGET,
        cf.MAXIMUM_FUTURE_SKEW,
        cf.INDETERMINATE_GRACE,
        cf.INDETERMINATE_ACTION,
        cf.MINIMUM_ON,
        cf.MINIMUM_OFF,
        cf.DIAGNOSTIC_PROFILE,
        cf.DEBUG_DURATION,
        cf.NOTIFICATIONS_ENABLED,
        cf.NOTIFICATION_RECIPIENTS,
        cf.NOTIFICATION_MAXIMUM,
        cf.NOTIFICATION_WINDOW,
        cf.CRITICAL_NOTIFICATION_MAXIMUM,
        cf.CRITICAL_NOTIFICATION_WINDOW,
        cf.NOTIFICATION_HISTORY,
    }


@pytest.mark.asyncio
async def test_mixed_legacy_and_canonical_authority_is_rejected(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={ACTIVE_REFERENCE_KEY: {"canonical_revision_id": "revision-v3"}, "zone_name": "Legacy"},
        options={"target_temperature": 20.0},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "canonical_legacy_mixed"
    assert entry.data["zone_name"] == "Legacy"
    assert entry.options == {"target_temperature": 20.0}


@pytest.mark.asyncio
async def test_real_single_entry_guard_aborts_second_flow(hass) -> None:
    MockConfigEntry(domain=DOMAIN, data={}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
