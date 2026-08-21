"""Pure derivation of REAL and SHADOW runtime configuration projections."""

from __future__ import annotations

from collections.abc import Mapping

from controlel.application.setup.model import (
    BindingSelection,
    CanonicalConfigurationRevision,
    EffectiveRuntimeConfiguration,
    ProviderReference,
    RuntimeConfigurationOrigin,
)


def derive_real_runtime_configuration(
    revision: CanonicalConfigurationRevision,
    resolved_references: Mapping[str, ProviderReference],
) -> EffectiveRuntimeConfiguration:
    """Resolve locators without adding another configuration authority."""

    bindings = _resolved_bindings(revision, resolved_references, require_shadow=False)
    return EffectiveRuntimeConfiguration(
        canonical_revision_id=revision.revision_id,
        semantic_configuration_fingerprint=revision.semantic_configuration_fingerprint,
        module_key=revision.module_key,
        module_instance_id=revision.module_instance_id,
        module_schema_version=revision.module_schema_version,
        origin=RuntimeConfigurationOrigin.REAL,
        environment_id=revision.environment_id,
        bindings=bindings,
        module_payload=revision.module_payload,
        derivation_evidence={"resolution": "explicit_provider_reference_resolution"},
    )


def derive_shadow_runtime_configuration(
    revision: CanonicalConfigurationRevision,
    substitutions: Mapping[str, ProviderReference],
    *,
    shadow_environment_id: str,
) -> EffectiveRuntimeConfiguration:
    """Substitute every REAL binding explicitly; the result is never authoritative."""

    bindings = _resolved_bindings(revision, substitutions, require_shadow=True)
    return EffectiveRuntimeConfiguration(
        canonical_revision_id=revision.revision_id,
        semantic_configuration_fingerprint=revision.semantic_configuration_fingerprint,
        module_key=revision.module_key,
        module_instance_id=revision.module_instance_id,
        module_schema_version=revision.module_schema_version,
        origin=RuntimeConfigurationOrigin.SHADOW_SIMULATION,
        environment_id=shadow_environment_id,
        bindings=bindings,
        module_payload=revision.module_payload,
        derivation_evidence={
            "source_document_hash": revision.document_hash,
            "source_provider_instance_id": revision.provider_instance_id,
            "substitution": "explicit_real_to_shadow",
        },
    )


def _resolved_bindings(
    revision: CanonicalConfigurationRevision,
    references: Mapping[str, ProviderReference],
    *,
    require_shadow: bool,
) -> tuple[BindingSelection, ...]:
    expected_roles = {binding.role for binding in revision.bindings}
    if set(references) != expected_roles:
        missing = expected_roles - set(references)
        extra = set(references) - expected_roles
        raise ValueError(f"resolved binding roles differ; missing={sorted(missing)}, extra={sorted(extra)}")
    result: list[BindingSelection] = []
    for source in sorted(revision.bindings, key=lambda item: item.role):
        target = references[source.role]
        if require_shadow:
            if target.provider != "shadow_simulation":
                raise ValueError("Shadow substitutions must use shadow_simulation provider references")
        elif target.semantic_data() != source.reference.semantic_data():
            raise ValueError("REAL resolution may update locators but cannot replace provider identity")
        result.append(
            BindingSelection(
                role=source.role,
                reference=target,
                selection_origin=source.selection_origin,
                user_confirmed=source.user_confirmed,
                provenance=source.provenance,
            )
        )
    return tuple(result)
