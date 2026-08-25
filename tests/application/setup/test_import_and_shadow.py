import json
from datetime import timedelta

import pytest
from pydantic import ValidationError

from controlel.application.configuration.heating_setup_adapter import HeatingSetupAdapter
from controlel.application.setup import (
    BindingSelection,
    CanonicalConfigurationImporter,
    CanonicalImportIntegrityError,
    EffectiveRuntimeConfiguration,
    IdentityQuality,
    InMemorySetupRepository,
    ProviderReference,
    RuntimeConfigurationOrigin,
    SelectionOrigin,
    SetupNotFoundError,
    UnsupportedSetupSchemaVersion,
    derive_shadow_runtime_configuration,
)

from .conftest import NOW


def test_import_creates_non_active_draft_and_never_changes_authority(canonical_revision) -> None:
    repository = InMemorySetupRepository()
    repository.add_canonical_revision(canonical_revision)
    importer = CanonicalConfigurationImporter(repository)

    result = importer.import_to_draft(
        canonical_revision.canonical_json(),
        draft_id="imported-draft",
        imported_at=NOW,
        target_environment_id="other-home",
    )

    assert result.activated is False
    assert result.draft.environment_id == "other-home"
    assert all(binding.selection_origin is SelectionOrigin.IMPORTED for binding in result.draft.bindings)
    assert all(not binding.user_confirmed for binding in result.draft.bindings)
    assert repository.get_active_reference(("other-home", "heating", "main-heating")) is None
    assert repository.get_draft("imported-draft") == result.draft


def test_import_rejects_unsupported_schema_before_interpreting_document(canonical_revision) -> None:
    repository = InMemorySetupRepository()
    document = json.loads(canonical_revision.canonical_json())
    document["schema_version"] = 99

    with pytest.raises(UnsupportedSetupSchemaVersion, match="unsupported setup schema version: 99"):
        CanonicalConfigurationImporter(repository).import_to_draft(
            json.dumps(document),
            draft_id="unsupported",
            imported_at=NOW,
            target_environment_id="home",
        )

    with pytest.raises(SetupNotFoundError):
        repository.get_draft("unsupported")


@pytest.mark.parametrize("missing_field", ["document_hash", "semantic_configuration_fingerprint"])
def test_import_requires_original_integrity_fields_before_persistence(canonical_revision, missing_field) -> None:
    repository = InMemorySetupRepository()
    document = json.loads(canonical_revision.canonical_json())
    document.pop(missing_field)

    with pytest.raises(CanonicalImportIntegrityError, match=missing_field):
        CanonicalConfigurationImporter(repository).import_to_draft(
            json.dumps(document),
            draft_id="missing-integrity",
            imported_at=NOW,
            target_environment_id="home",
        )

    with pytest.raises(SetupNotFoundError):
        repository.get_draft("missing-integrity")


@pytest.mark.parametrize("mismatching_field", ["document_hash", "semantic_configuration_fingerprint"])
def test_import_rejects_mismatching_integrity_before_persistence(canonical_revision, mismatching_field) -> None:
    repository = InMemorySetupRepository()
    document = json.loads(canonical_revision.canonical_json())
    document[mismatching_field] = "0" * 64

    with pytest.raises(ValidationError, match="does not match"):
        CanonicalConfigurationImporter(repository).import_to_draft(
            json.dumps(document),
            draft_id="mismatching-integrity",
            imported_at=NOW,
            target_environment_id="home",
        )

    with pytest.raises(SetupNotFoundError):
        repository.get_draft("mismatching-integrity")


def test_import_provenance_survives_later_canonicalization(canonical_revision) -> None:
    repository = InMemorySetupRepository()
    imported = (
        CanonicalConfigurationImporter(repository)
        .import_to_draft(
            canonical_revision.canonical_json(),
            draft_id="imported",
            imported_at=NOW,
            target_environment_id="home",
        )
        .draft
    )
    confirmed = imported.next_revision(
        updated_at=NOW + timedelta(seconds=1),
        bindings=tuple(
            BindingSelection(
                role=binding.role,
                reference=binding.reference,
                selection_origin=binding.selection_origin,
                user_confirmed=True,
                provenance=binding.provenance,
            )
            for binding in imported.bindings
        ),
    )
    adapter = HeatingSetupAdapter()
    report = adapter.validate(confirmed, report_id="import-validation", evaluated_at=NOW + timedelta(seconds=1))
    canonical = adapter.canonicalize(
        confirmed,
        report,
        configuration_id="imported-config",
        revision_id="imported-revision",
        revision=1,
        provider="home_assistant",
        provider_instance_id="ha-home",
        created_at=NOW + timedelta(seconds=2),
        actor="user:owner",
        source="setup_import",
        change_kind="IMPORT",
        reason="restore_backup",
        core_version="0.11.0",
    )

    assert canonical.import_provenance["source_document_hash"] == canonical_revision.document_hash
    assert canonical.lineage["imported_from_revision_id"] == canonical_revision.revision_id


def test_shadow_substitution_is_explicit_and_non_authoritative(canonical_revision) -> None:
    substitutions = {
        binding.role: ProviderReference(
            provider="shadow_simulation",
            provider_instance_id="shadow-run-1",
            object_kind="shadow.endpoint",
            native_id=f"virtual-{index}",
            identity_quality=IdentityQuality.STABLE,
            current_locator=f"virtual://{binding.role}",
        )
        for index, binding in enumerate(canonical_revision.bindings)
    }

    derived = derive_shadow_runtime_configuration(
        canonical_revision,
        substitutions,
        shadow_environment_id="shadow-environment-1",
    )

    assert derived.origin is RuntimeConfigurationOrigin.SHADOW_SIMULATION
    assert derived.authoritative is False
    assert derived.canonical_revision_id == canonical_revision.revision_id
    assert derived.semantic_configuration_fingerprint == canonical_revision.semantic_configuration_fingerprint
    assert all(binding.reference.provider == "shadow_simulation" for binding in derived.bindings)
    assert canonical_revision.provider == "home_assistant"


def test_shadow_derived_configuration_cannot_be_marked_authoritative(canonical_revision) -> None:
    with pytest.raises(ValidationError):
        EffectiveRuntimeConfiguration(
            canonical_revision_id=canonical_revision.revision_id,
            semantic_configuration_fingerprint=canonical_revision.semantic_configuration_fingerprint,
            module_key="heating",
            module_instance_id="main-heating",
            module_schema_version=canonical_revision.module_schema_version,
            origin=RuntimeConfigurationOrigin.SHADOW_SIMULATION,
            environment_id="shadow",
            bindings=(),
            module_payload={},
            authoritative=True,
        )


def test_shadow_derivation_rejects_partial_or_real_binding_substitution(canonical_revision) -> None:
    with pytest.raises(ValueError, match="resolved binding roles differ"):
        derive_shadow_runtime_configuration(
            canonical_revision,
            {},
            shadow_environment_id="shadow",
        )

    real_references = {binding.role: binding.reference for binding in canonical_revision.bindings}
    with pytest.raises(ValueError, match="shadow_simulation"):
        derive_shadow_runtime_configuration(
            canonical_revision,
            real_references,
            shadow_environment_id="shadow",
        )


def test_real_effective_configuration_rejects_shadow_bindings(canonical_revision) -> None:
    shadow_binding = canonical_revision.bindings[0].model_copy(
        update={
            "reference": ProviderReference(
                provider="shadow_simulation",
                provider_instance_id="shadow-run",
                object_kind="shadow.endpoint",
                native_id="virtual-endpoint",
                identity_quality=IdentityQuality.STABLE,
                current_locator="virtual://endpoint",
            )
        }
    )

    with pytest.raises(ValidationError, match="REAL runtime configuration cannot contain SHADOW bindings"):
        EffectiveRuntimeConfiguration(
            canonical_revision_id=canonical_revision.revision_id,
            semantic_configuration_fingerprint=canonical_revision.semantic_configuration_fingerprint,
            module_key=canonical_revision.module_key,
            module_instance_id=canonical_revision.module_instance_id,
            module_schema_version=canonical_revision.module_schema_version,
            origin=RuntimeConfigurationOrigin.REAL,
            environment_id=canonical_revision.environment_id,
            bindings=(shadow_binding,),
            module_payload=canonical_revision.module_payload,
        )
