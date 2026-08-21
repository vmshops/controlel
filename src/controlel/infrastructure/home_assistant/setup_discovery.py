"""Read-only Home Assistant registry discovery and conservative resolution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from typing import cast

from controlel.application.setup import (
    DiscoverySnapshot,
    IdentityQuality,
    ProviderReference,
    ProviderReferenceResolution,
    RecoveryCandidate,
    ReferenceResolutionStatus,
)

HOME_ASSISTANT_PROVIDER = "home_assistant"
HA_FLOOR_KIND = "home_assistant.floor"
HA_AREA_KIND = "home_assistant.area"
HA_DEVICE_KIND = "home_assistant.device"
HA_ENTITY_KIND = "home_assistant.entity"
HA_ENDPOINT_KIND = "home_assistant.endpoint"
HA_ADAPTER_CONTRACT_VERSION = "ha-registry-2026.7-v1"


@dataclass(frozen=True, slots=True)
class HomeAssistantEphemeralEndpoint:
    """Explicitly requested unregistered endpoint; live state is not scanned broadly."""

    current_locator: str
    domain: str
    device_registry_id: str | None = None
    area_id: str | None = None
    floor_id: str | None = None

    def __post_init__(self) -> None:
        if not self.current_locator or not self.domain:
            raise ValueError("ephemeral endpoint locator and domain must be non-empty")


class HomeAssistantDiscoveryAdapter:
    """Build privacy-minimized immutable snapshots from HA's in-memory registries."""

    def __init__(self, provider_instance_id: str) -> None:
        if not provider_instance_id:
            raise ValueError("Home Assistant provider instance ID must be non-empty")
        self._provider_instance_id = provider_instance_id

    @classmethod
    async def async_snapshot_from_hass(
        cls,
        hass: object,
        *,
        snapshot_id: str,
        captured_at: datetime,
        ephemeral_endpoints: Iterable[HomeAssistantEphemeralEndpoint] = (),
    ) -> DiscoverySnapshot:
        """Read current registry entries through the pinned HA 2026.7 APIs."""

        instance_module = import_module("homeassistant.helpers.instance_id")
        instance_getter = cast(
            Callable[[object], Awaitable[str]],
            getattr(instance_module, "async_get"),
        )
        provider_instance_id = await instance_getter(hass)

        floor_registry = _ha_registry("homeassistant.helpers.floor_registry", hass)
        area_registry = _ha_registry("homeassistant.helpers.area_registry", hass)
        device_registry = _ha_registry("homeassistant.helpers.device_registry", hass)
        entity_registry = _ha_registry("homeassistant.helpers.entity_registry", hass)

        return cls(provider_instance_id).snapshot(
            snapshot_id=snapshot_id,
            captured_at=captured_at,
            floors=_registry_values(floor_registry, "floors"),
            areas=_registry_values(area_registry, "areas"),
            devices=_registry_values(device_registry, "devices"),
            entities=_registry_values(entity_registry, "entities"),
            ephemeral_endpoints=ephemeral_endpoints,
        )

    def snapshot(
        self,
        *,
        snapshot_id: str,
        captured_at: datetime,
        floors: Iterable[object],
        areas: Iterable[object],
        devices: Iterable[object],
        entities: Iterable[object],
        ephemeral_endpoints: Iterable[HomeAssistantEphemeralEndpoint] = (),
    ) -> DiscoverySnapshot:
        """Copy registry evidence without calling any registry mutation API."""

        floor_entries = tuple(floors)
        area_entries = tuple(areas)
        device_entries = tuple(devices)
        entity_entries = tuple(entities)
        area_floor_ids = {_required_string(area, "id"): _optional_string(area, "floor_id") for area in area_entries}
        device_area_ids = {
            _required_string(device, "id"): _optional_string(device, "area_id") for device in device_entries
        }

        references = [self._floor_reference(floor) for floor in floor_entries]
        references.extend(self._area_reference(area) for area in area_entries)
        references.extend(self._device_reference(device, area_floor_ids=area_floor_ids) for device in device_entries)
        references.extend(
            self._entity_reference(
                entity,
                device_area_ids=device_area_ids,
                area_floor_ids=area_floor_ids,
            )
            for entity in entity_entries
        )
        references.extend(self._ephemeral_reference(endpoint) for endpoint in ephemeral_endpoints)

        return DiscoverySnapshot(
            snapshot_id=snapshot_id,
            provider=HOME_ASSISTANT_PROVIDER,
            provider_instance_id=self._provider_instance_id,
            adapter_contract_version=HA_ADAPTER_CONTRACT_VERSION,
            captured_at=captured_at,
            objects=tuple(references),
        )

    def _floor_reference(self, entry: object) -> ProviderReference:
        return self._stable_reference(
            object_kind=HA_FLOOR_KIND,
            native_id=_required_string(entry, "floor_id"),
        )

    def _area_reference(self, entry: object) -> ProviderReference:
        return self._stable_reference(
            object_kind=HA_AREA_KIND,
            native_id=_required_string(entry, "id"),
            floor_id=_optional_string(entry, "floor_id"),
        )

    def _device_reference(
        self,
        entry: object,
        *,
        area_floor_ids: Mapping[str, str | None],
    ) -> ProviderReference:
        area_id = _optional_string(entry, "area_id")
        return self._stable_reference(
            object_kind=HA_DEVICE_KIND,
            native_id=_required_string(entry, "id"),
            area_id=area_id,
            floor_id=area_floor_ids.get(area_id) if area_id is not None else None,
            recovery_evidence={
                "identifiers": _normalized_pairs(getattr(entry, "identifiers", ())),
                "connections": _normalized_pairs(getattr(entry, "connections", ())),
                "config_entry_ids": _normalized_strings(getattr(entry, "config_entries", ())),
                "config_entries_subentries": _normalized_config_subentries(
                    getattr(entry, "config_entries_subentries", {})
                ),
                "via_device_registry_id": _optional_string(entry, "via_device_id"),
            },
        )

    def _entity_reference(
        self,
        entry: object,
        *,
        device_area_ids: Mapping[str, str | None],
        area_floor_ids: Mapping[str, str | None],
    ) -> ProviderReference:
        device_id = _optional_string(entry, "device_id")
        entity_area_id = _optional_string(entry, "area_id")
        area_id = entity_area_id or (device_area_ids.get(device_id) if device_id is not None else None)
        return self._stable_reference(
            object_kind=HA_ENTITY_KIND,
            native_id=_required_string(entry, "id"),
            current_locator=_required_string(entry, "entity_id"),
            device_registry_id=device_id,
            area_id=area_id,
            floor_id=area_floor_ids.get(area_id) if area_id is not None else None,
            recovery_evidence={
                "domain": _required_string(entry, "domain"),
                "platform": _required_string(entry, "platform"),
                "unique_id": _required_string(entry, "unique_id"),
                "previous_unique_id": _optional_string(entry, "previous_unique_id"),
                "config_entry_id": _optional_string(entry, "config_entry_id"),
                "config_subentry_id": _optional_string(entry, "config_subentry_id"),
            },
        )

    def _ephemeral_reference(self, endpoint: HomeAssistantEphemeralEndpoint) -> ProviderReference:
        return ProviderReference(
            provider=HOME_ASSISTANT_PROVIDER,
            provider_instance_id=self._provider_instance_id,
            object_kind=HA_ENDPOINT_KIND,
            identity_quality=IdentityQuality.EPHEMERAL,
            current_locator=endpoint.current_locator,
            device_registry_id=endpoint.device_registry_id,
            area_id=endpoint.area_id,
            floor_id=endpoint.floor_id,
            recovery_evidence={"domain": endpoint.domain, "registered": False},
        )

    def _stable_reference(
        self,
        *,
        object_kind: str,
        native_id: str,
        current_locator: str | None = None,
        device_registry_id: str | None = None,
        area_id: str | None = None,
        floor_id: str | None = None,
        recovery_evidence: Mapping[str, object] | None = None,
    ) -> ProviderReference:
        return ProviderReference(
            provider=HOME_ASSISTANT_PROVIDER,
            provider_instance_id=self._provider_instance_id,
            object_kind=object_kind,
            native_id=native_id,
            identity_quality=IdentityQuality.STABLE,
            current_locator=current_locator,
            device_registry_id=device_registry_id,
            area_id=area_id,
            floor_id=floor_id,
            recovery_evidence=recovery_evidence or {},
        )


class HomeAssistantReferenceResolver:
    """Resolve exact registry identities and expose, but never accept, recovery candidates."""

    def resolve(
        self,
        reference: ProviderReference,
        snapshot: DiscoverySnapshot,
    ) -> ProviderReferenceResolution:
        if (
            reference.provider != HOME_ASSISTANT_PROVIDER
            or snapshot.provider != HOME_ASSISTANT_PROVIDER
            or reference.provider_instance_id != snapshot.provider_instance_id
        ):
            return ProviderReferenceResolution(
                requested_reference=reference,
                status=ReferenceResolutionStatus.ENVIRONMENT_MISMATCH,
                reason_code="home_assistant.environment_mismatch",
            )

        scoped = tuple(item for item in snapshot.objects if item.object_kind == reference.object_kind)
        if reference.identity_quality is IdentityQuality.EPHEMERAL:
            matching = next(
                (
                    item
                    for item in scoped
                    if item.identity_quality is IdentityQuality.EPHEMERAL
                    and item.current_locator == reference.current_locator
                ),
                None,
            )
            if matching is None:
                return ProviderReferenceResolution(
                    requested_reference=reference,
                    status=ReferenceResolutionStatus.MISSING,
                    reason_code="home_assistant.ephemeral_locator_missing",
                )
            return ProviderReferenceResolution(
                requested_reference=reference,
                status=ReferenceResolutionStatus.EPHEMERAL,
                reason_code="home_assistant.ephemeral_locator_present",
                resolved_reference=matching,
            )

        exact = next(
            (
                item
                for item in scoped
                if item.identity_quality is IdentityQuality.STABLE and item.native_id == reference.native_id
            ),
            None,
        )
        if exact is not None:
            return ProviderReferenceResolution(
                requested_reference=reference,
                status=ReferenceResolutionStatus.RESOLVED,
                reason_code="home_assistant.registry_id_exact",
                resolved_reference=exact,
            )

        candidates = tuple(
            candidate
            for item in scoped
            if item.identity_quality is IdentityQuality.STABLE and item.native_id != reference.native_id
            if (candidate := _recovery_candidate(reference, item)) is not None
        )
        if not candidates:
            return ProviderReferenceResolution(
                requested_reference=reference,
                status=ReferenceResolutionStatus.MISSING,
                reason_code="home_assistant.registry_id_missing",
            )
        if len(candidates) == 1:
            return ProviderReferenceResolution(
                requested_reference=reference,
                status=ReferenceResolutionStatus.RECOVERY_CANDIDATE,
                reason_code="home_assistant.recovery_candidate_requires_confirmation",
                recovery_candidates=candidates,
            )
        return ProviderReferenceResolution(
            requested_reference=reference,
            status=ReferenceResolutionStatus.AMBIGUOUS,
            reason_code="home_assistant.recovery_candidates_ambiguous",
            recovery_candidates=candidates,
        )


def _recovery_candidate(
    requested: ProviderReference,
    candidate: ProviderReference,
) -> RecoveryCandidate | None:
    if requested.object_kind == HA_ENTITY_KIND:
        return _entity_recovery_candidate(requested, candidate)
    if requested.object_kind == HA_DEVICE_KIND:
        return _device_recovery_candidate(requested, candidate)
    return None


def _entity_recovery_candidate(
    requested: ProviderReference,
    candidate: ProviderReference,
) -> RecoveryCandidate | None:
    requested_evidence = requested.recovery_evidence
    candidate_evidence = candidate.recovery_evidence
    if _evidence_string(requested_evidence, "domain") != _evidence_string(
        candidate_evidence, "domain"
    ) or _evidence_string(requested_evidence, "platform") != _evidence_string(candidate_evidence, "platform"):
        return None

    requested_ids = _entity_unique_ids(requested_evidence)
    candidate_ids = _entity_unique_ids(candidate_evidence)
    if not requested_ids or not candidate_ids or requested_ids.isdisjoint(candidate_ids):
        return None

    reasons = ["home_assistant.entity_unique_id_history_match"]
    matched_fields = ["domain", "platform", "unique_id_history"]
    for field in ("config_entry_id", "config_subentry_id"):
        requested_value = _evidence_string(requested_evidence, field)
        if requested_value is not None and requested_value == _evidence_string(candidate_evidence, field):
            reasons.append(f"home_assistant.entity_{field}_match")
            matched_fields.append(field)
    if requested.device_registry_id is not None and requested.device_registry_id == candidate.device_registry_id:
        reasons.append("home_assistant.entity_device_registry_id_match")
        matched_fields.append("device_registry_id")
    return RecoveryCandidate(
        reference=candidate,
        reason_codes=tuple(reasons),
        matched_evidence={"matched_fields": sorted(matched_fields)},
    )


def _device_recovery_candidate(
    requested: ProviderReference,
    candidate: ProviderReference,
) -> RecoveryCandidate | None:
    requested_identifiers = _evidence_pairs(requested.recovery_evidence, "identifiers")
    candidate_identifiers = _evidence_pairs(candidate.recovery_evidence, "identifiers")
    requested_connections = _evidence_pairs(requested.recovery_evidence, "connections")
    candidate_connections = _evidence_pairs(candidate.recovery_evidence, "connections")
    reasons: list[str] = []
    matched_fields: list[str] = []
    if requested_identifiers & candidate_identifiers:
        reasons.append("home_assistant.device_identifier_match")
        matched_fields.append("identifiers")
    if requested_connections & candidate_connections:
        reasons.append("home_assistant.device_connection_match")
        matched_fields.append("connections")
    if not reasons:
        return None
    return RecoveryCandidate(
        reference=candidate,
        reason_codes=tuple(reasons),
        matched_evidence={"matched_fields": sorted(matched_fields)},
    )


def _ha_registry(module_name: str, hass: object) -> object:
    module = import_module(module_name)
    getter = cast(Callable[[object], object], getattr(module, "async_get"))
    return getter(hass)


def _registry_values(registry: object, attribute: str) -> tuple[object, ...]:
    entries = getattr(registry, attribute)
    values = cast(Callable[[], Iterable[object]], getattr(entries, "values"))
    return tuple(values())


def _required_string(value: object, attribute: str) -> str:
    result = getattr(value, attribute, None)
    if not isinstance(result, str) or not result:
        raise ValueError(f"Home Assistant registry field {attribute} must be a non-empty string")
    return result


def _optional_string(value: object, attribute: str) -> str | None:
    result = getattr(value, attribute, None)
    if result is None:
        return None
    if not isinstance(result, str) or not result:
        raise ValueError(f"Home Assistant registry field {attribute} must be null or a non-empty string")
    return result


def _normalized_strings(value: object) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, str | bytes):
        raise TypeError("Home Assistant registry string collection must be iterable")
    values = tuple(value)
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError("Home Assistant registry string collections require non-empty strings")
    return sorted(cast(tuple[str, ...], values))


def _normalized_pairs(value: object) -> list[list[str]]:
    if not isinstance(value, Iterable) or isinstance(value, str | bytes):
        raise TypeError("Home Assistant registry pair collection must be iterable")
    result: list[tuple[str, str]] = []
    for item in value:
        if (
            not isinstance(item, tuple | list)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0]
            or not isinstance(item[1], str)
            or not item[1]
        ):
            raise ValueError("Home Assistant registry identifiers/connections require string pairs")
        result.append((item[0], item[1]))
    return [[key, item_value] for key, item_value in sorted(set(result))]


def _normalized_config_subentries(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Mapping):
        raise TypeError("Home Assistant config-entry/subentry associations must be a mapping")
    result: list[dict[str, object]] = []
    for config_entry_id, subentry_ids in value.items():
        if not isinstance(config_entry_id, str) or not config_entry_id:
            raise ValueError("Home Assistant config-entry IDs must be non-empty strings")
        if not isinstance(subentry_ids, Iterable) or isinstance(subentry_ids, str | bytes):
            raise TypeError("Home Assistant config subentry IDs must be iterable")
        normalized_subentries: list[str | None] = []
        for subentry_id in subentry_ids:
            if subentry_id is not None and (not isinstance(subentry_id, str) or not subentry_id):
                raise ValueError("Home Assistant config-subentry IDs must be null or non-empty strings")
            normalized_subentries.append(subentry_id)
        result.append(
            {
                "config_entry_id": config_entry_id,
                "config_subentry_ids": sorted(
                    normalized_subentries,
                    key=lambda item: (item is not None, item or ""),
                ),
            }
        )
    return sorted(result, key=lambda item: cast(str, item["config_entry_id"]))


def _evidence_string(evidence: Mapping[str, object], key: str) -> str | None:
    value = evidence.get(key)
    return value if isinstance(value, str) and value else None


def _entity_unique_ids(evidence: Mapping[str, object]) -> set[str]:
    return {
        value for key in ("unique_id", "previous_unique_id") if (value := _evidence_string(evidence, key)) is not None
    }


def _evidence_pairs(evidence: Mapping[str, object], key: str) -> set[tuple[str, str]]:
    value = evidence.get(key, ())
    if not isinstance(value, Iterable) or isinstance(value, str | bytes):
        return set()
    result: set[tuple[str, str]] = set()
    for item in value:
        if isinstance(item, tuple | list) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], str):
            result.add((item[0], item[1]))
    return result
