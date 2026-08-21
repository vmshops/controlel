"""Canonical Setup v1 import into durable, explicitly non-active drafts."""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from controlel.application.setup.model import (
    SETUP_SCHEMA_VERSION,
    BindingSelection,
    CanonicalConfigurationRevision,
    DraftRevision,
    SelectionOrigin,
)
from controlel.application.setup.repository import DraftRepository


class UnsupportedSetupSchemaVersion(ValueError):
    def __init__(self, version: object) -> None:
        super().__init__(f"unsupported setup schema version: {version}")
        self.version = version


class CanonicalImportIntegrityError(ValueError):
    """Raised before persistence when canonical integrity evidence is absent."""


class ConfigurationImportResult(BaseModel):
    source_revision_id: str
    source_document_hash: str
    draft: DraftRevision
    activated: bool = False

    model_config = ConfigDict(frozen=True, extra="forbid")


class CanonicalConfigurationImporter:
    def __init__(self, drafts: DraftRepository) -> None:
        self._drafts = drafts

    def import_to_draft(
        self,
        source: str,
        *,
        draft_id: str,
        imported_at: datetime,
        target_environment_id: str,
    ) -> ConfigurationImportResult:
        document = _parse_json_document(source)
        schema_version = document.get("schema_version")
        if schema_version != SETUP_SCHEMA_VERSION:
            raise UnsupportedSetupSchemaVersion(schema_version)
        _require_integrity_fields(document)
        canonical = CanonicalConfigurationRevision.model_validate(document)
        imported_bindings = tuple(
            BindingSelection(
                role=binding.role,
                reference=binding.reference,
                selection_origin=SelectionOrigin.IMPORTED,
                user_confirmed=False,
                provenance={
                    "source_document_hash": canonical.document_hash,
                    "source_revision_id": canonical.revision_id,
                    "historical_selection_origin": binding.selection_origin.value,
                    "historical_user_confirmation": binding.user_confirmed,
                },
            )
            for binding in canonical.bindings
        )
        draft = DraftRevision(
            draft_id=draft_id,
            revision=1,
            environment_id=target_environment_id,
            module_key=canonical.module_key,
            module_instance_id=canonical.module_instance_id,
            module_schema_version=canonical.module_schema_version,
            created_at=imported_at,
            updated_at=imported_at,
            settings=canonical.module_payload,
            bindings=imported_bindings,
            lineage={
                "imported_from_revision_id": canonical.revision_id,
                "imported_from_document_hash": canonical.document_hash,
            },
            import_provenance={
                "source_revision_id": canonical.revision_id,
                "source_document_hash": canonical.document_hash,
                "source_environment_id": canonical.environment_id,
                "source_provider_instance_id": canonical.provider_instance_id,
                "source_semantic_configuration_fingerprint": canonical.semantic_configuration_fingerprint,
            },
        )
        self._drafts.save_draft(draft)
        return ConfigurationImportResult(
            source_revision_id=canonical.revision_id,
            source_document_hash=canonical.document_hash,
            draft=draft,
        )


def _parse_json_document(source: str) -> dict[str, object]:
    def pairs_to_mapping(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    loaded = json.loads(source, object_pairs_hook=pairs_to_mapping, parse_constant=_reject_constant)
    if not isinstance(loaded, dict):
        raise TypeError("canonical configuration document must be a JSON object")
    return loaded


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON value is not supported: {value}")


def _require_integrity_fields(document: dict[str, object]) -> None:
    for field_name in ("semantic_configuration_fingerprint", "document_hash"):
        value = document.get(field_name)
        if not isinstance(value, str) or not value:
            raise CanonicalImportIntegrityError(f"canonical import requires {field_name}")
