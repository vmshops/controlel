"""Shared helpers for native Water Safety draft mutation semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import uuid4

from controlel.application.configuration.water_safety_setup_adapter import (
    WATER_SAFETY_MODULE_KEY,
    WATER_SAFETY_RECOMMENDATION_POLICY_VERSION,
    WATER_SAFETY_SETUP_SCHEMA_VERSION,
    WaterSafetySetupAdapter,
)
from controlel.application.setup import (
    ActiveReference,
    BindingSelection,
    CanonicalConfigurationRevision,
    DraftRevision,
)
from controlel.application.setup.json_data import canonical_json
from controlel.infrastructure.home_assistant.setup_persistence import HomeAssistantSetupRepository


def water_intent_matches_active(
    *,
    settings: Mapping[str, Any],
    bindings: Sequence[BindingSelection],
    active_revision: CanonicalConfigurationRevision | None,
) -> bool:
    """Return True when proposed draft intent equals the active canonical revision."""

    if active_revision is None:
        return False
    return _intent_fingerprint(settings, bindings) == _intent_fingerprint(
        active_revision.module_payload,
        active_revision.bindings,
    )


def water_intent_matches_draft(
    *,
    settings: Mapping[str, Any],
    bindings: Sequence[BindingSelection],
    draft: DraftRevision | None,
) -> bool:
    """Return True when proposed intent equals the current draft without revision bump."""

    if draft is None:
        return False
    return _intent_fingerprint(settings, bindings) == _intent_fingerprint(draft.settings, draft.bindings)


async def async_commit_water_draft_if_changed(
    repository: HomeAssistantSetupRepository,
    *,
    current_draft: DraftRevision | None,
    active_reference: ActiveReference | None,
    active_revision: CanonicalConfigurationRevision | None,
    settings: Mapping[str, Any],
    bindings: Sequence[BindingSelection],
    saved_at: datetime,
    report_id: str,
    discovery_snapshot_id: str,
    environment_fallback: str,
) -> DraftRevision | None:
    """Persist a Water draft only when intent actually changes.

    Returns:
    - existing draft unchanged when proposed intent matches current draft
    - None when proposed intent matches active (and any identical draft is deleted)
    - newly saved draft when intent differs
    """

    bindings_tuple = tuple(sorted(bindings, key=lambda item: item.role))
    settings_dict = dict(settings)

    if water_intent_matches_draft(settings=settings_dict, bindings=bindings_tuple, draft=current_draft):
        return current_draft

    if water_intent_matches_active(
        settings=settings_dict,
        bindings=bindings_tuple,
        active_revision=active_revision,
    ):
        if current_draft is not None:
            await repository.delete_draft(current_draft.draft_id, expected_revision=current_draft.revision)
        return None

    if current_draft is not None:
        draft = current_draft.next_revision(
            updated_at=saved_at,
            settings=settings_dict,
            bindings=bindings_tuple,
        )
    else:
        draft = DraftRevision(
            draft_id=f"ha-water-draft-{uuid4().hex}",
            revision=1,
            environment_id=(active_reference.environment_id if active_reference is not None else environment_fallback),
            module_key=WATER_SAFETY_MODULE_KEY,
            module_instance_id=(
                active_reference.module_instance_id if active_reference is not None else f"water-safety-{uuid4().hex}"
            ),
            module_schema_version=WATER_SAFETY_SETUP_SCHEMA_VERSION,
            created_at=saved_at,
            updated_at=saved_at,
            base_active_revision_id=(active_reference.canonical_revision_id if active_reference is not None else None),
            settings=settings_dict,
            bindings=bindings_tuple,
            lineage={
                "created_from_discovery_snapshot_id": discovery_snapshot_id,
                "recommendation_policy_version": WATER_SAFETY_RECOMMENDATION_POLICY_VERSION,
                "source": "home_assistant_native_configure",
            },
        )

    await repository.save_draft(draft)
    report = WaterSafetySetupAdapter().validate(
        draft,
        report_id=report_id,
        evaluated_at=saved_at,
        discovery_snapshot_id=discovery_snapshot_id,
        resolution_generation=draft.revision,
    )
    await repository.save_validation_report(report)
    return draft


def _intent_fingerprint(settings: Mapping[str, Any], bindings: Sequence[BindingSelection]) -> str:
    return canonical_json(
        {
            "settings": dict(settings),
            "bindings": [
                {
                    "role": binding.role,
                    "locator": binding.reference.current_locator or binding.reference.native_id,
                    "native_id": binding.reference.native_id,
                    "user_confirmed": binding.user_confirmed,
                }
                for binding in sorted(bindings, key=lambda item: item.role)
            ],
        }
    )
