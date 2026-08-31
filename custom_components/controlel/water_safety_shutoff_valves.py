"""Native Home Assistant authoring for Water Safety shutoff valve outputs."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from controlel.application.configuration.water_safety_setup_adapter import (
    MAX_SHUTOFF_VALVE_TARGETS,
    SHUTOFF_VALVE_ROLE_PREFIX,
    WATER_SAFETY_MODULE_KEY,
    WATER_SAFETY_RECOMMENDATION_POLICY_VERSION,
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
from controlel.infrastructure.home_assistant import ACTIVE_REFERENCE_KEY, HomeAssistantDiscoveryAdapter
from controlel.infrastructure.home_assistant.setup_persistence import HomeAssistantSetupRepository

from .water_safety_configure_view import async_list_module_drafts

DEFAULT_SHUTOFF_VALVE_ROLE = f"{SHUTOFF_VALVE_ROLE_PREFIX}primary"
_WATER_VALVE_CLOSE_REASON = "water_safety.candidate.water_valve_close"


@dataclass(frozen=True, slots=True)
class WaterSafetyShutoffValvesEditor:
    """One discovery/editor snapshot for the native shutoff valve form."""

    discovery: DiscoverySnapshot
    current_draft: DraftRevision | None
    active_reference: ActiveReference | None
    active_revision: CanonicalConfigurationRevision | None
    selected_target_ids: tuple[str, ...]
    compatible_target_ids: tuple[str, ...]
    unavailable_target_ids: tuple[str, ...]


async def async_load_water_safety_shutoff_valves_editor(
    hass: Any,
    repository: HomeAssistantSetupRepository,
    entry_data: Mapping[str, Any],
    *,
    snapshot_id: str,
    captured_at: datetime,
) -> WaterSafetyShutoffValvesEditor:
    """Load persisted Water intent plus conservative HA water-valve candidates."""

    drafts = await async_list_module_drafts(repository, WATER_SAFETY_MODULE_KEY)
    current_draft = drafts[0] if drafts else None
    active_reference = _water_active_reference(entry_data)
    active_revision = None
    if active_reference is not None:
        revision = await repository.get_canonical_revision(active_reference.canonical_revision_id)
        if isinstance(revision, CanonicalConfigurationRevision):
            active_revision = revision

    source_bindings = (
        current_draft.bindings
        if current_draft is not None
        else active_revision.bindings
        if active_revision is not None
        else ()
    )
    selected = tuple(
        locator
        for binding in sorted(source_bindings, key=lambda item: item.role)
        if binding.role.startswith(SHUTOFF_VALVE_ROLE_PREFIX)
        and (locator := binding.reference.current_locator or binding.reference.native_id) is not None
    )
    discovery = await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
        hass,
        snapshot_id=snapshot_id,
        captured_at=captured_at,
    )
    candidates = _shutoff_valve_candidates(discovery, (DEFAULT_SHUTOFF_VALVE_ROLE,))
    compatible = tuple(
        sorted(
            locator
            for candidate in candidates
            if _WATER_VALVE_CLOSE_REASON in candidate.reason_codes
            and (locator := candidate.reference.current_locator) is not None
        )
    )
    unavailable = tuple(target for target in selected if target not in compatible)
    return WaterSafetyShutoffValvesEditor(
        discovery=discovery,
        current_draft=current_draft,
        active_reference=active_reference,
        active_revision=active_revision,
        selected_target_ids=selected,
        compatible_target_ids=compatible,
        unavailable_target_ids=unavailable,
    )


async def async_save_water_safety_shutoff_valves_draft(
    repository: HomeAssistantSetupRepository,
    editor: WaterSafetyShutoffValvesEditor,
    *,
    target_ids: Sequence[str],
    saved_at: datetime,
    report_id: str,
) -> DraftRevision:
    """Persist automatic shutoff intent as an inactive Water draft revision."""

    selected_targets = _canonical_targets(target_ids)
    incompatible = tuple(target for target in selected_targets if target not in editor.compatible_target_ids)
    if incompatible:
        raise ValueError(f"selected shutoff valve is incompatible or unavailable: {incompatible[0]}")

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

    existing_roles = {
        locator: binding.role
        for binding in bindings
        if binding.role.startswith(SHUTOFF_VALVE_ROLE_PREFIX)
        and (locator := binding.reference.current_locator or binding.reference.native_id) is not None
    }
    retained_bindings = [item for item in bindings if not item.role.startswith(SHUTOFF_VALVE_ROLE_PREFIX)]
    assignments = _role_assignments(selected_targets, existing_roles)
    roles = tuple(role for role, _target in assignments)
    candidates = _shutoff_valve_candidates(editor.discovery, roles)
    candidate_by_role_target = {
        (candidate.role, candidate.reference.current_locator): candidate
        for candidate in candidates
        if _WATER_VALVE_CLOSE_REASON in candidate.reason_codes and candidate.reference.current_locator is not None
    }
    valve_bindings: list[BindingSelection] = []
    for role, target in assignments:
        candidate = candidate_by_role_target.get((role, target))
        if candidate is None:
            raise ValueError(f"selected shutoff valve is not compatible: {target}")
        valve_bindings.append(
            BindingSelection(
                role=role,
                reference=candidate.reference,
                selection_origin=SelectionOrigin.RECOMMENDATION_ACCEPTED,
                user_confirmed=True,
                provenance={
                    "discovery_snapshot_id": editor.discovery.snapshot_id,
                    "discovery_content_fingerprint": editor.discovery.content_fingerprint,
                    "recommendation_policy_version": WATER_SAFETY_RECOMMENDATION_POLICY_VERSION,
                    "candidate_id": candidate.candidate_id,
                    "confidence": candidate.confidence.value,
                    "reason_codes": candidate.reason_codes,
                    "source": "home_assistant_native_configure",
                },
            )
        )

    settings["shutoff_valve_target_roles"] = list(roles)
    bindings_tuple = tuple(sorted((*retained_bindings, *valve_bindings), key=lambda item: item.role))
    if current is not None:
        draft = current.next_revision(updated_at=saved_at, settings=settings, bindings=bindings_tuple)
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


def _shutoff_valve_candidates(
    discovery: DiscoverySnapshot,
    roles: tuple[str, ...],
) -> tuple[WaterSafetySetupCandidate, ...]:
    recommendations = WaterSafetySetupAdapter().recommend(
        discovery,
        notification_roles=(),
        siren_roles=(),
        shutoff_valve_roles=roles,
    )
    return tuple(
        candidate
        for recommendation in recommendations.recommendations
        if recommendation.role in roles
        for candidate in recommendation.candidates
    )


def _role_assignments(
    target_ids: tuple[str, ...],
    existing_roles: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    assigned_roles: set[str] = set()
    assignments: list[tuple[str, str]] = []
    for target in target_ids:
        role = existing_roles.get(target)
        if role is None or role in assigned_roles:
            if (
                DEFAULT_SHUTOFF_VALVE_ROLE not in assigned_roles
                and DEFAULT_SHUTOFF_VALVE_ROLE not in existing_roles.values()
            ):
                role = DEFAULT_SHUTOFF_VALVE_ROLE
            else:
                digest = hashlib.sha256(target.encode("utf-8")).hexdigest()[:12]
                role = f"{SHUTOFF_VALVE_ROLE_PREFIX}target_{digest}"
        if role in assigned_roles:
            raise ValueError("shutoff valve target role collision")
        assigned_roles.add(role)
        assignments.append((role, target))
    return tuple(sorted(assignments))


def _canonical_targets(target_ids: Sequence[str]) -> tuple[str, ...]:
    targets = tuple(str(item) for item in target_ids)
    if len(targets) > MAX_SHUTOFF_VALVE_TARGETS:
        raise ValueError("too many shutoff valve targets")
    if len(set(targets)) != len(targets):
        raise ValueError("shutoff valve targets must be unique")
    if any(not target.startswith("valve.") or target.count(".") != 1 for target in targets):
        raise ValueError("shutoff valve targets must be Home Assistant valve entities")
    return targets


def _water_active_reference(entry_data: Mapping[str, Any]) -> ActiveReference | None:
    raw = entry_data.get(ACTIVE_REFERENCE_KEY)
    if not isinstance(raw, Mapping):
        return None
    active = ActiveReference.model_validate(raw)
    return active if active.module_key == WATER_SAFETY_MODULE_KEY else None
