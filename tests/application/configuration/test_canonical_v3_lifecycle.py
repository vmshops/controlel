"""Canonical configuration v3 edit lifecycle contracts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.configuration import (
    CanonicalConfigurationLifecycleV3,
    ConfigurationScopesV3,
    migrate_heating_v2_revision_to_v3,
)
from controlel.application.configuration.heating_setup_adapter import HeatingSetupAdapter
from controlel.application.setup import ActiveReference, SetupConflictError, SetupNotFoundError
from tests.application.setup.conftest import complete_draft

NOW = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)


class Repository:
    def __init__(self, revision) -> None:
        self.revisions = {revision.revision_id: revision}
        self.active = ActiveReference(
            environment_id=revision.environment_id,
            module_key=revision.module_key,
            module_instance_id=revision.module_instance_id,
            canonical_revision_id=revision.revision_id,
            semantic_configuration_fingerprint=revision.semantic_configuration_fingerprint,
            generation=4,
            committing_operation_id="activate-v3-base",
        )
        self.drafts = {}
        self.validations = {}

    async def get_active_reference(self, scope):
        return self.active if self.active.scope_key == scope else None

    async def get_canonical_revision_v3(self, revision_id):
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

    async def save_canonical_validation_v3(self, report):
        self.validations[report.report_id] = report

    async def get_canonical_validation_v3(self, report_id):
        try:
            return self.validations[report_id]
        except KeyError as error:
            raise SetupNotFoundError(report_id) from error


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
        core_version="0.15.0",
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
        reference_health=(),
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
        core_version="0.15.0",
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
        reference_health=(),
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
            core_version="0.15.0",
        )
    assert "must-not-exist" not in repository.revisions


def test_active_read_and_clone_preserve_exact_semantic_configuration(active_v3) -> None:
    asyncio.run(_active_read_and_clone_preserve_exact_semantic_configuration(active_v3))


def test_one_field_edit_and_unchanged_round_trip_are_semantically_exact(active_v3) -> None:
    asyncio.run(_one_field_edit_and_unchanged_round_trip_are_semantically_exact(active_v3))


def test_generation_and_lineage_conflicts_are_rejected(active_v3) -> None:
    asyncio.run(_generation_and_lineage_conflicts_are_rejected(active_v3))
