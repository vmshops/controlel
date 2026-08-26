"""Heating recommendation and validation over real HA discovery snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

import pytest

from controlel.application.configuration.heating_setup_adapter import (
    HEAT_DELIVERY_ACTUATOR_ROLE,
    PRIMARY_TEMPERATURE_ROLE,
    REPORTED_SOURCE_STATE_ROLE,
    SOURCE_DISABLE_TARGET_ROLE,
    SOURCE_ENABLE_TARGET_ROLE,
    HeatingRecommendationSet,
    HeatingSetupAdapter,
    RecommendationConfidence,
)
from controlel.application.setup import InMemorySetupRepository, ValidationSeverity
from controlel.infrastructure.home_assistant import (
    HomeAssistantDiscoveryAdapter,
    HomeAssistantEphemeralEndpoint,
    HomeAssistantReferenceResolver,
)

from .conftest import NOW, complete_draft


@dataclass(frozen=True)
class FloorEntry:
    floor_id: str


@dataclass(frozen=True)
class AreaEntry:
    id: str
    floor_id: str | None


@dataclass(frozen=True)
class DeviceEntry:
    id: str
    area_id: str | None
    identifiers: frozenset[tuple[str, str]]
    connections: frozenset[tuple[str, str]]
    config_entries: frozenset[str]
    config_entries_subentries: dict[str, frozenset[str | None]]
    via_device_id: str | None = None


@dataclass(frozen=True)
class EntityEntry:
    id: str
    entity_id: str
    domain: str
    platform: str
    unique_id: str
    previous_unique_id: str | None
    config_entry_id: str | None
    config_subentry_id: str | None
    device_id: str | None
    area_id: str | None
    device_class: str | None = None
    original_device_class: str | None = None
    unit_of_measurement: str | None = None
    supported_features: int = 0


GROUND = FloorEntry("ground-floor")
LIVING = AreaEntry("living-room", GROUND.floor_id)
ROOM_DEVICE = DeviceEntry(
    id="device-room",
    area_id=LIVING.id,
    identifiers=frozenset({("mqtt", "room-device")}),
    connections=frozenset(),
    config_entries=frozenset({"entry-room"}),
    config_entries_subentries={"entry-room": frozenset({None})},
)
BOILER_DEVICE = DeviceEntry(
    id="device-boiler",
    area_id=LIVING.id,
    identifiers=frozenset({("mqtt", "boiler-device")}),
    connections=frozenset(),
    config_entries=frozenset({"entry-boiler"}),
    config_entries_subentries={"entry-boiler": frozenset({None})},
)
TEMPERATURE = EntityEntry(
    id="entity-temperature",
    entity_id="sensor.living_room_temperature",
    domain="sensor",
    platform="mqtt",
    unique_id="temperature-living",
    previous_unique_id=None,
    config_entry_id="entry-room",
    config_subentry_id=None,
    device_id=ROOM_DEVICE.id,
    area_id=None,
    device_class="temperature",
    original_device_class="temperature",
    unit_of_measurement="°C",
)
ALTERNATIVE_TEMPERATURE = replace(
    TEMPERATURE,
    id="entity-temperature-alternative",
    entity_id="sensor.spare_temperature",
    unique_id="temperature-spare",
    device_class=None,
    original_device_class=None,
)
SOURCE = EntityEntry(
    id="entity-source",
    entity_id="switch.boiler",
    domain="switch",
    platform="mqtt",
    unique_id="boiler-switch",
    previous_unique_id=None,
    config_entry_id="entry-boiler",
    config_subentry_id=None,
    device_id=BOILER_DEVICE.id,
    area_id=None,
)
ALTERNATIVE_SOURCE = replace(
    SOURCE,
    id="entity-source-backup",
    entity_id="switch.boiler_backup",
    unique_id="boiler-switch-backup",
)
ACTUATOR = EntityEntry(
    id="entity-actuator",
    entity_id="climate.living_room_radiator",
    domain="climate",
    platform="mqtt",
    unique_id="living-radiator",
    previous_unique_id=None,
    config_entry_id="entry-room",
    config_subentry_id=None,
    device_id=ROOM_DEVICE.id,
    area_id=None,
    supported_features=1,
)
CUSTOM_PERMISSION_TARGET = EntityEntry(
    id="entity-custom-permission",
    entity_id="input_boolean.boiler_permission",
    domain="input_boolean",
    platform="input_boolean",
    unique_id="boiler-permission",
    previous_unique_id=None,
    config_entry_id="entry-boiler",
    config_subentry_id=None,
    device_id=None,
    area_id=LIVING.id,
)
DEFAULT_ENTITIES = (
    TEMPERATURE,
    ALTERNATIVE_TEMPERATURE,
    SOURCE,
    ALTERNATIVE_SOURCE,
    ACTUATOR,
    CUSTOM_PERMISSION_TARGET,
)


def _snapshot(
    *,
    entities: tuple[EntityEntry, ...] = DEFAULT_ENTITIES,
    floors: tuple[FloorEntry, ...] = (GROUND,),
    areas: tuple[AreaEntry, ...] = (LIVING,),
    endpoints: tuple[HomeAssistantEphemeralEndpoint, ...] = (),
    snapshot_id: str = "heating-discovery",
    provider_instance_id: str = "ha-home",
):
    return HomeAssistantDiscoveryAdapter(provider_instance_id).snapshot(
        snapshot_id=snapshot_id,
        captured_at=NOW,
        floors=floors,
        areas=areas,
        devices=(ROOM_DEVICE, BOILER_DEVICE),
        entities=entities,
        ephemeral_endpoints=endpoints,
    )


def _recommendation(recommendations: HeatingRecommendationSet, role: str):
    return next(item for item in recommendations.recommendations if item.role == role)


def _recommended_draft(
    snapshot,
    *,
    confirmed: bool = True,
    selected_roles: tuple[str, ...] = (
        PRIMARY_TEMPERATURE_ROLE,
        SOURCE_ENABLE_TARGET_ROLE,
        SOURCE_DISABLE_TARGET_ROLE,
    ),
    settings=None,
):
    adapter = HeatingSetupAdapter()
    recommendations = adapter.recommend(snapshot, preferred_area_id=LIVING.id)
    selected = {
        role: _recommendation(recommendations, role).recommended_candidate.candidate_id for role in selected_roles
    }
    return adapter.create_draft_from_recommendations(
        recommendations,
        selected_candidate_ids=selected,
        explicitly_confirmed_roles=selected_roles if confirmed else (),
        draft_id="recommended-heating",
        environment_id="home",
        module_instance_id="main-heating",
        created_at=NOW,
        settings=dict(complete_draft().settings) if settings is None else settings,
    )


def _validate(draft, snapshot):
    return HeatingSetupAdapter().validate(
        draft,
        report_id="heating-discovery-validation",
        evaluated_at=NOW + timedelta(seconds=1),
        discovery_snapshot=snapshot,
        reference_resolver=HomeAssistantReferenceResolver(),
        resolution_generation=1,
    )


def test_recommendations_expose_recommended_candidate_alternatives_and_evidence() -> None:
    recommendations = HeatingSetupAdapter().recommend(_snapshot(), preferred_area_id=LIVING.id)

    temperature = _recommendation(recommendations, PRIMARY_TEMPERATURE_ROLE)
    source_enable = _recommendation(recommendations, SOURCE_ENABLE_TARGET_ROLE)
    source_reported = _recommendation(recommendations, REPORTED_SOURCE_STATE_ROLE)
    actuator = _recommendation(recommendations, HEAT_DELIVERY_ACTUATOR_ROLE)

    assert temperature.recommended_candidate is not None
    assert temperature.recommended_candidate.reference.native_id == TEMPERATURE.id
    assert temperature.confidence is RecommendationConfidence.HIGH
    assert temperature.alternatives
    assert temperature.alternatives[0].reference.native_id == ALTERNATIVE_TEMPERATURE.id
    assert "measurement.temperature" in temperature.recommended_candidate.capabilities
    assert "heating.candidate.temperature_device_class" in temperature.reason_codes
    assert temperature.recommended_candidate.evidence["preferred_area_match"] is True
    assert source_enable.recommended_candidate is not None
    assert source_enable.recommended_candidate.reference.native_id == SOURCE.id
    assert source_enable.alternatives[0].reference.native_id == ALTERNATIVE_SOURCE.id
    assert source_reported.recommended_candidate is not None
    assert source_reported.recommended_candidate.reference.native_id == SOURCE.id
    assert actuator.recommended_candidate is not None
    assert actuator.recommended_candidate.reference.native_id == ACTUATOR.id


def test_recommendation_order_is_deterministic_and_independent_of_snapshot_input_order() -> None:
    adapter = HeatingSetupAdapter()
    forward = adapter.recommend(_snapshot())
    reverse = adapter.recommend(_snapshot(entities=tuple(reversed(DEFAULT_ENTITIES))))

    assert forward == reverse


def test_candidate_ids_do_not_expire_only_because_capture_time_advanced() -> None:
    adapter = HeatingSetupAdapter()
    first = adapter.recommend(_snapshot())
    later_snapshot = HomeAssistantDiscoveryAdapter("ha-home").snapshot(
        snapshot_id="heating-discovery-later",
        captured_at=NOW + timedelta(minutes=5),
        floors=(GROUND,),
        areas=(LIVING,),
        devices=(ROOM_DEVICE, BOILER_DEVICE),
        entities=DEFAULT_ENTITIES,
    )
    later = adapter.recommend(later_snapshot)

    assert {
        item.role: tuple(candidate.candidate_id for candidate in item.candidates) for item in first.recommendations
    } == {item.role: tuple(candidate.candidate_id for candidate in item.candidates) for item in later.recommendations}


def test_recommendations_exclude_unverified_temperature_weather_and_controlel_entities() -> None:
    named_only_temperature = replace(
        TEMPERATURE,
        id="entity-named-only",
        entity_id="sensor.boiler_temperature",
        unique_id="named-only",
        device_class=None,
        original_device_class=None,
        unit_of_measurement=None,
    )
    weather = replace(
        SOURCE,
        id="entity-weather",
        entity_id="weather.home",
        domain="weather",
        unique_id="weather-home",
    )
    own_temperature = replace(
        TEMPERATURE,
        id="entity-controlel-temperature",
        entity_id="sensor.controlel_zone_temperature",
        platform="controlel",
        unique_id="controlel-zone-temperature",
    )
    own_switch = replace(
        SOURCE,
        id="entity-controlel-switch",
        entity_id="switch.controlel_heat_permission",
        platform="controlel",
        unique_id="controlel-heat-permission",
    )
    recommendations = HeatingSetupAdapter().recommend(
        _snapshot(entities=(*DEFAULT_ENTITIES, named_only_temperature, weather, own_temperature, own_switch))
    )

    temperature_ids = {
        item.reference.native_id for item in _recommendation(recommendations, PRIMARY_TEMPERATURE_ROLE).candidates
    }
    source_ids = {
        item.reference.native_id for item in _recommendation(recommendations, SOURCE_ENABLE_TARGET_ROLE).candidates
    }
    assert named_only_temperature.id not in temperature_ids
    assert own_temperature.id not in temperature_ids
    assert weather.id not in source_ids
    assert own_switch.id not in source_ids
    assert CUSTOM_PERMISSION_TARGET.id in source_ids


def test_preferred_area_ranks_a_capable_local_candidate_before_other_rooms() -> None:
    office = AreaEntry("office", GROUND.floor_id)
    local_medium = replace(
        ALTERNATIVE_TEMPERATURE,
        id="entity-local-medium",
        entity_id="sensor.living_air",
        unique_id="living-air",
    )
    other_high = replace(
        TEMPERATURE,
        id="entity-office-high",
        entity_id="sensor.office_temperature",
        unique_id="office-temperature",
        device_id=None,
        area_id=office.id,
    )
    recommendations = HeatingSetupAdapter().recommend(
        _snapshot(
            entities=(local_medium, other_high, SOURCE),
            areas=(LIVING, office),
        ),
        preferred_area_id=LIVING.id,
    )

    temperature = _recommendation(recommendations, PRIMARY_TEMPERATURE_ROLE)
    assert temperature.recommended_candidate is not None
    assert temperature.recommended_candidate.reference.native_id == local_medium.id


def test_draft_creation_requires_explicit_selection_and_does_not_auto_confirm() -> None:
    snapshot = _snapshot()
    draft = _recommended_draft(snapshot, confirmed=False)

    assert all(not binding.user_confirmed for binding in draft.bindings)
    assert all(binding.selection_origin.value == "RECOMMENDATION_ACCEPTED" for binding in draft.bindings)
    report = _validate(draft, snapshot)
    confirmation_issues = [issue for issue in report.issues if issue.code == "heating.binding_confirmation_required"]
    assert {issue.module_role for issue in confirmation_issues} == {
        PRIMARY_TEMPERATURE_ROLE,
        SOURCE_ENABLE_TARGET_ROLE,
        SOURCE_DISABLE_TARGET_ROLE,
    }
    assert report.activation_ready is False


def test_incomplete_recommended_draft_persists_and_validates_with_blocking_issues() -> None:
    snapshot = _snapshot()
    adapter = HeatingSetupAdapter()
    recommendations = adapter.recommend(snapshot)
    temperature = _recommendation(recommendations, PRIMARY_TEMPERATURE_ROLE).recommended_candidate
    assert temperature is not None
    draft = adapter.create_draft_from_recommendations(
        recommendations,
        selected_candidate_ids={PRIMARY_TEMPERATURE_ROLE: temperature.candidate_id},
        explicitly_confirmed_roles=(),
        draft_id="incomplete-recommendation",
        environment_id="home",
        module_instance_id="main-heating",
        created_at=NOW,
        settings={"zone_name": "Living room"},
    )
    repository = InMemorySetupRepository()
    repository.save_draft(draft)

    report = _validate(draft, snapshot)

    assert report.activation_ready is False
    assert {issue.code for issue in report.issues} >= {
        "heating.invalid_setting",
        "heating.required_binding_missing",
        "heating.binding_confirmation_required",
    }
    assert repository.get_draft(draft.draft_id) == draft


@pytest.mark.parametrize(
    ("temperature_entities", "expected_code"),
    (
        ((), "heating.binding_missing"),
        (
            (replace(TEMPERATURE, id="entity-temperature-recreated"),),
            "heating.binding_recovery_requires_confirmation",
        ),
        (
            (
                replace(TEMPERATURE, id="entity-temperature-recreated-a", entity_id="sensor.temperature_a"),
                replace(TEMPERATURE, id="entity-temperature-recreated-b", entity_id="sensor.temperature_b"),
            ),
            "heating.binding_ambiguous",
        ),
    ),
)
def test_missing_recreated_and_ambiguous_important_bindings_block_readiness(
    temperature_entities,
    expected_code,
) -> None:
    original_snapshot = _snapshot()
    draft = _recommended_draft(original_snapshot)
    changed_snapshot = _snapshot(
        entities=(*temperature_entities, SOURCE, ALTERNATIVE_SOURCE, ACTUATOR),
    )

    report = _validate(draft, changed_snapshot)

    assert report.activation_ready is False
    issue = next(item for item in report.issues if item.module_role == PRIMARY_TEMPERATURE_ROLE)
    assert issue.code == expected_code
    assert issue.severity is ValidationSeverity.ERROR


def test_stable_entity_rename_remains_valid() -> None:
    original_snapshot = _snapshot()
    draft = _recommended_draft(original_snapshot)
    renamed = replace(TEMPERATURE, entity_id="sensor.renamed_room_temperature")
    renamed_snapshot = _snapshot(
        entities=(renamed, ALTERNATIVE_TEMPERATURE, SOURCE, ALTERNATIVE_SOURCE, ACTUATOR),
    )

    report = _validate(draft, renamed_snapshot)

    assert report.activation_ready is True
    assert not any(issue.module_role == PRIMARY_TEMPERATURE_ROLE for issue in report.issues)


def test_exact_identity_with_unsuitable_capability_and_wrong_environment_blocks() -> None:
    original_snapshot = _snapshot()
    draft = _recommended_draft(original_snapshot)
    no_advertised_temperature = replace(
        TEMPERATURE,
        device_class=None,
        original_device_class=None,
        unit_of_measurement=None,
    )
    unsuitable_snapshot = _snapshot(
        entities=(
            no_advertised_temperature,
            ALTERNATIVE_TEMPERATURE,
            SOURCE,
            ALTERNATIVE_SOURCE,
            ACTUATOR,
        ),
    )
    other_environment = _snapshot(provider_instance_id="other-ha-installation")

    unsuitable_report = _validate(draft, unsuitable_snapshot)
    environment_report = _validate(draft, other_environment)

    assert unsuitable_report.activation_ready is False
    assert "heating.binding_capability_unsuitable" in {issue.code for issue in unsuitable_report.issues}
    assert environment_report.activation_ready is False
    assert {issue.code for issue in environment_report.issues} == {"heating.binding_environment_mismatch"}


def test_topology_change_is_warning_only_and_configuration_remains_ready() -> None:
    original_snapshot = _snapshot()
    draft = _recommended_draft(original_snapshot)
    upstairs = FloorEntry("upstairs")
    office = AreaEntry("office", upstairs.floor_id)
    moved_temperature = replace(TEMPERATURE, area_id=office.id)
    moved_snapshot = _snapshot(
        entities=(moved_temperature, ALTERNATIVE_TEMPERATURE, SOURCE, ALTERNATIVE_SOURCE, ACTUATOR),
        floors=(GROUND, upstairs),
        areas=(LIVING, office),
    )

    report = _validate(draft, moved_snapshot)

    assert report.activation_ready is True
    assert report.issues
    assert all(issue.severity is ValidationSeverity.WARNING for issue in report.issues)
    topology = next(issue for issue in report.issues if issue.code == "heating.binding_topology_changed")
    assert topology.module_role == PRIMARY_TEMPERATURE_ROLE
    assert topology.evidence["selected_area_id"] == LIVING.id
    assert topology.evidence["current_area_id"] == office.id


def test_optional_reported_state_and_heat_delivery_candidates_validate_when_enabled() -> None:
    snapshot = _snapshot()
    settings = dict(complete_draft().settings)
    settings.update(
        {
            "source_control_mode": "simple",
            "source_enable": {
                "domain": "switch",
                "service": "turn_on",
                "target_binding_role": SOURCE_ENABLE_TARGET_ROLE,
            },
            "source_disable": {
                "domain": "switch",
                "service": "turn_off",
                "target_binding_role": SOURCE_DISABLE_TARGET_ROLE,
            },
            "reported_source_state_binding_role": REPORTED_SOURCE_STATE_ROLE,
            "heat_delivery_mode": "setpoint_assist",
            "heat_delivery_actuator_binding_role": HEAT_DELIVERY_ACTUATOR_ROLE,
            "heat_delivery_ownership": "controlel_owned",
            "heat_delivery_assist_policy": "always_assist_while_heating",
        }
    )
    roles = (
        PRIMARY_TEMPERATURE_ROLE,
        SOURCE_ENABLE_TARGET_ROLE,
        SOURCE_DISABLE_TARGET_ROLE,
        REPORTED_SOURCE_STATE_ROLE,
        HEAT_DELIVERY_ACTUATOR_ROLE,
    )
    draft = _recommended_draft(snapshot, selected_roles=roles, settings=settings)

    report = _validate(draft, snapshot)

    assert report.activation_ready is True
    assert report.issues == ()


def test_ephemeral_custom_service_target_is_explicit_warning_but_simple_mode_blocks() -> None:
    endpoint = HomeAssistantEphemeralEndpoint(
        current_locator="vendor_boiler.target",
        domain="vendor_boiler",
    )
    snapshot = _snapshot(endpoints=(endpoint,))
    adapter = HeatingSetupAdapter()
    recommendations = adapter.recommend(snapshot)
    temperature = _recommendation(recommendations, PRIMARY_TEMPERATURE_ROLE).recommended_candidate
    assert temperature is not None
    selected = {PRIMARY_TEMPERATURE_ROLE: temperature.candidate_id}
    for role in (SOURCE_ENABLE_TARGET_ROLE, SOURCE_DISABLE_TARGET_ROLE):
        candidate = next(
            item
            for item in _recommendation(recommendations, role).candidates
            if item.reference.identity_quality.value == "EPHEMERAL"
        )
        selected[role] = candidate.candidate_id
    custom_draft = adapter.create_draft_from_recommendations(
        recommendations,
        selected_candidate_ids=selected,
        explicitly_confirmed_roles=selected,
        draft_id="ephemeral-custom",
        environment_id="home",
        module_instance_id="main-heating",
        created_at=NOW,
        settings=dict(complete_draft().settings),
    )
    simple_settings = dict(custom_draft.settings)
    simple_settings["source_control_mode"] = "simple"
    simple_draft = custom_draft.next_revision(
        updated_at=NOW + timedelta(seconds=1),
        settings=simple_settings,
    )

    custom_report = _validate(custom_draft, snapshot)
    simple_report = _validate(simple_draft, snapshot)

    assert custom_report.activation_ready is True
    assert {issue.code for issue in custom_report.issues} == {"heating.ephemeral_custom_service_target"}
    assert simple_report.activation_ready is False
    assert "heating.ephemeral_important_binding" in {issue.code for issue in simple_report.issues}


def test_external_service_binding_is_preserved_and_controlel_domain_still_rejected() -> None:
    snapshot = _snapshot()
    adapter = HeatingSetupAdapter()
    recommendations = adapter.recommend(snapshot)
    temperature = _recommendation(recommendations, PRIMARY_TEMPERATURE_ROLE).recommended_candidate
    enable = _recommendation(recommendations, SOURCE_ENABLE_TARGET_ROLE).recommended_candidate
    custom_disable = next(
        candidate
        for candidate in _recommendation(recommendations, SOURCE_DISABLE_TARGET_ROLE).candidates
        if candidate.reference.native_id == CUSTOM_PERMISSION_TARGET.id
    )
    assert temperature is not None and enable is not None
    selected = {
        PRIMARY_TEMPERATURE_ROLE: temperature.candidate_id,
        SOURCE_ENABLE_TARGET_ROLE: enable.candidate_id,
        SOURCE_DISABLE_TARGET_ROLE: custom_disable.candidate_id,
    }
    settings = dict(complete_draft().settings)
    settings["source_disable"] = {
        "domain": "input_boolean",
        "service": "turn_off",
        "target_binding_role": SOURCE_DISABLE_TARGET_ROLE,
    }
    draft = adapter.create_draft_from_recommendations(
        recommendations,
        selected_candidate_ids=selected,
        explicitly_confirmed_roles=selected,
        draft_id="arbitrary-service-target",
        environment_id="home",
        module_instance_id="main-heating",
        created_at=NOW,
        settings=settings,
    )
    report = _validate(draft, snapshot)
    canonical = adapter.canonicalize(
        draft,
        report,
        configuration_id="configuration",
        revision_id="revision",
        revision=1,
        provider="home_assistant",
        provider_instance_id="ha-home",
        created_at=NOW + timedelta(seconds=2),
        actor="user",
        source="setup_api",
        change_kind="CREATE",
        reason="recommended_setup",
        core_version="0.11.0",
    )
    invalid_settings = dict(draft.settings)
    invalid_settings["source_enable"] = {
        "domain": "controlel",
        "service": "enable_heating",
        "target_binding_role": SOURCE_ENABLE_TARGET_ROLE,
    }
    invalid = draft.next_revision(
        updated_at=NOW + timedelta(seconds=3),
        settings=invalid_settings,
    )

    assert canonical.module_payload["source_enable"] == {
        "domain": "vendor_boiler",
        "service": "grant_heat_permission",
        "target_binding_role": SOURCE_ENABLE_TARGET_ROLE,
    }
    assert canonical.module_payload["source_disable"] == {
        "domain": "input_boolean",
        "service": "turn_off",
        "target_binding_role": SOURCE_DISABLE_TARGET_ROLE,
    }
    assert (
        next(
            binding for binding in canonical.bindings if binding.role == SOURCE_DISABLE_TARGET_ROLE
        ).reference.current_locator
        == "input_boolean.boiler_permission"
    )
    invalid_report = _validate(invalid, snapshot)
    assert invalid_report.activation_ready is False
    assert "heating.invalid_setting" in {issue.code for issue in invalid_report.issues}
