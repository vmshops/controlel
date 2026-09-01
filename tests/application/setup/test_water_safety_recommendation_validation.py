"""Water Safety recommendation tests over Home Assistant discovery snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

import pytest

from controlel.application.configuration.water_safety_setup_adapter import (
    DEFAULT_NOTIFICATION_ROLE,
    SHUTOFF_VALVE_ROLE_PREFIX,
    WATER_SAFETY_SENSOR_ROLE,
    WaterSafetyRecommendationConfidence,
    WaterSafetyRecommendationSet,
    WaterSafetySetupAdapter,
)
from controlel.application.setup import DiscoverySnapshot, IdentityQuality, InMemorySetupRepository, ProviderReference
from controlel.infrastructure.home_assistant import HomeAssistantDiscoveryAdapter
from controlel.infrastructure.home_assistant.setup_discovery import (
    HA_ENDPOINT_KIND,
    HOME_ASSISTANT_PROVIDER,
)

from .conftest import NOW


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


UTILITY = AreaEntry("utility-room", "ground-floor")
ROOM_DEVICE = DeviceEntry(
    id="device-utility",
    area_id=UTILITY.id,
    identifiers=frozenset({("mqtt", "utility-device")}),
    connections=frozenset(),
    config_entries=frozenset({"entry-utility"}),
    config_entries_subentries={"entry-utility": frozenset({None})},
)
MOISTURE_BINARY = EntityEntry(
    id="entity-moisture-binary",
    entity_id="binary_sensor.utility_moisture",
    domain="binary_sensor",
    platform="mqtt",
    unique_id="utility-moisture-binary",
    previous_unique_id=None,
    config_entry_id="entry-utility",
    config_subentry_id=None,
    device_id=ROOM_DEVICE.id,
    area_id=None,
    device_class="moisture",
    original_device_class="moisture",
)
MOISTURE_SENSOR = replace(
    MOISTURE_BINARY,
    id="entity-moisture-sensor",
    entity_id="sensor.utility_moisture_level",
    domain="sensor",
    unique_id="utility-moisture-sensor",
    device_class="moisture",
    original_device_class="moisture",
)
MOISTURE_HINT = replace(
    MOISTURE_BINARY,
    id="entity-moisture-hint",
    entity_id="sensor.utility_water_leak",
    domain="sensor",
    unique_id="utility-water-hint",
    device_class=None,
    original_device_class=None,
)
SIREN = EntityEntry(
    id="entity-siren",
    entity_id="siren.hall_alert",
    domain="siren",
    platform="mqtt",
    unique_id="hall-siren",
    previous_unique_id=None,
    config_entry_id="entry-utility",
    config_subentry_id=None,
    device_id=ROOM_DEVICE.id,
    area_id=None,
)
SIREN_SWITCH = replace(
    SIREN,
    id="entity-siren-switch",
    entity_id="switch.hall_siren",
    domain="switch",
    unique_id="hall-siren-switch",
)
WATER_SHUTOFF_VALVE = replace(
    SIREN,
    id="entity-water-shutoff-valve",
    entity_id="valve.utility_water_main",
    domain="valve",
    unique_id="utility-water-main",
    device_class="water",
    original_device_class="water",
    supported_features=2,
)
WATER_VALVE_WITHOUT_CLOSE = replace(
    WATER_SHUTOFF_VALVE,
    id="entity-water-valve-without-close",
    entity_id="valve.utility_water_read_only",
    unique_id="utility-water-read-only",
    supported_features=1,
)
GAS_SHUTOFF_VALVE = replace(
    WATER_SHUTOFF_VALVE,
    id="entity-gas-shutoff-valve",
    entity_id="valve.utility_gas_main",
    unique_id="utility-gas-main",
    device_class="gas",
    original_device_class="gas",
)
DEFAULT_ENTITIES = (MOISTURE_BINARY, MOISTURE_SENSOR, MOISTURE_HINT, SIREN, SIREN_SWITCH)
NOTIFY_PRIMARY = "notify.mobile_app"
NOTIFY_BACKUP = "notify.persistent_notification"
SIREN_ROLE = "water_safety.siren.hall"
SHUTOFF_VALVE_ROLE = f"{SHUTOFF_VALVE_ROLE_PREFIX}main"


def _notify_reference(locator: str, *, provider_instance_id: str = "ha-home") -> ProviderReference:
    return ProviderReference(
        provider=HOME_ASSISTANT_PROVIDER,
        provider_instance_id=provider_instance_id,
        object_kind=HA_ENDPOINT_KIND,
        native_id=locator,
        identity_quality=IdentityQuality.STABLE,
        current_locator=locator,
        recovery_evidence={"domain": "notify"},
    )


def _snapshot(
    *,
    entities: tuple[EntityEntry, ...] = DEFAULT_ENTITIES,
    notify_endpoints: tuple[str, ...] = (NOTIFY_PRIMARY, NOTIFY_BACKUP),
    snapshot_id: str = "water-safety-discovery",
    provider_instance_id: str = "ha-home",
):
    base = HomeAssistantDiscoveryAdapter(provider_instance_id).snapshot(
        snapshot_id=snapshot_id,
        captured_at=NOW,
        floors=(FloorEntry("ground-floor"),),
        areas=(UTILITY,),
        devices=(ROOM_DEVICE,),
        entities=entities,
    )
    notify_refs = tuple(_notify_reference(item, provider_instance_id=provider_instance_id) for item in notify_endpoints)
    if not notify_refs:
        return base
    return DiscoverySnapshot(
        snapshot_id=base.snapshot_id,
        provider=base.provider,
        provider_instance_id=base.provider_instance_id,
        adapter_contract_version=base.adapter_contract_version,
        captured_at=base.captured_at,
        objects=(*base.objects, *notify_refs),
    )


def _recommendation(recommendations: WaterSafetyRecommendationSet, role: str):
    return next(item for item in recommendations.recommendations if item.role == role)


def _recommended_draft(
    snapshot,
    *,
    confirmed: bool = True,
    notification_roles: tuple[str, ...] = (DEFAULT_NOTIFICATION_ROLE,),
    siren_roles: tuple[str, ...] = (),
    shutoff_valve_roles: tuple[str, ...] = (),
    selected_roles: tuple[str, ...] | None = None,
    settings: dict[str, object] | None = None,
):
    adapter = WaterSafetySetupAdapter()
    recommendations = adapter.recommend(
        snapshot,
        notification_roles=notification_roles,
        siren_roles=siren_roles,
        shutoff_valve_roles=shutoff_valve_roles,
        preferred_area_id=UTILITY.id,
    )
    roles = selected_roles or (
        WATER_SAFETY_SENSOR_ROLE,
        *notification_roles,
        *siren_roles,
        *shutoff_valve_roles,
    )
    selected = {
        role: _recommendation(recommendations, role).recommended_candidate.candidate_id
        for role in roles
        if _recommendation(recommendations, role).recommended_candidate is not None
    }
    return adapter.create_draft_from_recommendations(
        recommendations,
        selected_candidate_ids=selected,
        explicitly_confirmed_roles=roles if confirmed else (),
        draft_id="recommended-water-safety",
        environment_id="home",
        module_instance_id="utility-water",
        created_at=NOW,
        settings=settings or {},
        preferred_area_id=UTILITY.id,
        preferred_area_name="Utility room",
        notification_roles=notification_roles,
        siren_roles=siren_roles,
        shutoff_valve_roles=shutoff_valve_roles,
    )


def test_recommendations_classify_moisture_notify_and_siren_candidates() -> None:
    recommendations = WaterSafetySetupAdapter().recommend(
        _snapshot(),
        notification_roles=(DEFAULT_NOTIFICATION_ROLE,),
        siren_roles=(SIREN_ROLE,),
        preferred_area_id=UTILITY.id,
    )

    moisture = _recommendation(recommendations, WATER_SAFETY_SENSOR_ROLE)
    notify = _recommendation(recommendations, DEFAULT_NOTIFICATION_ROLE)
    siren = _recommendation(recommendations, SIREN_ROLE)

    assert moisture.recommended_candidate is not None
    assert moisture.recommended_candidate.reference.native_id == MOISTURE_BINARY.id
    assert moisture.confidence is WaterSafetyRecommendationConfidence.HIGH
    assert "measurement.moisture" in moisture.recommended_candidate.capabilities
    assert "water_safety.candidate.moisture_binary_sensor" in moisture.reason_codes
    assert {item.reference.native_id for item in moisture.alternatives} == {
        MOISTURE_SENSOR.id,
        MOISTURE_HINT.id,
    }
    assert moisture.recommended_candidate.evidence["preferred_area_match"] is True

    assert notify.recommended_candidate is not None
    assert notify.recommended_candidate.reference.native_id == NOTIFY_PRIMARY
    assert notify.confidence is WaterSafetyRecommendationConfidence.HIGH
    assert "notification.deliver" in notify.recommended_candidate.capabilities
    assert notify.alternatives[0].reference.native_id == NOTIFY_BACKUP

    assert siren.recommended_candidate is not None
    assert siren.recommended_candidate.reference.native_id == SIREN.id
    assert siren.confidence is WaterSafetyRecommendationConfidence.HIGH
    assert siren.alternatives[0].reference.native_id == SIREN_SWITCH.id
    assert "alert.siren" in siren.recommended_candidate.capabilities


def test_moisture_sensor_and_locator_hint_confidence_levels() -> None:
    recommendations = WaterSafetySetupAdapter().recommend(
        _snapshot(entities=(MOISTURE_SENSOR, MOISTURE_HINT)),
    )
    moisture = _recommendation(recommendations, WATER_SAFETY_SENSOR_ROLE)

    assert moisture.recommended_candidate is not None
    assert moisture.recommended_candidate.reference.native_id == MOISTURE_SENSOR.id
    assert moisture.recommended_candidate.confidence is WaterSafetyRecommendationConfidence.MEDIUM
    assert moisture.alternatives[0].confidence is WaterSafetyRecommendationConfidence.LOW


def test_shutoff_recommendations_accept_only_water_valves_with_close_support() -> None:
    recommendations = WaterSafetySetupAdapter().recommend(
        _snapshot(
            entities=(
                WATER_SHUTOFF_VALVE,
                WATER_VALVE_WITHOUT_CLOSE,
                GAS_SHUTOFF_VALVE,
                SIREN,
            )
        ),
        notification_roles=(),
        shutoff_valve_roles=(SHUTOFF_VALVE_ROLE,),
    )

    shutoff = _recommendation(recommendations, SHUTOFF_VALVE_ROLE)
    assert shutoff.recommended_candidate is not None
    assert shutoff.recommended_candidate.reference.native_id == WATER_SHUTOFF_VALVE.id
    assert shutoff.recommended_candidate.capabilities == ("safety.water_shutoff.close",)
    assert shutoff.recommended_candidate.reason_codes == ("water_safety.candidate.water_valve_close",)
    assert shutoff.alternatives == ()


def test_recommendation_order_is_deterministic_and_independent_of_snapshot_input_order() -> None:
    adapter = WaterSafetySetupAdapter()
    forward = adapter.recommend(_snapshot())
    reverse = adapter.recommend(_snapshot(entities=tuple(reversed(DEFAULT_ENTITIES))))

    assert forward == reverse


def test_draft_creation_applies_defaults_and_requires_explicit_confirmation() -> None:
    snapshot = _snapshot()
    draft = _recommended_draft(snapshot, confirmed=False, siren_roles=(SIREN_ROLE,))

    assert draft.settings["behavior_contract_version"] == 1
    assert draft.settings["zone_id"] == UTILITY.id
    assert draft.settings["area_name"] == "Utility room"
    assert draft.settings["unavailable_grace_seconds"] == 60.0
    assert list(draft.settings["notification_target_roles"]) == [DEFAULT_NOTIFICATION_ROLE]
    assert list(draft.settings["shutoff_valve_target_roles"]) == []
    assert draft.settings["sensor_id"] == MOISTURE_BINARY.id
    assert all(not binding.user_confirmed for binding in draft.bindings)
    report = WaterSafetySetupAdapter().validate(
        draft,
        report_id="water-report",
        evaluated_at=NOW + timedelta(seconds=1),
    )
    confirmation_issues = [
        issue for issue in report.issues if issue.code == "water_safety.binding_confirmation_required"
    ]
    assert {issue.module_role for issue in confirmation_issues} == {
        WATER_SAFETY_SENSOR_ROLE,
        DEFAULT_NOTIFICATION_ROLE,
        SIREN_ROLE,
    }
    assert report.activation_ready is False


def test_incomplete_recommended_draft_persists_and_validates_with_blocking_issues() -> None:
    snapshot = _snapshot()
    adapter = WaterSafetySetupAdapter()
    recommendations = adapter.recommend(snapshot)
    moisture = _recommendation(recommendations, WATER_SAFETY_SENSOR_ROLE).recommended_candidate
    assert moisture is not None
    draft = adapter.create_draft_from_recommendations(
        recommendations,
        selected_candidate_ids={WATER_SAFETY_SENSOR_ROLE: moisture.candidate_id},
        explicitly_confirmed_roles=(),
        draft_id="incomplete-water-recommendation",
        environment_id="home",
        module_instance_id="utility-water",
        created_at=NOW,
        settings={},
        preferred_area_id=UTILITY.id,
    )
    repository = InMemorySetupRepository()
    repository.save_draft(draft)

    report = adapter.validate(draft, report_id="incomplete-report", evaluated_at=NOW + timedelta(seconds=1))

    assert report.activation_ready is False
    assert {issue.code for issue in report.issues} >= {
        "water_safety.required_binding_missing",
        "water_safety.binding_confirmation_required",
    }
    assert repository.get_draft(draft.draft_id) == draft


def test_cannot_confirm_a_role_that_was_not_selected() -> None:
    snapshot = _snapshot()
    adapter = WaterSafetySetupAdapter()
    recommendations = adapter.recommend(snapshot)

    with pytest.raises(ValueError, match="not explicitly selected"):
        adapter.create_draft_from_recommendations(
            recommendations,
            selected_candidate_ids={},
            explicitly_confirmed_roles=(WATER_SAFETY_SENSOR_ROLE,),
            draft_id="invalid-confirmation",
            environment_id="home",
            module_instance_id="utility-water",
            created_at=NOW,
            settings={},
        )
