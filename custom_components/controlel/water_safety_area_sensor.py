"""Native HA authoring for the Water Safety area and moisture binding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from homeassistant.helpers import area_registry as ar

from controlel.application.configuration.water_safety_setup_adapter import (
    WATER_SAFETY_MODULE_KEY,
    WATER_SAFETY_RECOMMENDATION_POLICY_VERSION,
    WATER_SAFETY_SENSOR_ROLE,
    WATER_SAFETY_SETUP_SCHEMA_VERSION,
    WaterSafetySetupAdapter,
    WaterSafetySetupCandidate,
)
from controlel.application.setup import (
    ActiveReference,
    BindingSelection,
    CanonicalConfigurationRevision,
    DiscoverySnapshot,
    DraftRevision,
    SelectionOrigin,
)
from controlel.infrastructure.home_assistant import HomeAssistantDiscoveryAdapter, active_reference_for_module
from controlel.infrastructure.home_assistant.setup_persistence import HomeAssistantSetupRepository

from .water_safety_configure_view import async_list_module_drafts

_AREA_SETTING_KEYS = frozenset({"zone_id", "zone_name", "area_id", "area_name"})
_SENSOR_SETTING_KEYS = frozenset({"sensor_id"})
_MOISTURE_BINARY_REASON = "water_safety.candidate.moisture_binary_sensor"


@dataclass(frozen=True, slots=True)
class WaterSafetyAreaSensorEditor:
    """One read-only discovery/editor snapshot for a native HA form."""

    discovery: DiscoverySnapshot
    current_draft: DraftRevision | None
    active_reference: ActiveReference | None
    active_revision: CanonicalConfigurationRevision | None
    area_id: str | None
    moisture_entity_id: str | None
    compatible_candidates: tuple[WaterSafetySetupCandidate, ...]
    available_area_ids: frozenset[str]

    def visible_entity_ids(self, *, show_all: bool) -> tuple[str, ...]:
        candidates = self.compatible_candidates
        if self.area_id is not None and not show_all:
            candidates = tuple(item for item in candidates if item.reference.area_id == self.area_id)
        return tuple(locator for item in candidates if (locator := item.reference.current_locator) is not None)

    @property
    def unavailable_selection_labels(self) -> tuple[str, ...]:
        """Return persisted selections that current HA discovery cannot resolve."""

        labels: list[str] = []
        if self.area_id is not None and self.area_id not in self.available_area_ids:
            labels.append(f"area {self.area_id}")
        compatible_entity_ids = {
            locator for item in self.compatible_candidates if (locator := item.reference.current_locator) is not None
        }
        if self.moisture_entity_id is not None and self.moisture_entity_id not in compatible_entity_ids:
            labels.append(f"moisture sensor {self.moisture_entity_id}")
        return tuple(labels)


async def async_load_water_safety_area_sensor_editor(
    hass: Any,
    repository: HomeAssistantSetupRepository,
    entry_data: Mapping[str, Any],
    *,
    snapshot_id: str,
    captured_at: datetime,
    preferred_area_id: str | None = None,
) -> WaterSafetyAreaSensorEditor:
    """Load persisted Water intent plus semantic HA moisture candidates."""

    drafts = await async_list_module_drafts(repository, WATER_SAFETY_MODULE_KEY)
    current_draft = drafts[0] if drafts else None
    active_reference = _water_active_reference(entry_data)
    active_revision = None
    if active_reference is not None:
        revision = await repository.get_canonical_revision(active_reference.canonical_revision_id)
        if isinstance(revision, CanonicalConfigurationRevision):
            active_revision = revision

    source_settings: Mapping[str, object]
    source_bindings: tuple[BindingSelection, ...]
    if current_draft is not None:
        source_settings = current_draft.settings
        source_bindings = current_draft.bindings
    elif active_revision is not None:
        source_settings = active_revision.module_payload
        source_bindings = active_revision.bindings
    else:
        source_settings = {}
        source_bindings = ()

    area_id = preferred_area_id if preferred_area_id is not None else _optional_string(source_settings.get("area_id"))
    discovery = await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
        hass,
        snapshot_id=snapshot_id,
        captured_at=captured_at,
    )
    recommendation = next(
        item
        for item in WaterSafetySetupAdapter()
        .recommend(
            discovery,
            notification_roles=(),
            siren_roles=(),
            preferred_area_id=area_id,
        )
        .recommendations
        if item.role == WATER_SAFETY_SENSOR_ROLE
    )
    compatible = tuple(
        candidate for candidate in recommendation.candidates if _MOISTURE_BINARY_REASON in candidate.reason_codes
    )
    return WaterSafetyAreaSensorEditor(
        discovery=discovery,
        current_draft=current_draft,
        active_reference=active_reference,
        active_revision=active_revision,
        area_id=area_id,
        moisture_entity_id=_binding_locator(source_bindings, WATER_SAFETY_SENSOR_ROLE),
        compatible_candidates=compatible,
        available_area_ids=frozenset(area.id for area in ar.async_get(hass).async_list_areas()),
    )


async def async_save_water_safety_area_sensor_draft(
    hass: Any,
    repository: HomeAssistantSetupRepository,
    editor: WaterSafetyAreaSensorEditor,
    *,
    area_id: str | None,
    moisture_entity_id: str | None,
    saved_at: datetime,
    report_id: str,
) -> DraftRevision:
    """Persist one inactive Water draft revision in the shared Setup repository."""

    selected = None
    if moisture_entity_id is not None:
        selected = next(
            (
                candidate
                for candidate in editor.compatible_candidates
                if candidate.reference.current_locator == moisture_entity_id
            ),
            None,
        )
        if selected is None:
            raise ValueError("selected entity is not a compatible moisture binary sensor")

    current = editor.current_draft
    if current is not None:
        persisted = await repository.get_draft(current.draft_id)
        if persisted.revision != current.revision:
            raise ValueError("Water Safety draft changed while the form was open")
        settings = dict(current.settings)
        bindings = list(current.bindings)
    elif editor.active_revision is not None:
        settings = dict(editor.active_revision.module_payload)
        bindings = list(editor.active_revision.bindings)
    else:
        settings = {}
        bindings = []

    for key in _AREA_SETTING_KEYS | _SENSOR_SETTING_KEYS:
        settings.pop(key, None)
    bindings = [item for item in bindings if item.role != WATER_SAFETY_SENSOR_ROLE]

    if area_id is not None:
        area = ar.async_get(hass).async_get_area(area_id)
        if area is None:
            raise ValueError("selected Home Assistant area no longer exists")
        settings.update(
            {
                "zone_id": area.id,
                "zone_name": area.name,
                "area_id": area.id,
                "area_name": area.name,
            }
        )
    if selected is not None:
        sensor_native_id = selected.reference.native_id
        if sensor_native_id is None:
            raise ValueError("compatible moisture sensor has no stable native identity")
        settings["sensor_id"] = sensor_native_id
        bindings.append(
            BindingSelection(
                role=WATER_SAFETY_SENSOR_ROLE,
                reference=selected.reference,
                selection_origin=SelectionOrigin.RECOMMENDATION_ACCEPTED,
                user_confirmed=True,
                provenance={
                    "discovery_snapshot_id": editor.discovery.snapshot_id,
                    "discovery_content_fingerprint": editor.discovery.content_fingerprint,
                    "recommendation_policy_version": WATER_SAFETY_RECOMMENDATION_POLICY_VERSION,
                    "candidate_id": selected.candidate_id,
                    "confidence": selected.confidence.value,
                    "reason_codes": selected.reason_codes,
                    "source": "home_assistant_native_configure",
                },
            )
        )

    bindings_tuple = tuple(sorted(bindings, key=lambda item: item.role))
    if current is not None:
        draft = current.next_revision(
            updated_at=saved_at,
            settings=settings,
            bindings=bindings_tuple,
        )
    else:
        active = editor.active_reference
        draft = DraftRevision(
            draft_id=f"ha-water-draft-{uuid4().hex}",
            revision=1,
            environment_id=(active.environment_id if active is not None else editor.discovery.provider_instance_id),
            module_key=WATER_SAFETY_MODULE_KEY,
            module_instance_id=(active.module_instance_id if active is not None else f"water-safety-{uuid4().hex}"),
            module_schema_version=WATER_SAFETY_SETUP_SCHEMA_VERSION,
            created_at=saved_at,
            updated_at=saved_at,
            base_active_revision_id=(active.canonical_revision_id if active is not None else None),
            settings=settings,
            bindings=bindings_tuple,
            lineage={
                "created_from_discovery_snapshot_id": editor.discovery.snapshot_id,
                "recommendation_policy_version": WATER_SAFETY_RECOMMENDATION_POLICY_VERSION,
                "source": "home_assistant_native_configure",
            },
        )

    await repository.save_draft(draft)
    report = WaterSafetySetupAdapter().validate(
        draft,
        report_id=report_id,
        evaluated_at=saved_at,
        discovery_snapshot_id=editor.discovery.snapshot_id,
        resolution_generation=draft.revision,
    )
    await repository.save_validation_report(report)
    return draft


def _water_active_reference(entry_data: Mapping[str, Any]) -> ActiveReference | None:
    return active_reference_for_module(entry_data, WATER_SAFETY_MODULE_KEY)


def _binding_locator(bindings: tuple[BindingSelection, ...], role: str) -> str | None:
    binding = next((item for item in bindings if item.role == role), None)
    if binding is None:
        return None
    return binding.reference.current_locator or binding.reference.native_id


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
