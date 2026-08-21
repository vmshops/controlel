"""Read-only Home Assistant setup discovery and exact resolution tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from controlel.application.setup import (
    IdentityQuality,
    ProviderReference,
    ReferenceResolutionStatus,
)
from controlel.infrastructure.home_assistant.setup_discovery import (
    HA_AREA_KIND,
    HA_DEVICE_KIND,
    HA_ENDPOINT_KIND,
    HA_ENTITY_KIND,
    HA_FLOOR_KIND,
    HomeAssistantDiscoveryAdapter,
    HomeAssistantEphemeralEndpoint,
    HomeAssistantReferenceResolver,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


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


FLOOR = FloorEntry("ground_floor")
AREA = AreaEntry("living_room", FLOOR.floor_id)
DEVICE = DeviceEntry(
    id="device-1",
    area_id=AREA.id,
    identifiers=frozenset({("mqtt", "thermostat-1")}),
    connections=frozenset({("mac", "00:11:22:33:44:55")}),
    config_entries=frozenset({"config-1"}),
    config_entries_subentries={"config-1": frozenset({None, "subentry-1"})},
)
ENTITY = EntityEntry(
    id="entity-registry-1",
    entity_id="sensor.living_room_temperature",
    domain="sensor",
    platform="mqtt",
    unique_id="living-temperature-1",
    previous_unique_id=None,
    config_entry_id="config-1",
    config_subentry_id="subentry-1",
    device_id=DEVICE.id,
    area_id=None,
)


def _snapshot(
    *,
    floors: tuple[FloorEntry, ...] = (FLOOR,),
    areas: tuple[AreaEntry, ...] = (AREA,),
    devices: tuple[DeviceEntry, ...] = (DEVICE,),
    entities: tuple[EntityEntry, ...] = (ENTITY,),
    endpoints: tuple[HomeAssistantEphemeralEndpoint, ...] = (),
    provider_instance_id: str = "ha-installation-1",
):
    return HomeAssistantDiscoveryAdapter(provider_instance_id).snapshot(
        snapshot_id="snapshot-1",
        captured_at=NOW,
        floors=floors,
        areas=areas,
        devices=devices,
        entities=entities,
        ephemeral_endpoints=endpoints,
    )


def _entity_reference(snapshot=None) -> ProviderReference:
    source = snapshot or _snapshot()
    return next(item for item in source.objects if item.object_kind == HA_ENTITY_KIND)


def test_exact_registry_id_resolves_and_retains_minimal_registry_evidence() -> None:
    snapshot = _snapshot()
    reference = _entity_reference(snapshot)

    result = HomeAssistantReferenceResolver().resolve(reference, snapshot)

    assert result.status is ReferenceResolutionStatus.RESOLVED
    assert result.resolved_reference == reference
    assert reference.native_id == ENTITY.id
    assert reference.current_locator == ENTITY.entity_id
    assert reference.device_registry_id == DEVICE.id
    assert reference.area_id == AREA.id
    assert reference.floor_id == FLOOR.floor_id
    assert dict(reference.recovery_evidence) == {
        "config_entry_id": "config-1",
        "config_subentry_id": "subentry-1",
        "domain": "sensor",
        "platform": "mqtt",
        "previous_unique_id": None,
        "unique_id": "living-temperature-1",
    }
    assert {item.object_kind for item in snapshot.objects} == {
        HA_FLOOR_KIND,
        HA_AREA_KIND,
        HA_DEVICE_KIND,
        HA_ENTITY_KIND,
    }


def test_entity_rename_with_same_registry_id_remains_resolved() -> None:
    original = _entity_reference()
    renamed_snapshot = _snapshot(entities=(replace(ENTITY, entity_id="sensor.lounge_temperature"),))

    result = HomeAssistantReferenceResolver().resolve(original, renamed_snapshot)

    assert result.status is ReferenceResolutionStatus.RESOLVED
    assert result.resolved_reference is not None
    assert result.resolved_reference.current_locator == "sensor.lounge_temperature"
    assert result.resolved_reference.semantic_data() == original.semantic_data()


def test_missing_registry_id_without_strong_recovery_evidence_is_missing() -> None:
    original = _entity_reference()

    result = HomeAssistantReferenceResolver().resolve(original, _snapshot(entities=()))

    assert result.status is ReferenceResolutionStatus.MISSING
    assert result.resolved_reference is None
    assert result.recovery_candidates == ()


def test_recreated_entity_is_recovery_candidate_and_never_silently_resolved() -> None:
    original = _entity_reference()
    recreated = replace(
        ENTITY,
        id="entity-registry-recreated",
        entity_id="sensor.recreated_temperature",
        previous_unique_id="older-temperature-id",
    )

    result = HomeAssistantReferenceResolver().resolve(original, _snapshot(entities=(recreated,)))

    assert result.status is ReferenceResolutionStatus.RECOVERY_CANDIDATE
    assert result.resolved_reference is None
    assert len(result.recovery_candidates) == 1
    candidate = result.recovery_candidates[0]
    assert candidate.reference.native_id == recreated.id
    assert "home_assistant.entity_unique_id_history_match" in candidate.reason_codes
    assert candidate.matched_evidence["matched_fields"] == (
        "config_entry_id",
        "config_subentry_id",
        "device_registry_id",
        "domain",
        "platform",
        "unique_id_history",
    )


def test_previous_unique_id_can_support_candidate_but_locator_alone_cannot() -> None:
    original = _entity_reference()
    historical_match = replace(
        ENTITY,
        id="entity-registry-historical",
        entity_id="sensor.recreated_temperature",
        unique_id="living-temperature-2",
        previous_unique_id=ENTITY.unique_id,
    )
    locator_only_match = replace(
        ENTITY,
        id="entity-registry-locator-only",
        unique_id="unrelated-unique-id",
        previous_unique_id=None,
    )

    historical_result = HomeAssistantReferenceResolver().resolve(
        original,
        _snapshot(entities=(historical_match,)),
    )
    locator_result = HomeAssistantReferenceResolver().resolve(
        original,
        _snapshot(entities=(locator_only_match,)),
    )

    assert historical_result.status is ReferenceResolutionStatus.RECOVERY_CANDIDATE
    assert locator_result.status is ReferenceResolutionStatus.MISSING


def test_multiple_recreated_entities_are_ambiguous() -> None:
    original = _entity_reference()
    candidates = (
        replace(ENTITY, id="entity-registry-new-b", entity_id="sensor.temperature_b"),
        replace(ENTITY, id="entity-registry-new-a", entity_id="sensor.temperature_a"),
    )

    result = HomeAssistantReferenceResolver().resolve(original, _snapshot(entities=candidates))

    assert result.status is ReferenceResolutionStatus.AMBIGUOUS
    assert result.resolved_reference is None
    assert [item.reference.native_id for item in result.recovery_candidates] == [
        "entity-registry-new-a",
        "entity-registry-new-b",
    ]


def test_area_and_floor_movement_updates_topology_without_changing_binding_identity() -> None:
    original = _entity_reference()
    upstairs = FloorEntry("upstairs")
    office = AreaEntry("office", upstairs.floor_id)
    moved_device = replace(DEVICE, area_id=office.id)
    moved_snapshot = _snapshot(
        floors=(upstairs,),
        areas=(office,),
        devices=(moved_device,),
    )

    result = HomeAssistantReferenceResolver().resolve(original, moved_snapshot)

    assert result.status is ReferenceResolutionStatus.RESOLVED
    assert result.resolved_reference is not None
    assert result.resolved_reference.area_id == office.id
    assert result.resolved_reference.floor_id == upstairs.floor_id
    assert result.resolved_reference.semantic_data() == original.semantic_data()


def test_unregistered_endpoint_is_explicitly_ephemeral() -> None:
    endpoint = HomeAssistantEphemeralEndpoint(
        current_locator="notify.mobile_app_phone",
        domain="notify",
    )
    snapshot = _snapshot(endpoints=(endpoint,))
    reference = next(item for item in snapshot.objects if item.object_kind == HA_ENDPOINT_KIND)

    result = HomeAssistantReferenceResolver().resolve(reference, snapshot)

    assert reference.identity_quality is IdentityQuality.EPHEMERAL
    assert reference.native_id is None
    assert reference.semantic_data()["current_locator"] == endpoint.current_locator
    assert result.status is ReferenceResolutionStatus.EPHEMERAL
    assert result.resolved_reference == reference


def test_snapshot_order_and_fingerprint_are_deterministic() -> None:
    other_floor = FloorEntry("basement")
    other_area = AreaEntry("utility", other_floor.floor_id)
    other_device = replace(
        DEVICE,
        id="device-2",
        area_id=other_area.id,
        identifiers=frozenset({("zha", "device-2")}),
        connections=frozenset(),
    )
    other_entity = replace(
        ENTITY,
        id="entity-registry-2",
        entity_id="binary_sensor.utility_leak",
        domain="binary_sensor",
        platform="zha",
        unique_id="utility-leak-2",
        device_id=other_device.id,
    )

    forward = _snapshot(
        floors=(FLOOR, other_floor),
        areas=(AREA, other_area),
        devices=(DEVICE, other_device),
        entities=(ENTITY, other_entity),
    )
    reverse = _snapshot(
        floors=(other_floor, FLOOR),
        areas=(other_area, AREA),
        devices=(other_device, DEVICE),
        entities=(other_entity, ENTITY),
    )

    assert forward.objects == reverse.objects
    assert forward.content_fingerprint == reverse.content_fingerprint


class ReadOnlyItems:
    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = values
        self.values_calls = 0
        self.write_attempts = 0

    def values(self) -> tuple[object, ...]:
        self.values_calls += 1
        return self._values

    def __setitem__(self, key: object, value: object) -> None:
        self.write_attempts += 1
        raise AssertionError(f"unexpected registry write: {key}={value}")


def test_hass_adapter_uses_stable_instance_id_and_registry_read_methods_only(monkeypatch) -> None:
    registries = {
        "homeassistant.helpers.floor_registry": SimpleNamespace(floors=ReadOnlyItems((FLOOR,))),
        "homeassistant.helpers.area_registry": SimpleNamespace(areas=ReadOnlyItems((AREA,))),
        "homeassistant.helpers.device_registry": SimpleNamespace(devices=ReadOnlyItems((DEVICE,))),
        "homeassistant.helpers.entity_registry": SimpleNamespace(entities=ReadOnlyItems((ENTITY,))),
    }
    hass = object()
    instance_calls: list[object] = []

    async def instance_id_getter(value: object) -> str:
        instance_calls.append(value)
        return "ha-core-instance-uuid"

    registry_calls: list[tuple[str, object]] = []

    def fake_import_module(module_name: str) -> Any:
        if module_name == "homeassistant.helpers.instance_id":
            return SimpleNamespace(async_get=instance_id_getter)
        registry = registries[module_name]

        def registry_getter(value: object) -> object:
            registry_calls.append((module_name, value))
            return registry

        return SimpleNamespace(async_get=registry_getter)

    monkeypatch.setattr(
        "controlel.infrastructure.home_assistant.setup_discovery.import_module",
        fake_import_module,
    )

    snapshot = asyncio.run(
        HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
            hass,
            snapshot_id="ha-snapshot",
            captured_at=NOW,
        )
    )

    assert snapshot.provider_instance_id == "ha-core-instance-uuid"
    assert instance_calls == [hass]
    assert registry_calls == [(module_name, hass) for module_name in registries]
    for registry in registries.values():
        items = next(iter(vars(registry).values()))
        assert items.values_calls == 1
        assert items.write_attempts == 0


def test_reference_from_other_installation_is_never_resolved() -> None:
    snapshot = _snapshot()
    reference = _entity_reference(snapshot).model_copy(update={"provider_instance_id": "other-installation"})

    result = HomeAssistantReferenceResolver().resolve(reference, snapshot)

    assert result.status is ReferenceResolutionStatus.ENVIRONMENT_MISMATCH
    assert result.resolved_reference is None
