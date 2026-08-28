"""Canonical configuration v3 edit lifecycle contracts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.configuration import (
    CanonicalConfigurationDraftV3,
    CanonicalConfigurationLifecycleV3,
    CanonicalReferenceHealthV3,
    ConfigurationScopesV3,
    canonical_reference_bindings_v3,
    migrate_heating_v2_revision_to_v3,
)
from controlel.application.configuration.heating_setup_adapter import HeatingSetupAdapter
from controlel.application.setup import (
    ActiveReference,
    ReferenceResolutionStatus,
    SetupConflictError,
    SetupNotFoundError,
)
from tests.application.setup.conftest import complete_draft

NOW = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)


class Repository:
    def __init__(self, revision=None) -> None:
        self.revisions = {} if revision is None else {revision.revision_id: revision}
        self.active = (
            None
            if revision is None
            else ActiveReference(
                environment_id=revision.environment_id,
                module_key=revision.module_key,
                module_instance_id=revision.module_instance_id,
                canonical_revision_id=revision.revision_id,
                semantic_configuration_fingerprint=revision.semantic_configuration_fingerprint,
                generation=4,
                committing_operation_id="activate-v3-base",
            )
        )
        self.drafts = {}
        self.validations = {}

    async def get_active_reference(self, scope):
        return self.active if self.active is not None and self.active.scope_key == scope else None

    async def get_canonical_revision_v3(self, revision_id):
        try:
            return self.revisions[revision_id]
        except KeyError as error:
            raise SetupNotFoundError(revision_id) from error

    async def get_canonical_revision(self, revision_id):
        try:
            return self.revisions[revision_id]
        except KeyError as error:
            raise SetupNotFoundError(revision_id) from error

    async def add_canonical_revision_v3(self, revision):
        current = self.revisions.get(revision.revision_id)
        if current is not None and current != revision:
            raise SetupConflictError("revision ID is immutable")
        self.revisions[revision.revision_id] = revision

    async def save_canonical_draft_v3(self, draft):
        revisions = self.drafts.setdefault(draft.draft_id, {})
        if draft.revision != max(revisions, default=0) + 1:
            raise SetupConflictError("stale draft")
        revisions[draft.revision] = draft

    async def get_canonical_draft_v3(self, draft_id):
        revisions = self.drafts.get(draft_id)
        if not revisions:
            raise SetupNotFoundError(draft_id)
        return revisions[max(revisions)]

    async def list_canonical_drafts_v3(self):
        return tuple(
            sorted(
                (revisions[max(revisions)] for revisions in self.drafts.values()),
                key=lambda item: (item.updated_at, item.draft_id),
            )
        )

    async def delete_canonical_draft_v3(self, draft_id, *, expected_revision):
        draft = await self.get_canonical_draft_v3(draft_id)
        if draft.revision != expected_revision:
            raise SetupConflictError("stale draft deletion")
        del self.drafts[draft_id]
        self.validations = {
            report_id: report for report_id, report in self.validations.items() if report.draft_id != draft_id
        }

    async def save_canonical_validation_v3(self, report):
        self.validations[report.report_id] = report

    async def get_canonical_validation_v3(self, report_id):
        try:
            return self.validations[report_id]
        except KeyError as error:
            raise SetupNotFoundError(report_id) from error


def _resolved_reference_health(draft):
    return tuple(
        CanonicalReferenceHealthV3(
            canonical_path=binding.canonical_path,
            activation_required=binding.activation_required,
            reference=binding.reference,
            status=ReferenceResolutionStatus.RESOLVED,
            reason_code="test.resolved",
            resolved_reference=binding.reference,
        )
        for binding in canonical_reference_bindings_v3(draft)
    )


@pytest.fixture
def active_v3():
    draft = complete_draft()
    adapter = HeatingSetupAdapter()
    report = adapter.validate(draft, report_id="v2-ready", evaluated_at=NOW)
    canonical_revision = adapter.canonicalize(
        draft,
        report,
        configuration_id="configuration-1",
        revision_id="canonical-v2-base",
        revision=1,
        provider="home_assistant",
        provider_instance_id="ha-home",
        created_at=NOW,
        actor="test:admin",
        source="test",
        change_kind="CREATE",
        reason="fixture",
        core_version="0.16.0",
    )
    return migrate_heating_v2_revision_to_v3(
        canonical_revision,
        revision_id="canonical-v3-active",
        created_at=NOW,
    )


async def _active_read_and_clone_preserve_exact_semantic_configuration(active_v3) -> None:
    repository = Repository(active_v3)
    lifecycle = CanonicalConfigurationLifecycleV3(repository)

    active = await lifecycle.read_active(active_v3.scope_key)
    draft = await lifecycle.clone_active_to_draft(
        active_v3.scope_key,
        draft_id="edit-active",
        created_at=NOW + timedelta(minutes=1),
        expected_active_generation=4,
    )

    assert active.active_reference.canonical_revision_id == active_v3.revision_id
    assert active.active_reference.generation == 4
    assert active.canonical_revision == active_v3
    assert active.configuration_scopes.heating == active_v3.heating
    assert draft.base_active_revision_id == active_v3.revision_id
    assert draft.base_active_generation == 4
    assert draft.content_fingerprint == active_v3.semantic_configuration_fingerprint


async def _one_field_edit_and_unchanged_round_trip_are_semantically_exact(active_v3) -> None:
    repository = Repository(active_v3)
    lifecycle = CanonicalConfigurationLifecycleV3(repository)
    draft = await lifecycle.clone_active_to_draft(
        active_v3.scope_key,
        draft_id="one-field",
        created_at=NOW + timedelta(minutes=1),
        expected_active_generation=4,
    )
    unchanged_report = await lifecycle.validate_draft(
        draft.draft_id,
        report_id="unchanged-ready",
        evaluated_at=NOW + timedelta(minutes=2),
        reference_health=_resolved_reference_health(draft),
    )
    unchanged = await lifecycle.canonicalize_draft(
        draft.draft_id,
        validation_report_id=unchanged_report.report_id,
        revision_id="canonical-v3-unchanged",
        created_at=NOW + timedelta(minutes=3),
        actor="test:admin",
        source="test",
        change_kind="UPDATE",
        reason="unchanged_round_trip",
        core_version="0.16.0",
        fresh_reference_health=_resolved_reference_health(draft),
    )
    assert unchanged.semantic_configuration_fingerprint == active_v3.semantic_configuration_fingerprint
    assert unchanged.parent_revision_id == active_v3.revision_id
    assert unchanged.lineage["base_active_revision_id"] == active_v3.revision_id

    changed_heating = active_v3.heating.model_copy(
        update={
            "zones": (
                active_v3.heating.zones[0].model_copy(
                    update={
                        "demand_policy": active_v3.heating.zones[0].demand_policy.model_copy(
                            update={"target_temperature_celsius": 22.5}
                        )
                    }
                ),
            )
        }
    )
    edited = await lifecycle.update_draft(
        draft.draft_id,
        expected_revision=1,
        updated_at=NOW + timedelta(minutes=4),
        scopes=ConfigurationScopesV3(
            heating=changed_heating,
            diagnostics=draft.diagnostics,
            notifications=draft.notifications,
        ),
    )

    assert edited.heating.zones[0].demand_policy.target_temperature_celsius == 22.5
    assert edited.diagnostics == draft.diagnostics
    assert edited.notifications == draft.notifications
    assert edited.heating.model_dump(exclude={"zones"}) == draft.heating.model_dump(exclude={"zones"})
    assert edited.content_fingerprint != draft.content_fingerprint


async def _generation_and_lineage_conflicts_are_rejected(active_v3) -> None:
    repository = Repository(active_v3)
    lifecycle = CanonicalConfigurationLifecycleV3(repository)
    with pytest.raises(SetupConflictError, match="generation changed"):
        await lifecycle.clone_active_to_draft(
            active_v3.scope_key,
            draft_id="stale-start",
            created_at=NOW,
            expected_active_generation=3,
        )

    draft = await lifecycle.clone_active_to_draft(
        active_v3.scope_key,
        draft_id="stale-canonicalize",
        created_at=NOW,
        expected_active_generation=4,
    )
    report = await lifecycle.validate_draft(
        draft.draft_id,
        report_id="ready",
        evaluated_at=NOW,
        reference_health=_resolved_reference_health(draft),
    )
    repository.active = repository.active.model_copy(update={"generation": 5})
    with pytest.raises(SetupConflictError, match="authority changed"):
        await lifecycle.canonicalize_draft(
            draft.draft_id,
            validation_report_id=report.report_id,
            revision_id="must-not-exist",
            created_at=NOW,
            actor="test:admin",
            source="test",
            change_kind="UPDATE",
            reason="stale",
            core_version="0.16.0",
            fresh_reference_health=_resolved_reference_health(draft),
        )
    assert "must-not-exist" not in repository.revisions


async def _greenfield_draft_completes_lifecycle_without_existing_authority(active_v3) -> None:
    repository = Repository()
    lifecycle = CanonicalConfigurationLifecycleV3(repository)
    diagnostics = active_v3.diagnostics.model_copy(
        update={"debug_policy": active_v3.diagnostics.debug_policy.model_copy(update={"until_changed": False})}
    )
    scopes = ConfigurationScopesV3(
        heating=active_v3.heating,
        diagnostics=diagnostics,
        notifications=active_v3.notifications,
    )

    draft = await lifecycle.start_greenfield_draft(
        draft_id="first-v3-draft",
        configuration_id="new-heating-configuration",
        environment_id=active_v3.environment_id,
        provider=active_v3.provider,
        provider_instance_id=active_v3.provider_instance_id,
        created_at=NOW,
        scopes=scopes,
    )
    report = await lifecycle.validate_draft(
        draft.draft_id,
        report_id="first-v3-validation",
        evaluated_at=NOW,
        reference_health=_resolved_reference_health(draft),
    )
    canonical = await lifecycle.canonicalize_draft(
        draft.draft_id,
        validation_report_id=report.report_id,
        revision_id="first-v3-canonical",
        created_at=NOW,
        actor="test:admin",
        source="configuration_v3_api",
        change_kind="CREATE",
        reason="greenfield",
        core_version="0.16.0",
        fresh_reference_health=_resolved_reference_health(draft),
    )

    assert draft.base_active_revision_id is None
    assert draft.base_active_generation == 0
    assert draft.canonical_revision == 1
    assert draft.parent_revision_id is None
    assert report.activation_ready is True
    assert canonical.revision == 1
    assert canonical.parent_revision_id is None
    assert repository.active is None


async def _pre_authoring_metadata_v3_draft_keeps_existing_edit_lineage(active_v3) -> None:
    repository = Repository(active_v3)
    lifecycle = CanonicalConfigurationLifecycleV3(repository)
    draft = await lifecycle.clone_active_to_draft(
        active_v3.scope_key,
        draft_id="pre-authoring-metadata",
        created_at=NOW,
        expected_active_generation=4,
    )
    stored = draft.model_dump(mode="python")
    stored.pop("canonical_revision")
    stored.pop("parent_revision_id")
    restored = CanonicalConfigurationDraftV3.model_validate(stored)
    repository.drafts[draft.draft_id] = {draft.revision: restored}
    report = await lifecycle.validate_draft(
        draft.draft_id,
        report_id="pre-authoring-metadata-validation",
        evaluated_at=NOW,
        reference_health=_resolved_reference_health(restored),
    )

    canonical = await lifecycle.canonicalize_draft(
        draft.draft_id,
        validation_report_id=report.report_id,
        revision_id="pre-authoring-metadata-canonical",
        created_at=NOW,
        actor="test:admin",
        source="test",
        change_kind="UPDATE",
        reason="backward_compatible_draft",
        core_version="0.16.0",
        fresh_reference_health=_resolved_reference_health(restored),
    )

    assert restored.canonical_revision == 1
    assert restored.parent_revision_id is None
    assert canonical.revision == active_v3.revision + 1
    assert canonical.parent_revision_id == active_v3.revision_id


async def _draft_resume_list_and_abandon_are_durable_and_authority_safe(active_v3) -> None:
    repository = Repository(active_v3)
    first_lifecycle = CanonicalConfigurationLifecycleV3(repository)
    draft = await first_lifecycle.clone_active_to_draft(
        active_v3.scope_key,
        draft_id="durable-edit",
        created_at=NOW + timedelta(minutes=1),
        expected_active_generation=4,
    )
    active_before = repository.active

    restarted_lifecycle = CanonicalConfigurationLifecycleV3(repository)
    reopened = await restarted_lifecycle.reopen_draft(draft.draft_id)
    listed = await restarted_lifecycle.list_drafts()

    assert reopened == draft
    assert reopened.content_fingerprint == draft.content_fingerprint
    assert reopened.parent_revision_id == active_v3.revision_id
    assert listed == (draft,)

    with pytest.raises(SetupConflictError, match="stale draft deletion"):
        await restarted_lifecycle.abandon_draft(draft.draft_id, expected_revision=2)
    await restarted_lifecycle.abandon_draft(draft.draft_id, expected_revision=1)

    assert repository.active == active_before
    assert repository.revisions[active_v3.revision_id] == active_v3
    assert await restarted_lifecycle.list_drafts() == ()
    with pytest.raises(SetupNotFoundError):
        await restarted_lifecycle.reopen_draft(draft.draft_id)


async def _deferred_v1_fields_cannot_be_authored_or_edited(active_v3) -> None:
    repository = Repository(active_v3)
    lifecycle = CanonicalConfigurationLifecycleV3(repository)
    draft = await lifecycle.clone_active_to_draft(
        active_v3.scope_key,
        draft_id="deferred-fields",
        created_at=NOW,
        expected_active_generation=4,
    )
    physical_reference = active_v3.heating.zones[0].primary_temperature_sensor.provider_reference
    changed_source = draft.heating.heat_sources[0].model_copy(
        update={
            "observations": draft.heating.heat_sources[0].observations.model_copy(
                update={"physical_operation_reference": physical_reference}
            )
        }
    )
    changed_heating = draft.heating.model_copy(update={"heat_sources": (changed_source,)})
    with pytest.raises(SetupConflictError, match="physical heat-source operation evidence is deferred"):
        await lifecycle.update_draft(
            draft.draft_id,
            expected_revision=1,
            updated_at=NOW + timedelta(minutes=1),
            scopes=ConfigurationScopesV3(
                heating=changed_heating,
                diagnostics=draft.diagnostics,
                notifications=draft.notifications,
            ),
        )

    changed_diagnostics = draft.diagnostics.model_copy(
        update={
            "debug_policy": draft.diagnostics.debug_policy.model_copy(
                update={"until_changed": not draft.diagnostics.debug_policy.until_changed}
            )
        }
    )
    with pytest.raises(SetupConflictError, match="until-changed Debug policy is deferred"):
        await lifecycle.update_draft(
            draft.draft_id,
            expected_revision=1,
            updated_at=NOW + timedelta(minutes=1),
            scopes=ConfigurationScopesV3(
                heating=draft.heating,
                diagnostics=changed_diagnostics,
                notifications=draft.notifications,
            ),
        )

    greenfield = CanonicalConfigurationLifecycleV3(Repository())
    with pytest.raises(SetupConflictError, match="physical heat-source operation evidence is deferred"):
        await greenfield.start_greenfield_draft(
            draft_id="must-not-author-physical-evidence",
            configuration_id="new-v3-configuration",
            environment_id=active_v3.environment_id,
            provider=active_v3.provider,
            provider_instance_id=active_v3.provider_instance_id,
            created_at=NOW,
            scopes=ConfigurationScopesV3(
                heating=changed_heating,
                diagnostics=draft.diagnostics.model_copy(
                    update={"debug_policy": draft.diagnostics.debug_policy.model_copy(update={"until_changed": False})}
                ),
                notifications=draft.notifications,
            ),
        )


async def _canonicalization_rechecks_complete_fresh_reference_health(active_v3) -> None:
    repository = Repository(active_v3)
    lifecycle = CanonicalConfigurationLifecycleV3(repository)
    draft = await lifecycle.clone_active_to_draft(
        active_v3.scope_key,
        draft_id="fresh-reference-health",
        created_at=NOW,
        expected_active_generation=4,
    )
    resolved = _resolved_reference_health(draft)
    report = await lifecycle.validate_draft(
        draft.draft_id,
        report_id="initially-ready",
        evaluated_at=NOW,
        reference_health=resolved,
    )
    required_index = next(index for index, item in enumerate(resolved) if item.activation_required)
    missing = list(resolved)
    missing[required_index] = missing[required_index].model_copy(
        update={
            "status": ReferenceResolutionStatus.MISSING,
            "reason_code": "test.removed_after_validation",
            "resolved_reference": None,
        }
    )

    with pytest.raises(SetupConflictError, match="reference health changed before canonicalization"):
        await lifecycle.canonicalize_draft(
            draft.draft_id,
            validation_report_id=report.report_id,
            revision_id="must-not-canonicalize",
            created_at=NOW + timedelta(minutes=1),
            actor="test:admin",
            source="test",
            change_kind="UPDATE",
            reason="reference_removed",
            core_version="0.16.0",
            fresh_reference_health=tuple(missing),
        )
    assert "must-not-canonicalize" not in repository.revisions

    with pytest.raises(SetupConflictError, match="does not cover"):
        await lifecycle.validate_draft(
            draft.draft_id,
            report_id="incomplete-health",
            evaluated_at=NOW,
            reference_health=resolved[:-1],
        )


def test_active_read_and_clone_preserve_exact_semantic_configuration(active_v3) -> None:
    asyncio.run(_active_read_and_clone_preserve_exact_semantic_configuration(active_v3))


def test_one_field_edit_and_unchanged_round_trip_are_semantically_exact(active_v3) -> None:
    asyncio.run(_one_field_edit_and_unchanged_round_trip_are_semantically_exact(active_v3))


def test_generation_and_lineage_conflicts_are_rejected(active_v3) -> None:
    asyncio.run(_generation_and_lineage_conflicts_are_rejected(active_v3))


def test_greenfield_draft_completes_lifecycle_without_existing_authority(active_v3) -> None:
    asyncio.run(_greenfield_draft_completes_lifecycle_without_existing_authority(active_v3))


def test_pre_authoring_metadata_v3_draft_keeps_existing_edit_lineage(active_v3) -> None:
    asyncio.run(_pre_authoring_metadata_v3_draft_keeps_existing_edit_lineage(active_v3))


def test_draft_resume_list_and_abandon_are_durable_and_authority_safe(active_v3) -> None:
    asyncio.run(_draft_resume_list_and_abandon_are_durable_and_authority_safe(active_v3))


def test_deferred_v1_fields_cannot_be_authored_or_edited(active_v3) -> None:
    asyncio.run(_deferred_v1_fields_cannot_be_authored_or_edited(active_v3))


def test_canonicalization_rechecks_complete_fresh_reference_health(active_v3) -> None:
    asyncio.run(_canonicalization_rechecks_complete_fresh_reference_health(active_v3))
