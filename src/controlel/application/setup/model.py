"""Immutable, module-neutral Setup / Discovery / Import contracts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from controlel.application.setup.json_data import (
    FrozenJsonMapping,
    ImmutableJsonMapping,
    aware_datetime,
    canonical_json,
    immutable_json_mapping,
    normalize_json,
)

SETUP_SCHEMA_VERSION = 1
CANONICALIZATION_POLICY_VERSION = 1
SEMANTIC_FINGERPRINT_POLICY_VERSION = 1
_HASH_PATTERN = r"^[0-9a-f]{64}$"


class IdentityQuality(StrEnum):
    STABLE = "STABLE"
    EPHEMERAL = "EPHEMERAL"


class SelectionOrigin(StrEnum):
    MANUAL = "MANUAL"
    RECOMMENDATION_ACCEPTED = "RECOMMENDATION_ACCEPTED"
    IMPORTED = "IMPORTED"
    MIGRATED = "MIGRATED"
    CLONED_FROM_ACTIVE = "CLONED_FROM_ACTIVE"


class ValidationSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class ValidationSubjectKind(StrEnum):
    DRAFT = "DRAFT"
    CANONICAL_REVISION = "CANONICAL_REVISION"


class ActivationState(StrEnum):
    PREPARED = "PREPARED"
    APPLYING = "APPLYING"
    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


class RuntimeConfigurationOrigin(StrEnum):
    REAL = "REAL"
    SHADOW_SIMULATION = "SHADOW_SIMULATION"


class ProviderReference(BaseModel):
    """Provider-scoped identity; current locators are never the identity."""

    provider: str = Field(min_length=1)
    provider_instance_id: str = Field(min_length=1)
    object_kind: str = Field(min_length=1)
    native_id: str | None = None
    identity_quality: IdentityQuality
    current_locator: str | None = None
    device_registry_id: str | None = None
    area_id: str | None = None
    floor_id: str | None = None
    recovery_evidence: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("recovery_evidence", mode="after")
    @classmethod
    def evidence_must_be_immutable(cls, value: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, "recovery_evidence")

    @model_validator(mode="after")
    def identity_shape_must_be_truthful(self) -> ProviderReference:
        if self.identity_quality is IdentityQuality.STABLE and not self.native_id:
            raise ValueError("STABLE provider references require native_id")
        if self.identity_quality is IdentityQuality.EPHEMERAL:
            if self.native_id is not None:
                raise ValueError("EPHEMERAL provider references cannot claim a stable native_id")
            if not self.current_locator:
                raise ValueError("EPHEMERAL provider references require current_locator")
        return self

    def semantic_data(self) -> dict[str, object]:
        """Identity-bearing data; stable locators and recovery hints are excluded."""

        data: dict[str, object] = {
            "provider": self.provider,
            "provider_instance_id": self.provider_instance_id,
            "object_kind": self.object_kind,
            "native_id": self.native_id,
            "identity_quality": self.identity_quality.value,
        }
        if self.identity_quality is IdentityQuality.EPHEMERAL:
            data["current_locator"] = self.current_locator
        return data

    def document_data(self) -> dict[str, object]:
        return {
            **self.semantic_data(),
            "current_locator": self.current_locator,
            "device_registry_id": self.device_registry_id,
            "area_id": self.area_id,
            "floor_id": self.floor_id,
            "recovery_evidence": normalize_json(self.recovery_evidence),
        }


ProviderObjectReference = ProviderReference


class DiscoverySnapshot(BaseModel):
    """One immutable, read-only observation of provider structure."""

    schema_version: int = SETUP_SCHEMA_VERSION
    snapshot_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provider_instance_id: str = Field(min_length=1)
    adapter_contract_version: str = Field(min_length=1)
    captured_at: datetime
    objects: tuple[ProviderReference, ...] = ()
    capabilities: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    content_fingerprint: str | None = Field(default=None, pattern=_HASH_PATTERN)

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("schema_version")
    @classmethod
    def schema_version_must_be_supported(cls, value: int) -> int:
        if value != SETUP_SCHEMA_VERSION:
            raise ValueError(f"unsupported setup schema version: {value}")
        return value

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_be_aware(cls, value: datetime) -> datetime:
        return aware_datetime(value, "captured_at")

    @field_validator("capabilities", mode="after")
    @classmethod
    def capabilities_must_be_immutable(cls, value: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, "capabilities")

    @model_validator(mode="after")
    def fingerprint_must_match_content(self) -> DiscoverySnapshot:
        if any(item.provider != self.provider for item in self.objects):
            raise ValueError("discovered objects must belong to the snapshot provider")
        if any(item.provider_instance_id != self.provider_instance_id for item in self.objects):
            raise ValueError("discovered objects must belong to the snapshot provider instance")
        ordered_objects = tuple(
            sorted(
                self.objects,
                key=lambda item: (
                    item.object_kind,
                    item.native_id or "",
                    item.current_locator or "",
                    canonical_json(item.document_data()),
                ),
            )
        )
        object.__setattr__(self, "objects", ordered_objects)
        expected = _sha256(
            {
                "schema_version": self.schema_version,
                "provider": self.provider,
                "provider_instance_id": self.provider_instance_id,
                "adapter_contract_version": self.adapter_contract_version,
                "captured_at": self.captured_at,
                "objects": [item.document_data() for item in ordered_objects],
                "capabilities": self.capabilities,
            }
        )
        if self.content_fingerprint is not None and self.content_fingerprint != expected:
            raise ValueError("discovery content fingerprint does not match snapshot")
        object.__setattr__(self, "content_fingerprint", expected)
        return self


class BindingSelection(BaseModel):
    """A persisted user/import selection, separate from recommendation advice."""

    role: str = Field(min_length=1)
    reference: ProviderReference
    selection_origin: SelectionOrigin
    user_confirmed: bool = False
    provenance: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("provenance", mode="after")
    @classmethod
    def provenance_must_be_immutable(cls, value: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, "binding provenance")

    def semantic_data(self) -> dict[str, object]:
        return {
            "role": self.role,
            "reference": self.reference.semantic_data(),
        }

    def document_data(self) -> dict[str, object]:
        return {
            "role": self.role,
            "reference": self.reference.document_data(),
            "selection_origin": self.selection_origin.value,
            "user_confirmed": self.user_confirmed,
            "provenance": normalize_json(self.provenance),
        }


class DraftRevision(BaseModel):
    """One persistable revision of incomplete or complete editable intent."""

    draft_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    environment_id: str = Field(min_length=1)
    module_key: str = Field(min_length=1)
    module_instance_id: str = Field(min_length=1)
    module_schema_version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    base_active_revision_id: str | None = None
    settings: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    bindings: tuple[BindingSelection, ...] = ()
    lineage: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    import_provenance: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    migration_provenance: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime, info: object) -> datetime:
        return aware_datetime(value, str(getattr(info, "field_name", "timestamp")))

    @field_validator("settings", "lineage", "import_provenance", "migration_provenance", mode="after")
    @classmethod
    def mappings_must_be_immutable(cls, value: object, info: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, str(getattr(info, "field_name", "mapping")))

    @model_validator(mode="after")
    def revision_must_be_consistent(self) -> DraftRevision:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        _require_unique_binding_roles(self.bindings)
        return self

    @property
    def content_fingerprint(self) -> str:
        return _sha256(
            {
                "environment_id": self.environment_id,
                "module_key": self.module_key,
                "module_instance_id": self.module_instance_id,
                "module_schema_version": self.module_schema_version,
                "settings": self.settings,
                "bindings": [binding.document_data() for binding in sorted(self.bindings, key=lambda item: item.role)],
            }
        )

    def next_revision(
        self,
        *,
        updated_at: datetime,
        settings: Mapping[str, object] | None = None,
        bindings: tuple[BindingSelection, ...] | None = None,
    ) -> DraftRevision:
        return DraftRevision(
            draft_id=self.draft_id,
            revision=self.revision + 1,
            environment_id=self.environment_id,
            module_key=self.module_key,
            module_instance_id=self.module_instance_id,
            module_schema_version=self.module_schema_version,
            created_at=self.created_at,
            updated_at=updated_at,
            base_active_revision_id=self.base_active_revision_id,
            settings=self.settings if settings is None else settings,
            bindings=self.bindings if bindings is None else bindings,
            lineage=self.lineage,
            import_provenance=self.import_provenance,
            migration_provenance=self.migration_provenance,
        )


class ValidationIssue(BaseModel):
    code: str = Field(min_length=1)
    severity: ValidationSeverity
    path: tuple[str, ...] = ()
    module_role: str | None = None
    message_key: str = Field(min_length=1)
    parameters: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    evidence: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    suggested_action: str | None = None

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("parameters", "evidence", mode="after")
    @classmethod
    def mappings_must_be_immutable(cls, value: object, info: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, str(getattr(info, "field_name", "mapping")))


class ValidationReport(BaseModel):
    report_id: str = Field(min_length=1)
    subject_kind: ValidationSubjectKind
    subject_id: str = Field(min_length=1)
    subject_revision: int = Field(ge=1)
    subject_fingerprint: str = Field(pattern=_HASH_PATTERN)
    module_key: str = Field(min_length=1)
    module_schema_version: int = Field(ge=1)
    validator_policy_version: int = Field(ge=1)
    evaluated_at: datetime
    discovery_snapshot_id: str | None = None
    resolution_generation: int | None = Field(default=None, ge=0)
    issues: tuple[ValidationIssue, ...] = ()
    activation_ready: bool

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_must_be_aware(cls, value: datetime) -> datetime:
        return aware_datetime(value, "evaluated_at")

    @model_validator(mode="after")
    def readiness_cannot_ignore_errors(self) -> ValidationReport:
        if self.activation_ready and any(issue.severity is ValidationSeverity.ERROR for issue in self.issues):
            raise ValueError("activation-ready validation cannot contain errors")
        return self

    def assesses(self, draft: DraftRevision) -> bool:
        return (
            self.subject_kind is ValidationSubjectKind.DRAFT
            and self.subject_id == draft.draft_id
            and self.subject_revision == draft.revision
            and self.subject_fingerprint == draft.content_fingerprint
            and self.module_key == draft.module_key
            and self.module_schema_version == draft.module_schema_version
        )


class CanonicalConfigurationRevision(BaseModel):
    """The sole persisted normalized configuration authority."""

    schema_version: int = SETUP_SCHEMA_VERSION
    canonicalization_policy_version: int = CANONICALIZATION_POLICY_VERSION
    semantic_fingerprint_policy_version: int = SEMANTIC_FINGERPRINT_POLICY_VERSION
    configuration_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    parent_revision_id: str | None = None
    environment_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provider_instance_id: str = Field(min_length=1)
    module_key: str = Field(min_length=1)
    module_instance_id: str = Field(min_length=1)
    module_schema_version: int = Field(ge=1)
    created_at: datetime
    actor: str = Field(min_length=1)
    source: str = Field(min_length=1)
    change_kind: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    core_version: str = Field(min_length=1)
    integration_version: str | None = None
    logical_identities: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    bindings: tuple[BindingSelection, ...]
    module_payload: ImmutableJsonMapping
    lineage: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    import_provenance: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    migration_provenance: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    semantic_configuration_fingerprint: str = Field(default="", pattern=_HASH_PATTERN)
    document_hash: str = Field(default="", pattern=_HASH_PATTERN)

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("schema_version")
    @classmethod
    def schema_version_must_be_supported(cls, value: int) -> int:
        if value != SETUP_SCHEMA_VERSION:
            raise ValueError(f"unsupported setup schema version: {value}")
        return value

    @field_validator("canonicalization_policy_version")
    @classmethod
    def canonicalization_policy_must_be_supported(cls, value: int) -> int:
        if value != CANONICALIZATION_POLICY_VERSION:
            raise ValueError(f"unsupported canonicalization policy version: {value}")
        return value

    @field_validator("semantic_fingerprint_policy_version")
    @classmethod
    def fingerprint_policy_must_be_supported(cls, value: int) -> int:
        if value != SEMANTIC_FINGERPRINT_POLICY_VERSION:
            raise ValueError(f"unsupported semantic fingerprint policy version: {value}")
        return value

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_aware(cls, value: datetime) -> datetime:
        return aware_datetime(value, "created_at")

    @field_validator(
        "logical_identities",
        "module_payload",
        "lineage",
        "import_provenance",
        "migration_provenance",
        mode="after",
    )
    @classmethod
    def mappings_must_be_immutable(cls, value: object, info: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, str(getattr(info, "field_name", "mapping")))

    @model_validator(mode="after")
    def hashes_must_match_content(self) -> CanonicalConfigurationRevision:
        _require_unique_binding_roles(self.bindings)
        expected_semantic = _sha256(self.semantic_data())
        if self.semantic_configuration_fingerprint and self.semantic_configuration_fingerprint != expected_semantic:
            raise ValueError("semantic configuration fingerprint does not match revision")
        object.__setattr__(self, "semantic_configuration_fingerprint", expected_semantic)
        expected_document = _sha256(self.document_body())
        if self.document_hash and self.document_hash != expected_document:
            raise ValueError("document hash does not match canonical revision")
        object.__setattr__(self, "document_hash", expected_document)
        return self

    @classmethod
    def from_validated_draft(
        cls,
        draft: DraftRevision,
        report: ValidationReport,
        *,
        configuration_id: str,
        revision_id: str,
        revision: int,
        provider: str,
        provider_instance_id: str,
        created_at: datetime,
        actor: str,
        source: str,
        change_kind: str,
        reason: str,
        core_version: str,
        normalized_payload: Mapping[str, object],
        logical_identities: Mapping[str, object],
        integration_version: str | None = None,
        parent_revision_id: str | None = None,
    ) -> CanonicalConfigurationRevision:
        if not report.assesses(draft):
            raise ValueError("validation report does not assess the exact draft revision")
        if not report.activation_ready:
            raise ValueError("draft is not activation-ready")
        return cls(
            configuration_id=configuration_id,
            revision_id=revision_id,
            revision=revision,
            parent_revision_id=parent_revision_id,
            environment_id=draft.environment_id,
            provider=provider,
            provider_instance_id=provider_instance_id,
            module_key=draft.module_key,
            module_instance_id=draft.module_instance_id,
            module_schema_version=draft.module_schema_version,
            created_at=created_at,
            actor=actor,
            source=source,
            change_kind=change_kind,
            reason=reason,
            core_version=core_version,
            integration_version=integration_version,
            logical_identities=logical_identities,
            bindings=draft.bindings,
            module_payload=normalized_payload,
            lineage={
                **dict(draft.lineage),
                "draft_id": draft.draft_id,
                "draft_revision": draft.revision,
            },
            import_provenance=draft.import_provenance,
            migration_provenance=draft.migration_provenance,
        )

    def semantic_data(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "semantic_fingerprint_policy_version": self.semantic_fingerprint_policy_version,
            "environment_id": self.environment_id,
            "provider": self.provider,
            "provider_instance_id": self.provider_instance_id,
            "module_key": self.module_key,
            "module_instance_id": self.module_instance_id,
            "module_schema_version": self.module_schema_version,
            "logical_identities": normalize_json(self.logical_identities),
            "bindings": [binding.semantic_data() for binding in sorted(self.bindings, key=lambda item: item.role)],
            "module_payload": normalize_json(self.module_payload),
        }

    def document_body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "canonicalization_policy_version": self.canonicalization_policy_version,
            "semantic_fingerprint_policy_version": self.semantic_fingerprint_policy_version,
            "configuration_id": self.configuration_id,
            "revision_id": self.revision_id,
            "revision": self.revision,
            "parent_revision_id": self.parent_revision_id,
            "environment_id": self.environment_id,
            "provider": self.provider,
            "provider_instance_id": self.provider_instance_id,
            "module_key": self.module_key,
            "module_instance_id": self.module_instance_id,
            "module_schema_version": self.module_schema_version,
            "created_at": self.created_at,
            "actor": self.actor,
            "source": self.source,
            "change_kind": self.change_kind,
            "reason": self.reason,
            "core_version": self.core_version,
            "integration_version": self.integration_version,
            "logical_identities": normalize_json(self.logical_identities),
            "bindings": [binding.document_data() for binding in sorted(self.bindings, key=lambda item: item.role)],
            "module_payload": normalize_json(self.module_payload),
            "lineage": normalize_json(self.lineage),
            "import_provenance": normalize_json(self.import_provenance),
            "migration_provenance": normalize_json(self.migration_provenance),
            "semantic_configuration_fingerprint": self.semantic_configuration_fingerprint,
        }

    def canonical_data(self) -> FrozenJsonMapping:
        return immutable_json_mapping(
            {**self.document_body(), "document_hash": self.document_hash},
            "canonical revision",
        )

    def canonical_json(self) -> str:
        return canonical_json(self.canonical_data())


class ActiveReference(BaseModel):
    """Atomic selection of a canonical revision for one module instance."""

    environment_id: str = Field(min_length=1)
    module_key: str = Field(min_length=1)
    module_instance_id: str = Field(min_length=1)
    canonical_revision_id: str = Field(min_length=1)
    semantic_configuration_fingerprint: str = Field(pattern=_HASH_PATTERN)
    generation: int = Field(ge=1)
    committing_operation_id: str = Field(min_length=1)

    model_config = ConfigDict(frozen=True, extra="forbid")

    @property
    def scope_key(self) -> tuple[str, str, str]:
        return self.environment_id, self.module_key, self.module_instance_id


class LoadedRuntimeConfiguration(BaseModel):
    canonical_revision_id: str = Field(min_length=1)
    semantic_configuration_fingerprint: str = Field(pattern=_HASH_PATTERN)
    environment_id: str = Field(min_length=1)
    origin: Literal[RuntimeConfigurationOrigin.REAL] = RuntimeConfigurationOrigin.REAL
    module_key: str = Field(min_length=1)
    module_instance_id: str = Field(min_length=1)

    model_config = ConfigDict(frozen=True, extra="forbid")


class CandidateRuntimeReady(BaseModel):
    """Host evidence that a candidate crossed the documented startup boundary."""

    runtime: LoadedRuntimeConfiguration
    ready_at: datetime
    host_adapter: str = Field(min_length=1)
    readiness_evidence: ImmutableJsonMapping

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("ready_at")
    @classmethod
    def ready_at_must_be_aware(cls, value: datetime) -> datetime:
        return aware_datetime(value, "ready_at")

    @field_validator("readiness_evidence", mode="after")
    @classmethod
    def readiness_evidence_must_be_immutable(cls, value: object) -> FrozenJsonMapping:
        evidence = immutable_json_mapping(value, "readiness_evidence")
        if not evidence:
            raise ValueError("candidate readiness evidence must not be empty")
        return evidence


class EffectiveRuntimeConfiguration(BaseModel):
    """Transient projection derived wholly from one canonical authority."""

    canonical_revision_id: str = Field(min_length=1)
    semantic_configuration_fingerprint: str = Field(pattern=_HASH_PATTERN)
    module_key: str = Field(min_length=1)
    module_instance_id: str = Field(min_length=1)
    module_schema_version: int = Field(ge=1)
    origin: RuntimeConfigurationOrigin
    environment_id: str = Field(min_length=1)
    bindings: tuple[BindingSelection, ...]
    module_payload: ImmutableJsonMapping
    derivation_evidence: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    authoritative: Literal[False] = False

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("module_payload", "derivation_evidence", mode="after")
    @classmethod
    def mappings_must_be_immutable(cls, value: object, info: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, str(getattr(info, "field_name", "mapping")))

    @model_validator(mode="after")
    def binding_roles_and_origin_must_be_consistent(self) -> EffectiveRuntimeConfiguration:
        _require_unique_binding_roles(self.bindings)
        providers = {binding.reference.provider for binding in self.bindings}
        if self.origin is RuntimeConfigurationOrigin.REAL and "shadow_simulation" in providers:
            raise ValueError("REAL runtime configuration cannot contain SHADOW bindings")
        if self.origin is RuntimeConfigurationOrigin.SHADOW_SIMULATION and providers - {"shadow_simulation"}:
            raise ValueError("SHADOW runtime configuration requires only SHADOW bindings")
        return self


class ActivationAttempt(BaseModel):
    """Durable activation transaction evidence; state does not select a revision."""

    attempt_id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    environment_id: str = Field(min_length=1)
    module_key: str = Field(min_length=1)
    module_instance_id: str = Field(min_length=1)
    state: ActivationState
    candidate_revision_id: str = Field(min_length=1)
    candidate_semantic_fingerprint: str = Field(pattern=_HASH_PATTERN)
    previous_revision_id: str | None = None
    previous_semantic_fingerprint: str | None = Field(default=None, pattern=_HASH_PATTERN)
    last_known_good_revision_id: str | None = None
    last_known_good_semantic_fingerprint: str | None = Field(default=None, pattern=_HASH_PATTERN)
    expected_active_generation: int = Field(ge=0)
    prepared_at: datetime
    applying_at: datetime | None = None
    completed_at: datetime | None = None
    interruption_recovered_at: datetime | None = None
    candidate_runtime_ready: CandidateRuntimeReady | None = None
    rollback_runtime_stamp: LoadedRuntimeConfiguration | None = None
    failure_evidence: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("prepared_at", "applying_at", "completed_at", "interruption_recovered_at")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime | None, info: object) -> datetime | None:
        if value is None:
            return None
        return aware_datetime(value, str(getattr(info, "field_name", "timestamp")))

    @field_validator("failure_evidence", mode="after")
    @classmethod
    def failure_evidence_must_be_immutable(cls, value: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, "failure_evidence")

    @model_validator(mode="after")
    def lifecycle_shape_must_be_consistent(self) -> ActivationAttempt:
        if (self.previous_revision_id is None) != (self.previous_semantic_fingerprint is None):
            raise ValueError("previous revision and fingerprint must be present together")
        if (self.last_known_good_revision_id is None) != (self.last_known_good_semantic_fingerprint is None):
            raise ValueError("last-known-good revision and fingerprint must be present together")
        if self.state is ActivationState.PREPARED and self.applying_at is not None:
            raise ValueError("PREPARED attempt cannot have applying_at")
        if self.state is not ActivationState.PREPARED and self.applying_at is None:
            raise ValueError(f"{self.state.value} attempt requires applying_at")
        if self.state in {ActivationState.COMMITTED, ActivationState.ROLLED_BACK, ActivationState.FAILED}:
            if self.completed_at is None:
                raise ValueError("terminal activation attempts require completed_at")
        elif self.completed_at is not None:
            raise ValueError("non-terminal activation attempts cannot have completed_at")
        if self.state is ActivationState.COMMITTED:
            if self.candidate_runtime_ready is None:
                raise ValueError("COMMITTED attempt requires candidate runtime readiness")
        if self.candidate_runtime_ready is not None:
            _require_attempt_runtime_match(
                self,
                self.candidate_runtime_ready.runtime,
                revision_id=self.candidate_revision_id,
                fingerprint=self.candidate_semantic_fingerprint,
                label="candidate",
            )
        if self.rollback_runtime_stamp is not None:
            rollback_revision_id = self.last_known_good_revision_id or self.previous_revision_id
            rollback_fingerprint = self.last_known_good_semantic_fingerprint or self.previous_semantic_fingerprint
            if rollback_revision_id is None or rollback_fingerprint is None:
                raise ValueError("rollback runtime evidence requires a previous or last-known-good revision")
            _require_attempt_runtime_match(
                self,
                self.rollback_runtime_stamp,
                revision_id=rollback_revision_id,
                fingerprint=rollback_fingerprint,
                label="rollback",
            )
        return self

    @property
    def scope_key(self) -> tuple[str, str, str]:
        return self.environment_id, self.module_key, self.module_instance_id


def _require_unique_binding_roles(bindings: tuple[BindingSelection, ...]) -> None:
    roles = tuple(binding.role for binding in bindings)
    if len(roles) != len(set(roles)):
        raise ValueError("binding roles must be unique")


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require_attempt_runtime_match(
    attempt: ActivationAttempt,
    runtime: LoadedRuntimeConfiguration,
    *,
    revision_id: str,
    fingerprint: str,
    label: str,
) -> None:
    if runtime.canonical_revision_id != revision_id or runtime.semantic_configuration_fingerprint != fingerprint:
        raise ValueError(f"{label} runtime stamp does not match revision and fingerprint")
    if (
        runtime.environment_id != attempt.environment_id
        or runtime.module_key != attempt.module_key
        or runtime.module_instance_id != attempt.module_instance_id
    ):
        raise ValueError(f"{label} runtime stamp does not match activation scope")
