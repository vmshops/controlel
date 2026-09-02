"""Real Home Assistant coverage for native canonical-v3 Configure."""

from __future__ import annotations

from copy import deepcopy

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.components.valve import ValveDeviceClass, ValveEntityFeature
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
from controlel.application.configuration import ConfigurationEditabilityV3, canonical_field_registry_v3
from controlel.application.setup import ActiveReference
from controlel.domain.value_objects.temperature import Temperature
from controlel.infrastructure.home_assistant import (
    ACTIVE_REFERENCE_KEY,
    ACTIVE_REFERENCES_KEY,
    active_reference_for_module,
)
from custom_components.controlel import config_flow as cf
from custom_components.controlel.const import DOMAIN
from custom_components.controlel.setup_backend import async_get_setup_backend, async_get_setup_service


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


def _fields(result) -> set[str]:
    return {marker.schema for marker in result["data_schema"].schema}


def _field(result, name: str):
    return next(validator for marker, validator in result["data_schema"].schema.items() if marker.schema == name)


def _suggested(result, name: str):
    marker = next(marker for marker in result["data_schema"].schema if marker.schema == name)
    return marker.description.get("suggested_value")


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


def _register_water_candidates(hass):
    areas = ar.async_get(hass)
    utility = areas.async_create("Utility room")
    garage = areas.async_create("Garage")
    registry = er.async_get(hass)

    def create(domain: str, unique_id: str, *, area_id: str | None, device_class: str | None):
        entry = registry.async_get_or_create(
            domain,
            "water-configure-test",
            unique_id,
            suggested_object_id=unique_id,
            original_device_class=device_class,
        )
        if area_id is not None:
            entry = registry.async_update_entity(entry.entity_id, area_id=area_id)
        return entry.entity_id

    inside = create("binary_sensor", "utility_water", area_id=utility.id, device_class="moisture")
    outside = create("binary_sensor", "garage_water", area_id=garage.id, device_class="moisture")
    unrelated = (
        create("binary_sensor", "utility_door", area_id=utility.id, device_class="door"),
        create("binary_sensor", "utility_leak_named_only", area_id=utility.id, device_class=None),
        create("sensor", "utility_moisture_percent", area_id=utility.id, device_class="moisture"),
    )
    return utility, garage, inside, outside, unrelated


def _register_notify_targets(hass, *services: str, calls: list[tuple[str, dict[str, object]]] | None = None):
    async def record(call) -> None:
        if calls is not None:
            calls.append((call.service, dict(call.data)))

    for service in services:
        hass.services.async_register("notify", service, record)
    return tuple(f"notify.{service}" for service in services)


def _register_siren_candidates(hass):
    registry = er.async_get(hass)

    def create(domain: str, unique_id: str) -> str:
        return registry.async_get_or_create(
            domain,
            "water-siren-configure-test",
            unique_id,
            suggested_object_id=unique_id,
        ).entity_id

    compatible = (create("siren", "hall_alarm"), create("siren", "cellar_alarm"))
    incompatible = (create("switch", "garage_siren"), create("alarm_control_panel", "home_alarm"))
    return (*compatible, incompatible)


def _register_shutoff_valve_candidates(hass):
    registry = er.async_get(hass)

    def create(
        domain: str,
        unique_id: str,
        *,
        device_class: str | None = None,
        supported_features: int = 0,
    ) -> str:
        return registry.async_get_or_create(
            domain,
            "water-shutoff-configure-test",
            unique_id,
            suggested_object_id=unique_id,
            original_device_class=device_class,
            supported_features=supported_features,
        ).entity_id

    close = int(ValveEntityFeature.CLOSE)
    compatible = (
        create("valve", "utility_water_main", device_class=ValveDeviceClass.WATER, supported_features=close),
        create("valve", "street_water_main", device_class=ValveDeviceClass.WATER, supported_features=close),
    )
    incompatible = (
        create(
            "valve",
            "utility_water_open_only",
            device_class=ValveDeviceClass.WATER,
            supported_features=int(ValveEntityFeature.OPEN),
        ),
        create("valve", "utility_gas_main", device_class=ValveDeviceClass.GAS, supported_features=close),
        create("switch", "legacy_water_valve"),
    )
    return (*compatible, incompatible)


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


async def _open_hub(hass, entry):
    hub = await hass.config_entries.options.async_init(entry.entry_id)
    assert hub["type"] is data_entry_flow.FlowResultType.MENU
    assert hub["step_id"] == "init"
    return hub


async def _open_heating_menu(hass, entry, *, hub=None):
    if hub is None:
        hub = await _open_hub(hass, entry)
    heating = await _choose(hass, hub, "heating")
    assert heating["step_id"] == "heating"
    return heating


async def _through_groups(hass, result, *, target: float | None = None, measurement_age: float | None = None):
    assert result["step_id"] == "heating"
    zone = await _choose(hass, result, "zone")
    values = _defaults(zone)
    if target is not None:
        values[cf.TARGET_TEMPERATURE] = target
    result = await hass.config_entries.options.async_configure(zone["flow_id"], values)

    assert result["step_id"] == "heating"
    sensor = await _choose(hass, result, "sensor")
    values = _defaults(sensor)
    if measurement_age is not None:
        values[cf.MEASUREMENT_MAX_AGE] = measurement_age
    result = await hass.config_entries.options.async_configure(sensor["flow_id"], values)

    for step_id in ("heat_source", "heat_delivery", "safety_timing", "diagnostics", "notifications"):
        assert result["step_id"] == "heating"
        section = await _choose(hass, result, step_id)
        assert section["step_id"] == step_id
        result = await hass.config_entries.options.async_configure(section["flow_id"], _defaults(section))
    assert result["step_id"] == "heating"
    return result


async def _start_greenfield_draft(hass, entry, sensor_id: str, source_id: str):
    heating = await _open_heating_menu(hass, entry)
    assert heating["menu_options"][0] == "heating_status"
    assert all("wizard" not in option for option in heating["menu_options"])
    start = await _choose(hass, heating, "start_greenfield")
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
    del hass
    assert result["type"] is data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "heating"
    return result


async def _prepare_activation(hass, saved):
    review = await _choose(hass, saved, "heating_review")
    assert review["step_id"] == "heating_review"
    activate = await hass.config_entries.options.async_configure(review["flow_id"], {})
    assert activate["step_id"] == "activate"
    return activate


async def _activate_new_heating(hass, entry, *, platform: str) -> ActiveReference:
    sensor_id, source_id = _register_bindings(hass, platform=platform)
    draft = await _start_greenfield_draft(hass, entry, sensor_id, source_id)
    activate = await _prepare_activation(hass, await _save_draft(hass, draft))
    completed = await hass.config_entries.options.async_configure(activate["flow_id"], {})
    assert completed["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    active = active_reference_for_module(entry.data, "heating")
    assert active is not None
    return active


@pytest.mark.asyncio
async def test_greenfield_config_entry_is_empty_v3_shell_and_links_to_configure(hass) -> None:
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert initial["type"] is data_entry_flow.FlowResultType.FORM
    assert not _fields(initial)
    assert initial["description_placeholders"]["configure_explanation"] == cf.CREATE_EXPLANATION

    result = await hass.config_entries.flow.async_configure(initial["flow_id"], {})
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Controlel"
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
    assert drafts[0].revision == 8
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

    initial = await _open_heating_menu(hass, entry)
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

    initial = await _open_heating_menu(hass, entry)
    assert "resume_draft" in initial["menu_options"]
    resume = await _choose(hass, initial, "resume_draft")
    resumed = await hass.config_entries.options.async_configure(resume["flow_id"], {"draft_id": draft.draft_id})
    assert resumed["step_id"] == "heating"
    zone = await _choose(hass, resumed, "zone")
    assert _defaults(zone)[cf.ZONE_NAME] == "Living room"
    hass.config_entries.options.async_abort(zone["flow_id"])

    initial = await _open_heating_menu(hass, entry)
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

    initial = await _open_heating_menu(hass, entry)
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


@pytest.mark.asyncio
async def test_configure_opens_hub_with_module_menu(hass) -> None:
    entry = await _empty_entry(hass)
    hub = await _open_hub(hass, entry)
    assert hub["description_placeholders"]["hub_explanation"] == cf.HUB_EXPLANATION
    assert list(hub["menu_options"]) == list(cf.HUB_MENU_OPTIONS)


@pytest.mark.asyncio
async def test_heating_route_reaches_existing_configuration_menu(hass) -> None:
    entry = await _empty_entry(hass)
    heating = await _open_heating_menu(hass, entry)
    assert "start_greenfield" in heating["menu_options"]
    assert "heating_status" in heating["menu_options"]
    assert all("wizard" not in option for option in heating["menu_options"])
    assert "back_to_hub" in heating["menu_options"]


@pytest.mark.asyncio
async def test_heating_section_router_saves_partial_draft_and_reopens_current_values(hass) -> None:
    sensor_id, source_id = _register_bindings(hass, platform="heating-sections")
    entry = await _empty_entry(hass)

    heating = await _start_greenfield_draft(hass, entry, sensor_id, source_id)
    assert list(heating["menu_options"]) == list(cf.HEATING_SECTION_MENU_OPTIONS)
    assert "inactive Heating draft" not in heating["description_placeholders"]["heating_summary"]
    backend = await async_get_setup_backend(hass, entry)
    draft = (await backend.configuration_v3.list_drafts())[0]
    assert draft.revision == 1
    assert active_reference_for_module(entry.data, "heating") is None

    status = await _choose(hass, heating, "heating_status")
    assert status["menu_options"] == ["back_to_heating"]
    heating = await _choose(hass, status, "back_to_heating")

    zone = await _choose(hass, heating, "zone")
    zone_values = _defaults(zone)
    zone_values[cf.TARGET_TEMPERATURE] = 22.75
    heating = await hass.config_entries.options.async_configure(zone["flow_id"], zone_values)
    assert heating["step_id"] == "heating"
    draft = (await backend.configuration_v3.list_drafts())[0]
    assert draft.revision == 2
    assert draft.heating.zones[0].demand_policy.target_temperature_celsius == 22.75
    assert draft.heating.zones[0].primary_temperature_sensor.provider_reference.current_locator == sensor_id
    assert active_reference_for_module(entry.data, "heating") is None
    hass.config_entries.options.async_abort(heating["flow_id"])

    reopened = await _open_heating_menu(hass, entry)
    resume = await _choose(hass, reopened, "resume_draft")
    resumed = await hass.config_entries.options.async_configure(resume["flow_id"], {"draft_id": draft.draft_id})
    zone = await _choose(hass, resumed, "zone")
    assert _defaults(zone)[cf.TARGET_TEMPERATURE] == 22.75


@pytest.mark.asyncio
async def test_heating_section_can_clear_optional_references_without_changing_other_sections(hass) -> None:
    sensor_id, source_id = _register_bindings(hass, platform="heating-clear")
    entry = await _empty_entry(hass)
    heating = await _start_greenfield_draft(hass, entry, sensor_id, source_id)
    backend = await async_get_setup_backend(hass, entry)
    before = (await backend.configuration_v3.list_drafts())[0]

    source = await _choose(hass, heating, "heat_source")
    source_values = _defaults(source)
    source_values.pop(cf.SOURCE_ENTITY)
    source_values.pop(cf.REPORTED_SOURCE_STATE)
    heating = await hass.config_entries.options.async_configure(source["flow_id"], source_values)

    after = (await backend.configuration_v3.list_drafts())[0]
    assert after.heating.heat_sources[0].provider_reference is None
    assert after.heating.heat_sources[0].observations.reported_actuator_state_reference is None
    assert after.heating.zones == before.heating.zones
    assert after.notifications == before.notifications
    assert active_reference_for_module(entry.data, "heating") is None
    assert heating["step_id"] == "heating"


@pytest.mark.asyncio
async def test_missing_and_unavailable_heating_entities_remain_visible_in_active_edit_draft(hass) -> None:
    sensor_id, source_id = _register_bindings(hass, platform="heating-missing")
    entry = await _empty_entry(hass)
    configured = await _through_groups(
        hass,
        await _start_greenfield_draft(hass, entry, sensor_id, source_id),
    )
    activate = await _prepare_activation(hass, configured)
    await hass.config_entries.options.async_configure(activate["flow_id"], {})
    await hass.async_block_till_done()
    active_before = active_reference_for_module(entry.data, "heating")
    hass.states.async_set(sensor_id, "unavailable")
    hass.states.async_remove(source_id)
    er.async_get(hass).async_remove(source_id)

    edit = await _choose(hass, await _open_heating_menu(hass, entry), "edit_active")
    sensor = await _choose(hass, edit, "sensor")
    assert _defaults(sensor)[cf.TEMPERATURE_ENTITY] == sensor_id
    hass.config_entries.options.async_abort(sensor["flow_id"])

    reopened = await _open_heating_menu(hass, entry)
    resume = await _choose(hass, reopened, "resume_draft")
    resumed = await hass.config_entries.options.async_configure(
        resume["flow_id"],
        {"draft_id": (await (await async_get_setup_backend(hass, entry)).configuration_v3.list_drafts())[-1].draft_id},
    )
    source = await _choose(hass, resumed, "heat_source")
    defaults = _defaults(source)
    assert defaults[cf.ENABLE_TARGET] == source_id
    assert defaults[cf.DISABLE_TARGET] == source_id
    assert active_reference_for_module(entry.data, "heating") == active_before


async def _open_water_menu(hass, entry, *, hub=None):
    if hub is None:
        hub = await _open_hub(hass, entry)
    water = await _choose(hass, hub, "water_safety")
    assert water["step_id"] == "water_safety"
    return water


async def _water_drafts(hass, entry):
    from custom_components.controlel.water_safety_configure_view import async_list_module_drafts

    backend = await async_get_setup_backend(hass, entry)
    return await async_list_module_drafts(backend.repository, "water_safety")


async def _activate_water_draft(hass, water_menu):
    review = await _choose(hass, water_menu, "water_safety_validation")
    assert review["type"] is data_entry_flow.FlowResultType.FORM
    assert "ready for activation" in review["description_placeholders"]["validation_summary"]
    confirmation = await hass.config_entries.options.async_configure(review["flow_id"], {})
    assert confirmation["type"] is data_entry_flow.FlowResultType.FORM
    assert confirmation["step_id"] == "water_safety_activate"
    return await hass.config_entries.options.async_configure(confirmation["flow_id"], {})


async def _seed_water_draft(hass, entry, *, complete: bool = False):
    from datetime import UTC, datetime

    from controlel.application.configuration.water_safety_setup_adapter import (
        DEFAULT_NOTIFICATION_ROLE,
        WATER_SAFETY_MODULE_KEY,
        WATER_SAFETY_SENSOR_ROLE,
        WaterSafetySetupAdapter,
    )
    from controlel.application.setup import (
        BindingSelection,
        DraftRevision,
        IdentityQuality,
        ProviderReference,
        SelectionOrigin,
    )

    backend = await async_get_setup_backend(hass, entry)
    repository = backend.repository
    now = datetime.now(UTC)
    bindings = (
        BindingSelection(
            role=WATER_SAFETY_SENSOR_ROLE,
            reference=ProviderReference(
                provider="home_assistant",
                provider_instance_id="home",
                object_kind="home_assistant.entity",
                native_id="binary_sensor.utility_moisture",
                identity_quality=IdentityQuality.STABLE,
                current_locator="binary_sensor.utility_moisture",
            ),
            selection_origin=SelectionOrigin.MANUAL,
            user_confirmed=complete,
        ),
        BindingSelection(
            role=DEFAULT_NOTIFICATION_ROLE,
            reference=ProviderReference(
                provider="home_assistant",
                provider_instance_id="home",
                object_kind="home_assistant.endpoint",
                native_id="notify.mobile_app_phone",
                identity_quality=IdentityQuality.STABLE,
                current_locator="notify.mobile_app_phone",
            ),
            selection_origin=SelectionOrigin.MANUAL,
            user_confirmed=complete,
        ),
    )
    draft = DraftRevision(
        draft_id="water-draft",
        revision=1,
        environment_id="home",
        module_key=WATER_SAFETY_MODULE_KEY,
        module_instance_id="utility-water",
        module_schema_version=1,
        created_at=now,
        updated_at=now,
        settings={
            "behavior_contract_version": 1,
            "zone_id": "utility",
            "zone_name": "Utility",
            "area_id": "utility-room",
            "area_name": "Utility room",
            "sensor_id": "utility-moisture",
            "critical_sensor": False,
            "unavailable_grace_seconds": 30.0,
            "fault_repeat_interval_seconds": 120.0,
            "notification_target_roles": [DEFAULT_NOTIFICATION_ROLE],
            "siren_target_roles": [],
            "messages": {},
        },
        bindings=bindings if complete else (),
    )
    await repository.save_draft(draft)
    adapter = WaterSafetySetupAdapter()
    report = adapter.validate(draft, report_id="water-report", evaluated_at=now)
    await repository.save_validation_report(report)
    return draft, report


async def _seed_configured_water(hass, entry):
    from datetime import UTC, datetime

    from controlel.application.configuration.water_safety_setup_adapter import WaterSafetySetupAdapter
    from controlel.application.setup import ActiveReference

    draft, report = await _seed_water_draft(hass, entry, complete=True)
    adapter = WaterSafetySetupAdapter()
    now = datetime.now(UTC)
    canonical = adapter.canonicalize(
        draft,
        report,
        configuration_id="water-config",
        revision_id="water-revision",
        revision=1,
        provider="home_assistant",
        provider_instance_id="home",
        created_at=now,
        actor="test",
        source="home_assistant_native_configure_test",
        change_kind="CREATE",
        reason="test",
        core_version="0.17.0",
    )
    backend = await async_get_setup_backend(hass, entry)
    await backend.repository.add_canonical_revision(canonical)
    active = ActiveReference(
        environment_id="home",
        module_key="water_safety",
        module_instance_id="utility-water",
        canonical_revision_id="water-revision",
        semantic_configuration_fingerprint=canonical.semantic_configuration_fingerprint,
        generation=1,
        committing_operation_id="test-op",
    )
    hass.config_entries.async_update_entry(
        entry,
        data={ACTIVE_REFERENCE_KEY: active.model_dump(mode="json")},
        options={},
    )
    return draft, canonical, active


async def _activate_new_water(hass, entry) -> ActiveReference:
    await _seed_water_draft(hass, entry, complete=True)
    completed = await _activate_water_draft(hass, await _open_water_menu(hass, entry))
    assert completed["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    active = active_reference_for_module(entry.data, "water_safety")
    assert active is not None
    return active


@pytest.mark.asyncio
async def test_water_safety_native_menu_structure(hass) -> None:
    entry = await _empty_entry(hass)
    water = await _open_water_menu(hass, entry)
    assert list(water["menu_options"]) == list(cf.WATER_SAFETY_MENU_OPTIONS)
    assert all("wizard" not in option for option in water["menu_options"])
    assert "water_safety_sensor_fault" not in water["menu_options"]
    assert "water_safety_messages" not in water["menu_options"]
    assert "not configured" in water["description_placeholders"]["water_safety_summary"].lower()


@pytest.mark.asyncio
async def test_water_safety_submenu_navigation_returns_to_module_menu(hass) -> None:
    entry = await _empty_entry(hass)
    water = await _open_water_menu(hass, entry)
    for step_id in ("water_safety_status",):
        section = await _choose(hass, water, step_id)
        assert section["step_id"] == step_id
        assert section["menu_options"] == ["back_to_water_safety"]
        assert "section_detail" in section["description_placeholders"]
        water = await _choose(hass, section, "back_to_water_safety")
        assert water["step_id"] == "water_safety"

    notifications = await _choose(hass, water, "water_safety_notifications")
    assert notifications["type"] is data_entry_flow.FlowResultType.FORM
    assert notifications["step_id"] == "water_safety_notifications"
    assert _fields(notifications) == {cf.WATER_NOTIFICATION_TARGETS, cf.WATER_TEST_NOTIFICATION}
    hass.config_entries.options.async_abort(notifications["flow_id"])

    water = await _open_water_menu(hass, entry)

    sirens = await _choose(hass, water, "water_safety_sirens")
    assert sirens["type"] is data_entry_flow.FlowResultType.FORM
    assert sirens["step_id"] == "water_safety_sirens"
    assert _fields(sirens) == {cf.WATER_SIREN_TARGETS}
    hass.config_entries.options.async_abort(sirens["flow_id"])

    water = await _open_water_menu(hass, entry)

    shutoff_valves = await _choose(hass, water, "water_safety_shutoff_valves")
    assert shutoff_valves["type"] is data_entry_flow.FlowResultType.FORM
    assert shutoff_valves["step_id"] == "water_safety_shutoff_valves"
    assert _fields(shutoff_valves) == {cf.WATER_SHUTOFF_VALVE_TARGETS}
    hass.config_entries.options.async_abort(shutoff_valves["flow_id"])

    water = await _open_water_menu(hass, entry)

    area_sensor = await _choose(hass, water, "water_safety_area_sensor")
    assert area_sensor["type"] is data_entry_flow.FlowResultType.FORM
    assert area_sensor["step_id"] == "water_safety_area_sensor"
    assert _fields(area_sensor) == {
        cf.WATER_AREA,
        cf.WATER_MOISTURE_SENSOR,
        cf.WATER_SHOW_ALL_COMPATIBLE,
    }
    hass.config_entries.options.async_abort(area_sensor["flow_id"])


@pytest.mark.asyncio
async def test_water_safety_back_to_hub_navigation(hass) -> None:
    entry = await _empty_entry(hass)
    water = await _open_water_menu(hass, entry)
    hub_again = await _choose(hass, water, "back_to_hub")
    assert hub_again["step_id"] == "init"
    assert list(hub_again["menu_options"]) == list(cf.HUB_MENU_OPTIONS)


@pytest.mark.asyncio
async def test_fresh_water_safety_menu_reports_not_configured(hass) -> None:
    entry = await _empty_entry(hass)
    water = await _open_water_menu(hass, entry)
    status = await _choose(hass, water, "water_safety_status")
    assert status["description_placeholders"]["section_detail"] == "Not configured."
    area = await _choose(hass, await _choose(hass, status, "back_to_water_safety"), "water_safety_area_sensor")
    assert area["type"] is data_entry_flow.FlowResultType.FORM
    assert cf.WATER_AREA not in _defaults(area)
    assert cf.WATER_MOISTURE_SENSOR not in _defaults(area)
    assert "Disabled" not in water["description_placeholders"]["water_safety_summary"]


@pytest.mark.asyncio
async def test_water_area_only_save_is_partial_durable_and_reloadable(hass) -> None:
    utility, _garage, inside, outside, _unrelated = _register_water_candidates(hass)
    entry = await _empty_entry(hass)
    area_form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_area_sensor")

    initial_selector = _field(area_form, cf.WATER_MOISTURE_SENSOR)
    assert isinstance(initial_selector, selector.EntitySelector)
    assert set(initial_selector.config["include_entities"]) == {inside, outside}
    saved_menu = await hass.config_entries.options.async_configure(
        area_form["flow_id"],
        {
            cf.WATER_AREA: utility.id,
            cf.WATER_SHOW_ALL_COMPATIBLE: False,
        },
    )

    assert saved_menu["step_id"] == "water_safety"
    assert "Draft incomplete" in saved_menu["description_placeholders"]["water_safety_summary"]
    draft = (await _water_drafts(hass, entry))[0]
    assert dict(draft.settings) == {
        "zone_id": utility.id,
        "zone_name": utility.name,
        "area_id": utility.id,
        "area_name": utility.name,
    }
    assert draft.bindings == ()
    assert ACTIVE_REFERENCE_KEY not in entry.data
    backend = await async_get_setup_backend(hass, entry)
    water_service = await async_get_setup_service(hass, entry, module_key="water_safety")
    assert water_service._repository is backend.repository

    reloaded = await _choose(hass, saved_menu, "water_safety_area_sensor")
    assert _suggested(reloaded, cf.WATER_AREA) == utility.id
    filtered = _field(reloaded, cf.WATER_MOISTURE_SENSOR)
    assert filtered.config["include_entities"] == [inside]


@pytest.mark.asyncio
async def test_water_compatible_sensor_can_be_saved_without_area(hass) -> None:
    _utility, _garage, inside, _outside, _unrelated = _register_water_candidates(hass)
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_area_sensor")

    saved_menu = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            cf.WATER_MOISTURE_SENSOR: inside,
            cf.WATER_SHOW_ALL_COMPATIBLE: False,
        },
    )

    assert saved_menu["step_id"] == "water_safety"
    draft = (await _water_drafts(hass, entry))[0]
    assert set(draft.settings) == {"sensor_id"}
    assert draft.bindings[0].role == "water_safety.moisture_sensor"
    assert draft.bindings[0].reference.current_locator == inside
    assert draft.bindings[0].reference.native_id is not None
    assert draft.bindings[0].user_confirmed is True


@pytest.mark.asyncio
async def test_water_area_filters_default_candidates_and_show_all_expands_without_saving(hass) -> None:
    utility, _garage, inside, outside, unrelated = _register_water_candidates(hass)
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_area_sensor")
    area_saved = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_AREA: utility.id, cf.WATER_SHOW_ALL_COMPATIBLE: False},
    )
    draft_before = (await _water_drafts(hass, entry))[0]

    filtered_form = await _choose(hass, area_saved, "water_safety_area_sensor")
    filtered = _field(filtered_form, cf.WATER_MOISTURE_SENSOR)
    assert filtered.config["include_entities"] == [inside]
    expanded = await hass.config_entries.options.async_configure(
        filtered_form["flow_id"],
        {cf.WATER_AREA: utility.id, cf.WATER_SHOW_ALL_COMPATIBLE: True},
    )

    assert expanded["type"] is data_entry_flow.FlowResultType.FORM
    expanded_selector = _field(expanded, cf.WATER_MOISTURE_SENSOR)
    assert expanded_selector.config["include_entities"] == [inside, outside]
    assert all(entity_id not in expanded_selector.config["include_entities"] for entity_id in unrelated)
    assert (await _water_drafts(hass, entry))[0] == draft_before

    saved = await hass.config_entries.options.async_configure(
        expanded["flow_id"],
        {
            cf.WATER_AREA: utility.id,
            cf.WATER_MOISTURE_SENSOR: outside,
            cf.WATER_SHOW_ALL_COMPATIBLE: True,
        },
    )
    assert saved["step_id"] == "water_safety"
    edited = (await _water_drafts(hass, entry))[0]
    assert edited.revision == draft_before.revision + 1
    assert edited.bindings[0].reference.current_locator == outside


@pytest.mark.asyncio
async def test_water_existing_draft_can_change_and_clear_area_sensor_section(hass) -> None:
    utility, garage, inside, _outside, _unrelated = _register_water_candidates(hass)
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_area_sensor")
    first_menu = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            cf.WATER_AREA: utility.id,
            cf.WATER_MOISTURE_SENSOR: inside,
            cf.WATER_SHOW_ALL_COMPATIBLE: False,
        },
    )
    first = (await _water_drafts(hass, entry))[0]

    edit = await _choose(hass, first_menu, "water_safety_area_sensor")
    changed_menu = await hass.config_entries.options.async_configure(
        edit["flow_id"],
        {cf.WATER_AREA: garage.id, cf.WATER_SHOW_ALL_COMPATIBLE: False},
    )
    changed = (await _water_drafts(hass, entry))[0]
    assert changed.revision == first.revision + 1
    assert changed.settings["area_id"] == garage.id
    assert "sensor_id" not in changed.settings
    assert changed.bindings == ()

    clear = await _choose(hass, changed_menu, "water_safety_area_sensor")
    cleared_menu = await hass.config_entries.options.async_configure(
        clear["flow_id"],
        {cf.WATER_SHOW_ALL_COMPATIBLE: False},
    )
    cleared = (await _water_drafts(hass, entry))[0]
    assert cleared.revision == changed.revision + 1
    assert dict(cleared.settings) == {}
    assert cleared.bindings == ()
    assert "Draft incomplete" in cleared_menu["description_placeholders"]["water_safety_summary"]


@pytest.mark.asyncio
async def test_water_back_without_save_does_not_create_or_update_draft(hass) -> None:
    _register_water_candidates(hass)
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_area_sensor")

    hass.config_entries.options.async_abort(form["flow_id"])

    assert await _water_drafts(hass, entry) == ()
    assert entry.data == {}
    assert entry.options == {}


@pytest.mark.asyncio
async def test_water_notification_defaults_save_empty_incomplete_draft(hass) -> None:
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_notifications")

    assert _defaults(form) == {
        cf.WATER_NOTIFICATION_TARGETS: [],
        cf.WATER_TEST_NOTIFICATION: False,
    }
    saved = await hass.config_entries.options.async_configure(form["flow_id"], _defaults(form))

    assert saved["step_id"] == "water_safety"
    assert "Draft incomplete" in saved["description_placeholders"]["water_safety_summary"]
    draft = (await _water_drafts(hass, entry))[0]
    assert dict(draft.settings) == {"notification_target_roles": ()}
    assert draft.bindings == ()
    backend = await async_get_setup_backend(hass, entry)
    report = await backend.repository.get_latest_validation_report(draft.draft_id)
    assert report is not None
    assert report.activation_ready is False
    assert report.issues
    assert ACTIVE_REFERENCE_KEY not in entry.data


@pytest.mark.asyncio
async def test_water_notification_one_target_is_durable_and_reloadable(hass) -> None:
    (phone,) = _register_notify_targets(hass, "mobile_app_phone")
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_notifications")

    target_selector = _field(form, cf.WATER_NOTIFICATION_TARGETS)
    assert isinstance(target_selector, selector.SelectSelector)
    assert target_selector.config["multiple"] is True
    assert target_selector.config["options"] == [{"value": phone, "label": phone}]
    saved = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [phone], cf.WATER_TEST_NOTIFICATION: False},
    )

    draft = (await _water_drafts(hass, entry))[0]
    assert list(draft.settings["notification_target_roles"]) == ["water_safety.notification.primary"]
    assert len(draft.bindings) == 1
    assert draft.bindings[0].reference.current_locator == phone
    assert draft.bindings[0].user_confirmed is True
    reloaded = await _choose(hass, saved, "water_safety_notifications")
    assert _defaults(reloaded)[cf.WATER_NOTIFICATION_TARGETS] == [phone]


@pytest.mark.asyncio
async def test_water_notification_multiple_targets_can_be_edited_and_cleared(hass) -> None:
    phone, tablet, wall = _register_notify_targets(hass, "phone", "tablet", "wall_panel")
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_notifications")
    first_menu = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [phone, tablet], cf.WATER_TEST_NOTIFICATION: False},
    )
    first = (await _water_drafts(hass, entry))[0]
    first_roles = tuple(first.settings["notification_target_roles"])
    assert len(first_roles) == 2
    assert {binding.role: binding.reference.current_locator for binding in first.bindings} == dict(
        zip(first_roles, (phone, tablet), strict=True)
    )

    edit = await _choose(hass, first_menu, "water_safety_notifications")
    edited_menu = await hass.config_entries.options.async_configure(
        edit["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [tablet, wall], cf.WATER_TEST_NOTIFICATION: False},
    )
    edited = (await _water_drafts(hass, entry))[0]
    assert edited.revision == first.revision + 1
    assert edited.settings["notification_target_roles"][0] == first_roles[1]
    assert {binding.role: binding.reference.current_locator for binding in edited.bindings} == dict(
        zip(edited.settings["notification_target_roles"], (tablet, wall), strict=True)
    )

    clear = await _choose(hass, edited_menu, "water_safety_notifications")
    cleared_menu = await hass.config_entries.options.async_configure(
        clear["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [], cf.WATER_TEST_NOTIFICATION: False},
    )
    cleared = (await _water_drafts(hass, entry))[0]
    assert cleared.revision == edited.revision + 1
    assert list(cleared.settings["notification_target_roles"]) == []
    assert cleared.bindings == ()
    assert "Draft incomplete" in cleared_menu["description_placeholders"]["water_safety_summary"]


@pytest.mark.asyncio
async def test_water_notification_back_without_save_does_not_mutate_draft(hass) -> None:
    (phone,) = _register_notify_targets(hass, "phone")
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_notifications")
    saved = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [phone], cf.WATER_TEST_NOTIFICATION: False},
    )
    before = (await _water_drafts(hass, entry))[0]

    edit = await _choose(hass, saved, "water_safety_notifications")
    hass.config_entries.options.async_abort(edit["flow_id"])

    assert (await _water_drafts(hass, entry))[0] == before
    assert ACTIVE_REFERENCE_KEY not in entry.data


@pytest.mark.asyncio
async def test_water_notification_edit_of_active_creates_draft_only(hass) -> None:
    old_target, new_target = _register_notify_targets(hass, "mobile_app_phone", "family")
    entry = MockConfigEntry(domain=DOMAIN, title="Water active notification edit", data={}, options={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    old_draft, canonical, active = await _seed_configured_water(hass, entry)
    active_data = deepcopy(dict(entry.data))
    backend = await async_get_setup_backend(hass, entry)
    await backend.repository.delete_draft(old_draft.draft_id, expected_revision=old_draft.revision)

    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_notifications")
    assert _defaults(form)[cf.WATER_NOTIFICATION_TARGETS] == [old_target]
    saved = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [new_target], cf.WATER_TEST_NOTIFICATION: False},
    )

    assert saved["step_id"] == "water_safety"
    assert entry.data == active_data
    assert ActiveReference.model_validate(entry.data[ACTIVE_REFERENCE_KEY]) == active
    assert await backend.repository.get_canonical_revision(canonical.revision_id) == canonical
    draft = (await _water_drafts(hass, entry))[0]
    assert draft.base_active_revision_id == active.canonical_revision_id
    assert [
        binding.reference.current_locator
        for binding in draft.bindings
        if binding.role.startswith("water_safety.notification.")
    ] == [new_target]


@pytest.mark.asyncio
async def test_water_notification_test_reports_acceptance_without_saving(hass) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    phone, tablet = _register_notify_targets(hass, "phone", "tablet", calls=calls)
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_notifications")

    tested = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [phone, tablet], cf.WATER_TEST_NOTIFICATION: True},
    )

    assert tested["type"] is data_entry_flow.FlowResultType.FORM
    assert tested["step_id"] == "water_safety_notifications"
    result = tested["description_placeholders"]["notification_test_result"]
    assert "accepted 2" in result
    assert "did not verify delivery" in result
    assert "No configuration was saved" in result
    assert [service for service, _data in calls] == ["phone", "tablet"]
    assert all("delivery is not verified" in str(data["message"]) for _service, data in calls)
    assert await _water_drafts(hass, entry) == ()
    assert entry.data == {}
    assert entry.options == {}


@pytest.mark.asyncio
async def test_water_unavailable_notification_target_is_reported_truthfully(hass) -> None:
    (phone,) = _register_notify_targets(hass, "phone")
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_notifications")
    saved = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [phone], cf.WATER_TEST_NOTIFICATION: False},
    )
    before = (await _water_drafts(hass, entry))[0]
    hass.services.async_remove("notify", "phone")

    edit = await _choose(hass, saved, "water_safety_notifications")
    options = _field(edit, cf.WATER_NOTIFICATION_TARGETS).config["options"]
    assert options == [{"value": phone, "label": f"{phone} (currently unavailable)"}]
    rejected = await hass.config_entries.options.async_configure(
        edit["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [phone], cf.WATER_TEST_NOTIFICATION: False},
    )

    assert rejected["type"] is data_entry_flow.FlowResultType.FORM
    assert rejected["errors"] == {cf.WATER_NOTIFICATION_TARGETS: "invalid_water_notification_targets"}
    assert (await _water_drafts(hass, entry))[0] == before


@pytest.mark.asyncio
async def test_water_siren_defaults_save_no_output_in_incomplete_draft(hass) -> None:
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_sirens")

    assert _defaults(form) == {cf.WATER_SIREN_TARGETS: []}
    saved = await hass.config_entries.options.async_configure(form["flow_id"], _defaults(form))

    assert saved["step_id"] == "water_safety"
    assert "Draft incomplete" in saved["description_placeholders"]["water_safety_summary"]
    draft = (await _water_drafts(hass, entry))[0]
    assert dict(draft.settings) == {"siren_target_roles": ()}
    assert draft.bindings == ()
    assert ACTIVE_REFERENCE_KEY not in entry.data


@pytest.mark.asyncio
async def test_water_siren_discovery_accepts_only_native_siren_entities(hass) -> None:
    hall, cellar, incompatible = _register_siren_candidates(hass)
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_sirens")

    target_selector = _field(form, cf.WATER_SIREN_TARGETS)
    assert isinstance(target_selector, selector.EntitySelector)
    assert target_selector.config["domain"] == ["siren"]
    assert target_selector.config["multiple"] is True
    assert set(target_selector.config["include_entities"]) == {hall, cellar}
    assert set(incompatible).isdisjoint(target_selector.config["include_entities"])
    hass.config_entries.options.async_abort(form["flow_id"])
    assert await _water_drafts(hass, entry) == ()


@pytest.mark.asyncio
async def test_water_multiple_sirens_are_durable_reloadable_editable_and_clearable(hass) -> None:
    hall, cellar, _incompatible = _register_siren_candidates(hass)
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_sirens")
    first_menu = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_SIREN_TARGETS: [hall, cellar]},
    )
    first = (await _water_drafts(hass, entry))[0]

    roles = tuple(first.settings["siren_target_roles"])
    assert roles == tuple(sorted(roles))
    assert len(roles) == 2
    assert {binding.reference.current_locator for binding in first.bindings} == {hall, cellar}
    assert all(binding.user_confirmed for binding in first.bindings)

    reloaded = await _choose(hass, first_menu, "water_safety_sirens")
    assert set(_defaults(reloaded)[cf.WATER_SIREN_TARGETS]) == {hall, cellar}
    edited_menu = await hass.config_entries.options.async_configure(
        reloaded["flow_id"],
        {cf.WATER_SIREN_TARGETS: [cellar]},
    )
    edited = (await _water_drafts(hass, entry))[0]
    assert edited.revision == first.revision + 1
    assert [binding.reference.current_locator for binding in edited.bindings] == [cellar]

    clear = await _choose(hass, edited_menu, "water_safety_sirens")
    cleared_menu = await hass.config_entries.options.async_configure(
        clear["flow_id"],
        {cf.WATER_SIREN_TARGETS: []},
    )
    cleared = (await _water_drafts(hass, entry))[0]
    assert cleared.revision == edited.revision + 1
    assert list(cleared.settings["siren_target_roles"]) == []
    assert cleared.bindings == ()
    assert "Draft incomplete" in cleared_menu["description_placeholders"]["water_safety_summary"]


@pytest.mark.asyncio
async def test_water_removed_siren_is_visible_as_unavailable_and_cannot_be_resaved(hass) -> None:
    hall, _cellar, _incompatible = _register_siren_candidates(hass)
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_sirens")
    saved = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_SIREN_TARGETS: [hall]},
    )
    before = (await _water_drafts(hass, entry))[0]
    er.async_get(hass).async_remove(hall)

    edit = await _choose(hass, saved, "water_safety_sirens")
    assert _defaults(edit)[cf.WATER_SIREN_TARGETS] == [hall]
    assert hall in edit["description_placeholders"]["unavailable_sirens"]
    rejected = await hass.config_entries.options.async_configure(
        edit["flow_id"],
        {cf.WATER_SIREN_TARGETS: [hall]},
    )

    assert rejected["type"] is data_entry_flow.FlowResultType.FORM
    assert rejected["errors"] == {cf.WATER_SIREN_TARGETS: "invalid_water_siren_targets"}
    assert (await _water_drafts(hass, entry))[0] == before


@pytest.mark.asyncio
async def test_water_siren_edit_of_active_creates_draft_without_reloading_authority(hass) -> None:
    hall, _cellar, _incompatible = _register_siren_candidates(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="Water active siren edit", data={}, options={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    old_draft, canonical, active = await _seed_configured_water(hass, entry)
    active_data = deepcopy(dict(entry.data))
    backend = await async_get_setup_backend(hass, entry)
    await backend.repository.delete_draft(old_draft.draft_id, expected_revision=old_draft.revision)

    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_sirens")
    saved = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_SIREN_TARGETS: [hall]},
    )

    assert saved["step_id"] == "water_safety"
    assert entry.data == active_data
    assert ActiveReference.model_validate(entry.data[ACTIVE_REFERENCE_KEY]) == active
    assert await backend.repository.get_canonical_revision(canonical.revision_id) == canonical
    draft = (await _water_drafts(hass, entry))[0]
    assert draft.base_active_revision_id == active.canonical_revision_id
    siren_bindings = [binding for binding in draft.bindings if binding.role.startswith("water_safety.siren.")]
    assert [binding.reference.current_locator for binding in siren_bindings] == [hall]


@pytest.mark.asyncio
async def test_water_shutoff_defaults_save_no_output_in_incomplete_draft(hass) -> None:
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_shutoff_valves")

    assert _defaults(form) == {cf.WATER_SHUTOFF_VALVE_TARGETS: []}
    saved = await hass.config_entries.options.async_configure(form["flow_id"], _defaults(form))

    assert saved["step_id"] == "water_safety"
    draft = (await _water_drafts(hass, entry))[0]
    assert dict(draft.settings) == {"shutoff_valve_target_roles": ()}
    assert draft.bindings == ()
    assert ACTIVE_REFERENCE_KEY not in entry.data


@pytest.mark.asyncio
async def test_water_shutoff_discovery_is_conservative_and_unavailable_target_cannot_be_resaved(hass) -> None:
    main, backup, incompatible = _register_shutoff_valve_candidates(hass)
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_shutoff_valves")

    target_selector = _field(form, cf.WATER_SHUTOFF_VALVE_TARGETS)
    assert isinstance(target_selector, selector.EntitySelector)
    assert target_selector.config["domain"] == ["valve"]
    assert target_selector.config["multiple"] is True
    assert set(target_selector.config["include_entities"]) == {main, backup}
    assert set(incompatible).isdisjoint(target_selector.config["include_entities"])

    saved = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_SHUTOFF_VALVE_TARGETS: [main]},
    )
    before = (await _water_drafts(hass, entry))[0]
    er.async_get(hass).async_remove(main)
    edit = await _choose(hass, saved, "water_safety_shutoff_valves")
    assert _defaults(edit)[cf.WATER_SHUTOFF_VALVE_TARGETS] == [main]
    assert main in edit["description_placeholders"]["unavailable_shutoff_valves"]

    rejected = await hass.config_entries.options.async_configure(
        edit["flow_id"],
        {cf.WATER_SHUTOFF_VALVE_TARGETS: [main]},
    )
    assert rejected["errors"] == {cf.WATER_SHUTOFF_VALVE_TARGETS: "invalid_water_shutoff_valve_targets"}
    assert (await _water_drafts(hass, entry))[0] == before


@pytest.mark.asyncio
async def test_water_multiple_shutoff_valves_are_reloadable_and_preserve_other_water_draft_fields(hass) -> None:
    main, backup, _incompatible = _register_shutoff_valve_candidates(hass)
    entry = await _empty_entry(hass)
    original, _report = await _seed_water_draft(hass, entry, complete=True)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_shutoff_valves")

    saved = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_SHUTOFF_VALVE_TARGETS: [main, backup]},
    )
    edited = (await _water_drafts(hass, entry))[0]

    assert edited.revision == original.revision + 1
    assert {key: value for key, value in edited.settings.items() if key != "shutoff_valve_target_roles"} == dict(
        original.settings
    )
    original_bindings = {binding.role: binding for binding in original.bindings}
    assert all(binding in edited.bindings for binding in original_bindings.values())
    valve_bindings = [binding for binding in edited.bindings if binding.role.startswith("water_safety.shutoff_valve.")]
    assert {binding.reference.current_locator for binding in valve_bindings} == {main, backup}
    assert all(binding.reference.native_id and binding.user_confirmed for binding in valve_bindings)

    reloaded = await _choose(hass, saved, "water_safety_shutoff_valves")
    assert set(_defaults(reloaded)[cf.WATER_SHUTOFF_VALVE_TARGETS]) == {main, backup}
    cleared_menu = await hass.config_entries.options.async_configure(
        reloaded["flow_id"],
        {cf.WATER_SHUTOFF_VALVE_TARGETS: []},
    )
    cleared = (await _water_drafts(hass, entry))[0]
    assert cleared.revision == edited.revision + 1
    assert list(cleared.settings["shutoff_valve_target_roles"]) == []
    assert all(not binding.role.startswith("water_safety.shutoff_valve.") for binding in cleared.bindings)
    cleared_form = await _choose(hass, cleared_menu, "water_safety_shutoff_valves")
    assert _defaults(cleared_form)[cf.WATER_SHUTOFF_VALVE_TARGETS] == []
    hass.config_entries.options.async_abort(cleared_form["flow_id"])


@pytest.mark.asyncio
async def test_draft_incomplete_water_safety_menu(hass) -> None:
    entry = await _empty_entry(hass)
    await _seed_water_draft(hass, entry, complete=False)
    water = await _open_water_menu(hass, entry)
    assert "incomplete draft" in water["description_placeholders"]["water_safety_summary"]
    validation = await _choose(hass, water, "water_safety_validation")
    assert validation["type"] is data_entry_flow.FlowResultType.FORM
    assert "incomplete" in validation["description_placeholders"]["validation_summary"]


@pytest.mark.asyncio
async def test_configured_water_safety_menu(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Water configured menu", data={}, options={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    _draft, _canonical, active = await _seed_configured_water(hass, entry)
    water = await _open_water_menu(hass, entry)
    assert active.canonical_revision_id in water["description_placeholders"]["water_safety_summary"]
    area = await _choose(hass, water, "water_safety_area_sensor")
    assert _suggested(area, cf.WATER_AREA) == "utility-room"
    assert _suggested(area, cf.WATER_MOISTURE_SENSOR) == "binary_sensor.utility_moisture"


@pytest.mark.asyncio
async def test_water_active_configuration_is_unchanged_by_native_draft_edit(hass) -> None:
    areas = ar.async_get(hass)
    garage = areas.async_create("Garage")
    entry = MockConfigEntry(domain=DOMAIN, title="Water active draft edit", data={}, options={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    old_draft, canonical, active = await _seed_configured_water(hass, entry)
    active_data = deepcopy(dict(entry.data))
    backend = await async_get_setup_backend(hass, entry)
    await backend.repository.delete_draft(old_draft.draft_id, expected_revision=old_draft.revision)
    assert await _water_drafts(hass, entry) == ()

    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_area_sensor")
    saved = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_AREA: garage.id, cf.WATER_SHOW_ALL_COMPATIBLE: False},
    )

    assert saved["step_id"] == "water_safety"
    assert entry.data == active_data
    assert ActiveReference.model_validate(entry.data[ACTIVE_REFERENCE_KEY]) == active
    assert await backend.repository.get_canonical_revision(canonical.revision_id) == canonical
    edited = (await _water_drafts(hass, entry))[0]
    assert edited.revision == 1
    assert edited.settings["area_id"] == garage.id
    assert edited.base_active_revision_id == active.canonical_revision_id
    assert edited.environment_id == active.environment_id
    assert active.canonical_revision_id in saved["description_placeholders"]["water_safety_summary"]


@pytest.mark.asyncio
async def test_complete_native_water_lifecycle_activation_restart_edit_and_missing_entities(hass) -> None:
    utility, _garage, moisture, _outside, _unrelated = _register_water_candidates(hass)
    (phone,) = _register_notify_targets(hass, "lifecycle_phone")
    siren, _other_siren, _incompatible_sirens = _register_siren_candidates(hass)
    valve, _backup_valve, _incompatible_valves = _register_shutoff_valve_candidates(hass)
    hass.states.async_set(moisture, "off")
    entry = await _empty_entry(hass, title="Water lifecycle")

    water = await _open_water_menu(hass, entry)
    area = await _choose(hass, water, "water_safety_area_sensor")
    water = await hass.config_entries.options.async_configure(
        area["flow_id"],
        {
            cf.WATER_AREA: utility.id,
            cf.WATER_MOISTURE_SENSOR: moisture,
            cf.WATER_SHOW_ALL_COMPATIBLE: False,
        },
    )
    notifications = await _choose(hass, water, "water_safety_notifications")
    water = await hass.config_entries.options.async_configure(
        notifications["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [phone], cf.WATER_TEST_NOTIFICATION: False},
    )
    sirens = await _choose(hass, water, "water_safety_sirens")
    water = await hass.config_entries.options.async_configure(
        sirens["flow_id"],
        {cf.WATER_SIREN_TARGETS: [siren]},
    )
    shutoff = await _choose(hass, water, "water_safety_shutoff_valves")
    water = await hass.config_entries.options.async_configure(
        shutoff["flow_id"],
        {cf.WATER_SHUTOFF_VALVE_TARGETS: [valve]},
    )

    complete_draft = (await _water_drafts(hass, entry))[0]
    assert {binding.reference.current_locator for binding in complete_draft.bindings} == {
        moisture,
        phone,
        siren,
        valve,
    }
    assert "Draft ready" in water["description_placeholders"]["water_safety_summary"]

    activated = await _activate_water_draft(hass, water)
    assert activated["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY, activated
    await hass.async_block_till_done()
    first_active = ActiveReference.model_validate(entry.data[ACTIVE_REFERENCE_KEY])
    assert first_active.module_key == "water_safety"
    assert await _water_drafts(hass, entry) == ()
    assert entry.runtime_data.host is None
    assert entry.runtime_data.water_safety_host is not None
    assert (
        entry.runtime_data.loaded_water_safety_configuration.canonical_revision_id == first_active.canonical_revision_id
    )

    configured = await _open_water_menu(hass, entry)
    assert first_active.canonical_revision_id in configured["description_placeholders"]["water_safety_summary"]
    area = await _choose(hass, configured, "water_safety_area_sensor")
    assert _suggested(area, cf.WATER_AREA) == utility.id
    assert _suggested(area, cf.WATER_MOISTURE_SENSOR) == moisture
    hass.config_entries.options.async_abort(area["flow_id"])

    hass.data.pop("controlel_setup_backend", None)
    hass.data.pop("controlel_setup_services", None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    restarted = await _open_water_menu(hass, entry)
    assert first_active.canonical_revision_id in restarted["description_placeholders"]["water_safety_summary"]

    er.async_get(hass).async_remove(moisture)
    hass.states.async_remove(moisture)
    er.async_get(hass).async_remove(siren)
    er.async_get(hass).async_remove(valve)
    hass.services.async_remove("notify", "lifecycle_phone")

    missing_area = await _choose(hass, restarted, "water_safety_area_sensor")
    assert _suggested(missing_area, cf.WATER_MOISTURE_SENSOR) == moisture
    assert moisture in missing_area["description_placeholders"]["unavailable_area_sensor"]
    hass.config_entries.options.async_abort(missing_area["flow_id"])
    missing_notifications = await _choose(
        hass,
        await _open_water_menu(hass, entry),
        "water_safety_notifications",
    )
    assert _defaults(missing_notifications)[cf.WATER_NOTIFICATION_TARGETS] == [phone]
    assert phone in missing_notifications["description_placeholders"]["unavailable_notification_targets"]
    hass.config_entries.options.async_abort(missing_notifications["flow_id"])
    missing_sirens = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_sirens")
    assert _defaults(missing_sirens)[cf.WATER_SIREN_TARGETS] == [siren]
    assert siren in missing_sirens["description_placeholders"]["unavailable_sirens"]
    hass.config_entries.options.async_abort(missing_sirens["flow_id"])
    missing_valves = await _choose(
        hass,
        await _open_water_menu(hass, entry),
        "water_safety_shutoff_valves",
    )
    assert _defaults(missing_valves)[cf.WATER_SHUTOFF_VALVE_TARGETS] == [valve]
    assert valve in missing_valves["description_placeholders"]["unavailable_shutoff_valves"]
    hass.config_entries.options.async_abort(missing_valves["flow_id"])
    assert await _water_drafts(hass, entry) == ()

    clear_siren = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_sirens")
    edited_menu = await hass.config_entries.options.async_configure(
        clear_siren["flow_id"],
        {cf.WATER_SIREN_TARGETS: []},
    )
    assert ActiveReference.model_validate(entry.data[ACTIVE_REFERENCE_KEY]) == first_active
    edited_draft = (await _water_drafts(hass, entry))[0]
    assert list(edited_draft.settings["siren_target_roles"]) == []
    assert {binding.reference.current_locator for binding in edited_draft.bindings} == {
        moisture,
        phone,
        valve,
    }

    reactivated = await _activate_water_draft(hass, edited_menu)
    assert reactivated["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY, reactivated
    await hass.async_block_till_done()
    second_active = ActiveReference.model_validate(entry.data[ACTIVE_REFERENCE_KEY])
    assert second_active.canonical_revision_id != first_active.canonical_revision_id
    assert second_active.generation == first_active.generation + 1
    assert await _water_drafts(hass, entry) == ()
    reopened_sirens = await _choose(
        hass,
        await _open_water_menu(hass, entry),
        "water_safety_sirens",
    )
    assert _defaults(reopened_sirens)[cf.WATER_SIREN_TARGETS] == []
    hass.config_entries.options.async_abort(reopened_sirens["flow_id"])


@pytest.mark.asyncio
async def test_failed_native_water_activation_retains_draft_and_prior_authority(hass, monkeypatch) -> None:
    from custom_components.controlel.water_safety_activation import WaterSafetyActivationService

    entry = await _empty_entry(hass, title="Water activation failure")
    draft, _canonical, prior_active = await _seed_configured_water(hass, entry)
    await hass.async_block_till_done()
    assert (
        entry.runtime_data.loaded_water_safety_configuration.canonical_revision_id == prior_active.canonical_revision_id
    )

    async def fail_candidate_start(*_args, **_kwargs):
        raise RuntimeError("candidate runtime did not reach readiness")

    monkeypatch.setattr(
        WaterSafetyActivationService,
        "_async_build_and_start_host",
        fail_candidate_start,
    )

    review = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_validation")
    confirmation = await hass.config_entries.options.async_configure(review["flow_id"], {})
    failed = await hass.config_entries.options.async_configure(confirmation["flow_id"], {})

    assert failed["type"] is data_entry_flow.FlowResultType.FORM
    assert failed["step_id"] == "water_safety_activate"
    assert failed["errors"] == {"base": "water_safety_activation_failed"}
    assert ActiveReference.model_validate(entry.data[ACTIVE_REFERENCE_KEY]) == prior_active
    assert (
        entry.runtime_data.loaded_water_safety_configuration.canonical_revision_id == prior_active.canonical_revision_id
    )
    assert (await _water_drafts(hass, entry))[0] == draft
    backend = await async_get_setup_backend(hass, entry)
    assert await backend.repository.list_non_terminal_attempts() == ()


@pytest.mark.asyncio
async def test_activate_and_reactivate_water_preserves_heating_and_restart_composes_both(hass) -> None:
    entry = await _empty_entry(hass, title="Heating then Water")
    heating = await _activate_new_heating(hass, entry, platform="heating-before-water")
    water = await _activate_new_water(hass, entry)

    assert set(entry.data) == {ACTIVE_REFERENCES_KEY}
    assert active_reference_for_module(entry.data, "heating") == heating
    assert active_reference_for_module(entry.data, "water_safety") == water
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == heating.canonical_revision_id
    assert entry.runtime_data.loaded_water_safety_configuration.canonical_revision_id == water.canonical_revision_id
    assert entry.runtime_data.host is not None
    assert entry.runtime_data.water_safety_host is not None
    backend = await async_get_setup_backend(hass, entry)
    heating_drafts_before = await backend.configuration_v3.list_drafts()

    siren, _other_siren, _incompatible = _register_siren_candidates(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_sirens")
    edited_menu = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_SIREN_TARGETS: [siren]},
    )
    assert active_reference_for_module(entry.data, "heating") == heating
    assert active_reference_for_module(entry.data, "water_safety") == water
    assert await backend.configuration_v3.list_drafts() == heating_drafts_before

    completed = await _activate_water_draft(hass, edited_menu)
    assert completed["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    updated_water = active_reference_for_module(entry.data, "water_safety")
    assert updated_water is not None
    assert updated_water.generation == water.generation + 1
    assert active_reference_for_module(entry.data, "heating") == heating

    hass.data.pop("controlel_setup_backend", None)
    hass.data.pop("controlel_setup_services", None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == heating.canonical_revision_id
    assert (
        entry.runtime_data.loaded_water_safety_configuration.canonical_revision_id
        == updated_water.canonical_revision_id
    )
    assert entry.runtime_data.host is not None
    assert entry.runtime_data.water_safety_host is not None


@pytest.mark.asyncio
async def test_activate_and_reactivate_heating_preserves_water_authority(hass) -> None:
    entry = await _empty_entry(hass, title="Water then Heating")
    water = await _activate_new_water(hass, entry)
    heating = await _activate_new_heating(hass, entry, platform="heating-after-water")

    assert set(entry.data) == {ACTIVE_REFERENCES_KEY}
    assert active_reference_for_module(entry.data, "water_safety") == water
    assert active_reference_for_module(entry.data, "heating") == heating
    assert entry.runtime_data.host is not None
    assert entry.runtime_data.water_safety_host is not None

    edit = await _choose(hass, await _open_heating_menu(hass, entry), "edit_active")
    saved = await _save_draft(hass, await _through_groups(hass, edit, target=23.5))
    assert active_reference_for_module(entry.data, "water_safety") == water
    assert active_reference_for_module(entry.data, "heating") == heating
    assert await _water_drafts(hass, entry) == ()

    activate = await _prepare_activation(hass, saved)
    completed = await hass.config_entries.options.async_configure(activate["flow_id"], {})
    assert completed["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    updated_heating = active_reference_for_module(entry.data, "heating")
    assert updated_heating is not None
    assert updated_heating.generation == heating.generation + 1
    assert active_reference_for_module(entry.data, "water_safety") == water
    assert entry.runtime_data.config.target_temperature == Temperature(23.5)
    assert entry.runtime_data.water_safety_host is not None


@pytest.mark.asyncio
async def test_failed_native_heating_activation_preserves_heating_and_water_authorities(hass, monkeypatch) -> None:
    from custom_components.controlel import activation_backend

    entry = await _empty_entry(hass, title="Heating activation failure")
    water = await _activate_new_water(hass, entry)
    heating = await _activate_new_heating(hass, entry, platform="heating-failure")
    runtime_before = entry.runtime_data

    edit = await _choose(hass, await _open_heating_menu(hass, entry), "edit_active")
    zone = await _choose(hass, edit, "zone")
    values = _defaults(zone)
    values[cf.TARGET_TEMPERATURE] = 24.0
    edited = await hass.config_entries.options.async_configure(zone["flow_id"], values)
    activate = await _prepare_activation(hass, edited)

    async def fail_activation_reload(*_args, **_kwargs):
        raise RuntimeError("candidate runtime did not reach readiness")

    monkeypatch.setattr(activation_backend, "_require_reload_success", fail_activation_reload)
    failed = await hass.config_entries.options.async_configure(activate["flow_id"], {})

    assert failed["type"] is data_entry_flow.FlowResultType.FORM
    assert failed["step_id"] == "activate"
    assert failed["errors"] == {"base": "heating_activation_failed"}
    assert active_reference_for_module(entry.data, "heating") == heating
    assert active_reference_for_module(entry.data, "water_safety") == water
    assert entry.runtime_data is runtime_before
    assert entry.runtime_data.config.target_temperature == Temperature(21.0)
    assert entry.runtime_data.host is not None
    assert entry.runtime_data.water_safety_host is not None


@pytest.mark.asyncio
async def test_failed_water_activation_preserves_both_active_module_authorities(hass, monkeypatch) -> None:
    from custom_components.controlel.water_safety_activation import WaterSafetyActivationService

    entry = await _empty_entry(hass, title="Multimodule activation failure")
    heating = await _activate_new_heating(hass, entry, platform="multimodule-failure")
    water = await _activate_new_water(hass, entry)
    siren, _other_siren, _incompatible = _register_siren_candidates(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_sirens")
    edited_menu = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_SIREN_TARGETS: [siren]},
    )

    async def fail_candidate_start(*_args, **_kwargs):
        raise RuntimeError("candidate runtime did not reach readiness")

    monkeypatch.setattr(
        WaterSafetyActivationService,
        "_async_build_and_start_host",
        fail_candidate_start,
    )
    review = await _choose(hass, edited_menu, "water_safety_validation")
    confirmation = await hass.config_entries.options.async_configure(review["flow_id"], {})
    failed = await hass.config_entries.options.async_configure(confirmation["flow_id"], {})

    assert failed["type"] is data_entry_flow.FlowResultType.FORM
    assert failed["errors"] == {"base": "water_safety_activation_failed"}
    assert active_reference_for_module(entry.data, "heating") == heating
    assert active_reference_for_module(entry.data, "water_safety") == water
    assert entry.runtime_data.loaded_configuration.canonical_revision_id == heating.canonical_revision_id
    assert entry.runtime_data.loaded_water_safety_configuration.canonical_revision_id == water.canonical_revision_id
    assert entry.runtime_data.host is not None
    assert entry.runtime_data.water_safety_host is not None


@pytest.mark.asyncio
async def test_water_menu_has_no_route_to_frozen_wizard(hass) -> None:
    entry = await _empty_entry(hass)
    water = await _open_water_menu(hass, entry)
    assert water["menu_options"][0] == "water_safety_status"
    assert all("wizard" not in option for option in water["menu_options"])


@pytest.mark.asyncio
async def test_hub_back_navigation_from_placeholders(hass) -> None:
    entry = await _empty_entry(hass)
    for step_id in ("notifications_hub", "general_hub", "diagnostics_advanced"):
        hub = await _open_hub(hass, entry)
        submenu = await _choose(hass, hub, step_id)
        assert submenu["step_id"] == step_id
        assert submenu["menu_options"] == ["back_to_hub"]
        hub_again = await _choose(hass, submenu, "back_to_hub")
        assert hub_again["step_id"] == "init"


@pytest.mark.asyncio
async def test_fresh_unconfigured_entry_opens_hub_without_heating_auto_entry(hass) -> None:
    initial = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    await hass.config_entries.flow.async_configure(initial["flow_id"], {})
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hub = await _open_hub(hass, entry)
    assert hub["step_id"] == "init"
    assert "heating" in hub["menu_options"]
    assert "start_greenfield" not in hub["menu_options"]


@pytest.mark.asyncio
async def test_configured_entry_heating_route_remains_compatible(hass) -> None:
    sensor_id, source_id = _register_bindings(hass, platform="configured-hub-test")
    entry = await _empty_entry(hass)
    created = await _through_groups(hass, await _start_greenfield_draft(hass, entry, sensor_id, source_id))
    activated = await _prepare_activation(hass, await _save_draft(hass, created))
    await hass.config_entries.options.async_configure(activated["flow_id"], {})
    await hass.async_block_till_done()

    heating = await _open_heating_menu(hass, entry)
    assert "edit_active" in heating["menu_options"]
    assert "start_greenfield" not in heating["menu_options"]
