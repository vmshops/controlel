"""Native HA authoring for Water Safety notification targets."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from controlel.application.configuration.water_safety_setup_adapter import (
    DEFAULT_NOTIFICATION_ROLE,
    MAX_NOTIFICATION_TARGETS,
    NOTIFICATION_ROLE_PREFIX,
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
from controlel.infrastructure.home_assistant import active_reference_for_module
from controlel.infrastructure.home_assistant.setup_persistence import HomeAssistantSetupRepository
from controlel.infrastructure.home_assistant.water_safety_discovery import async_snapshot_with_notify_services

from .water_safety_configure_view import async_list_module_drafts


@dataclass(frozen=True, slots=True)
class WaterSafetyNotificationsEditor:
    """One discovery/editor snapshot for the native notification form."""

    discovery: DiscoverySnapshot
    current_draft: DraftRevision | None
    active_reference: ActiveReference | None
    active_revision: CanonicalConfigurationRevision | None
    selected_target_ids: tuple[str, ...]
    available_target_ids: tuple[str, ...]
    unavailable_target_ids: tuple[str, ...]


async def async_load_water_safety_notifications_editor(
    hass: Any,
    repository: HomeAssistantSetupRepository,
    entry_data: Mapping[str, Any],
    *,
    snapshot_id: str,
    captured_at: datetime,
) -> WaterSafetyNotificationsEditor:
    """Load persisted Water intent plus currently registered HA notify services."""

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
        if binding.role.startswith(NOTIFICATION_ROLE_PREFIX)
        and (locator := binding.reference.current_locator or binding.reference.native_id) is not None
    )
    discovery = await async_snapshot_with_notify_services(
        hass,
        snapshot_id=snapshot_id,
        captured_at=captured_at,
    )
    available = tuple(
        sorted(
            locator
            for reference in discovery.objects
            if reference.object_kind == "home_assistant.endpoint"
            and (locator := reference.current_locator) is not None
            and locator.startswith("notify.")
        )
    )
    unavailable = tuple(target for target in selected if target not in available)
    return WaterSafetyNotificationsEditor(
        discovery=discovery,
        current_draft=current_draft,
        active_reference=active_reference,
        active_revision=active_revision,
        selected_target_ids=selected,
        available_target_ids=available,
        unavailable_target_ids=unavailable,
    )


async def async_save_water_safety_notifications_draft(
    repository: HomeAssistantSetupRepository,
    editor: WaterSafetyNotificationsEditor,
    *,
    target_ids: Sequence[str],
    saved_at: datetime,
    report_id: str,
) -> DraftRevision:
    """Persist notification intent as an inactive Water draft revision."""

    selected_targets = _canonical_targets(target_ids)
    unavailable = tuple(target for target in selected_targets if target not in editor.available_target_ids)
    if unavailable:
        raise ValueError(f"selected notification target is unavailable: {unavailable[0]}")

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
        if binding.role.startswith(NOTIFICATION_ROLE_PREFIX)
        and (locator := binding.reference.current_locator or binding.reference.native_id) is not None
    }
    retained_bindings = [item for item in bindings if not item.role.startswith(NOTIFICATION_ROLE_PREFIX)]
    roles = _roles_for_targets(selected_targets, existing_roles)
    candidates = _notification_candidates(editor.discovery, roles)
    candidate_by_role_target = {
        (candidate.role, candidate.reference.current_locator): candidate
        for candidate in candidates
        if candidate.reference.current_locator is not None
    }
    notification_bindings: list[BindingSelection] = []
    for target, role in zip(selected_targets, roles, strict=True):
        candidate = candidate_by_role_target.get((role, target))
        if candidate is None:
            raise ValueError(f"selected notification target is not compatible: {target}")
        notification_bindings.append(
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

    settings["notification_target_roles"] = list(roles)
    bindings_tuple = tuple(sorted((*retained_bindings, *notification_bindings), key=lambda item: item.role))
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


async def async_test_water_safety_notification(
    hass: Any,
    editor: WaterSafetyNotificationsEditor,
    *,
    target_ids: Sequence[str],
) -> tuple[str, ...]:
    """Request native HA test delivery without changing Water configuration."""

    selected_targets = _canonical_targets(target_ids)
    if not selected_targets:
        raise ValueError("select at least one notification target to test")
    unavailable = tuple(target for target in selected_targets if target not in editor.available_target_ids)
    if unavailable:
        raise ValueError(f"selected notification target is unavailable: {unavailable[0]}")
    for target in selected_targets:
        domain, service = target.split(".", 1)
        await hass.services.async_call(
            domain,
            service,
            {
                "title": "Controlel Water Safety test",
                "message": (
                    "This is a Water Safety test notification. Home Assistant accepted the service request; "
                    "notification delivery is not verified by Controlel."
                ),
            },
            blocking=True,
        )
    return selected_targets


def _notification_candidates(
    discovery: DiscoverySnapshot,
    roles: tuple[str, ...],
) -> tuple[WaterSafetySetupCandidate, ...]:
    recommendations = WaterSafetySetupAdapter().recommend(
        discovery,
        notification_roles=roles,
        siren_roles=(),
    )
    return tuple(
        candidate
        for recommendation in recommendations.recommendations
        if recommendation.role in roles
        for candidate in recommendation.candidates
    )


def _roles_for_targets(
    target_ids: tuple[str, ...],
    existing_roles: Mapping[str, str],
) -> tuple[str, ...]:
    assigned: list[str] = []
    for target in target_ids:
        existing = existing_roles.get(target)
        if existing is not None and existing not in assigned:
            assigned.append(existing)
            continue
        if DEFAULT_NOTIFICATION_ROLE not in assigned and DEFAULT_NOTIFICATION_ROLE not in existing_roles.values():
            assigned.append(DEFAULT_NOTIFICATION_ROLE)
            continue
        digest = hashlib.sha256(target.encode("utf-8")).hexdigest()[:12]
        role = f"{NOTIFICATION_ROLE_PREFIX}target_{digest}"
        if role in assigned:
            raise ValueError("notification target role collision")
        assigned.append(role)
    return tuple(assigned)


def _canonical_targets(target_ids: Sequence[str]) -> tuple[str, ...]:
    targets = tuple(str(item) for item in target_ids)
    if len(targets) > MAX_NOTIFICATION_TARGETS:
        raise ValueError("too many notification targets")
    if len(set(targets)) != len(targets):
        raise ValueError("notification targets must be unique")
    if any(not target.startswith("notify.") or target.count(".") != 1 for target in targets):
        raise ValueError("notification targets must be Home Assistant notify services")
    return targets


def _water_active_reference(entry_data: Mapping[str, Any]) -> ActiveReference | None:
    return active_reference_for_module(entry_data, WATER_SAFETY_MODULE_KEY)
