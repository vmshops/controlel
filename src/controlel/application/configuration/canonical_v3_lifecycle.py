"""Editable lifecycle contracts for canonical configuration v3.

Edits are immutable draft revisions.  Canonicalization creates another
immutable canonical revision, and activation remains a separate CAS-protected
authority transition.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from controlel.application.configuration.canonical_defaults import NEW_CONFIGURATION_DEBUG_UNTIL_CHANGED
from controlel.application.configuration.canonical_v3 import (
    CANONICAL_CONFIGURATION_SCHEMA_VERSION_V3,
    CanonicalConfigurationRevisionV3,
    DiagnosticsConfigurationV3,
    HeatingConfigurationV3,
    NotificationsConfigurationV3,
)
from controlel.application.setup.discovery import ReferenceResolutionStatus
from controlel.application.setup.json_data import (
    FrozenJsonMapping,
    ImmutableJsonMapping,
    aware_datetime,
    immutable_json_mapping,
)
from controlel.application.setup.model import (
    ActiveReference,
    CanonicalConfigurationRevision,
    ProviderReference,
)
from controlel.application.setup.repository import SetupConflictError

_HASH_PATTERN = r"^[0-9a-f]{64}$"


class CanonicalDraftRevisionConflict(SetupConflictError):
    """A persisted v3 draft changed before the requested mutation."""


class ConfigurationScopesV3(BaseModel):
    """The three independently-owned semantic configuration scopes."""

    heating: HeatingConfigurationV3
    diagnostics: DiagnosticsConfigurationV3
    notifications: NotificationsConfigurationV3

    model_config = ConfigDict(frozen=True, extra="forbid")


class CanonicalConfigurationDraftV3(BaseModel):
    """One immutable revision of editable v3 intent cloned from authority."""

    schema_version: int = CANONICAL_CONFIGURATION_SCHEMA_VERSION_V3
    draft_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    configuration_id: str = Field(min_length=1)
    base_active_revision_id: str | None = Field(default=None, min_length=1)
    base_active_generation: int = Field(default=0, ge=0)
    canonical_revision: int = Field(default=1, ge=1)
    parent_revision_id: str | None = Field(default=None, min_length=1)
    environment_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provider_instance_id: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime
    heating: HeatingConfigurationV3
    diagnostics: DiagnosticsConfigurationV3
    notifications: NotificationsConfigurationV3
    lineage: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    import_provenance: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    migration_provenance: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("schema_version")
    @classmethod
    def schema_version_must_be_v3(cls, value: int) -> int:
        if value != CANONICAL_CONFIGURATION_SCHEMA_VERSION_V3:
            raise ValueError("canonical configuration draft must use schema v3")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime, info: object) -> datetime:
        return aware_datetime(value, str(getattr(info, "field_name", "timestamp")))

    @field_validator("lineage", "import_provenance", "migration_provenance", mode="after")
    @classmethod
    def provenance_must_be_immutable(cls, value: object, info: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, str(getattr(info, "field_name", "provenance")))

    @model_validator(mode="after")
    def timestamps_are_monotonic(self) -> CanonicalConfigurationDraftV3:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.base_active_revision_id is None and self.base_active_generation != 0:
            raise ValueError("a draft without active authority must use generation zero")
        if self.base_active_revision_id is not None and self.base_active_generation < 1:
            raise ValueError("a draft based on active authority requires a positive generation")
        return self

    @property
    def scopes(self) -> ConfigurationScopesV3:
        return ConfigurationScopesV3(
            heating=self.heating,
            diagnostics=self.diagnostics,
            notifications=self.notifications,
        )

    @property
    def content_fingerprint(self) -> str:
        return self._semantic_revision().semantic_configuration_fingerprint

    def next_revision(
        self,
        *,
        expected_revision: int,
        updated_at: datetime,
        scopes: ConfigurationScopesV3,
    ) -> CanonicalConfigurationDraftV3:
        if self.revision != expected_revision:
            raise CanonicalDraftRevisionConflict(
                f"canonical v3 draft changed before update: expected {expected_revision}, found {self.revision}"
            )
        values = self.model_dump(mode="python")
        values.update(
            {
                "revision": self.revision + 1,
                "updated_at": aware_datetime(updated_at, "updated_at"),
                "heating": scopes.heating,
                "diagnostics": scopes.diagnostics,
                "notifications": scopes.notifications,
            }
        )
        return CanonicalConfigurationDraftV3.model_validate(values)

    def _semantic_revision(self) -> CanonicalConfigurationRevisionV3:
        """Materialize identity-neutral metadata solely to reuse v3 hashing."""

        return CanonicalConfigurationRevisionV3(
            configuration_id=self.configuration_id,
            revision_id="draft-semantic-projection",
            revision=1,
            environment_id=self.environment_id,
            provider=self.provider,
            provider_instance_id=self.provider_instance_id,
            created_at=self.created_at,
            actor="system:draft-fingerprint",
            source="canonical_v3_draft",
            change_kind="DRAFT",
            reason="calculate_semantic_configuration_fingerprint",
            core_version="draft",
            heating=self.heating,
            diagnostics=self.diagnostics,
            notifications=self.notifications,
        )


class CanonicalReferenceHealthV3(BaseModel):
    """Current provider evidence for one persisted reference; never a mutation."""

    canonical_path: str = Field(min_length=1)
    activation_required: bool
    reference: ProviderReference
    status: ReferenceResolutionStatus
    reason_code: str = Field(min_length=1)
    resolved_reference: ProviderReference | None = None
    evidence: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("evidence", mode="after")
    @classmethod
    def evidence_must_be_immutable(cls, value: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, "reference health evidence")

    @property
    def runtime_ready(self) -> bool:
        return self.status in {ReferenceResolutionStatus.RESOLVED, ReferenceResolutionStatus.EPHEMERAL}


@dataclass(frozen=True, slots=True)
class CanonicalReferenceBindingV3:
    canonical_path: str
    activation_required: bool
    reference: ProviderReference


def canonical_reference_bindings_v3(
    configuration: CanonicalConfigurationRevisionV3 | CanonicalConfigurationDraftV3,
) -> tuple[CanonicalReferenceBindingV3, ...]:
    """List every persisted provider reference with its runtime significance."""

    result: list[CanonicalReferenceBindingV3] = []
    for zone_index, zone in enumerate(configuration.heating.zones):
        prefix = f"heating.zones[{zone_index}]"
        if zone.topology.area_reference is not None:
            result.append(
                CanonicalReferenceBindingV3(
                    f"{prefix}.topology.area_reference",
                    False,
                    zone.topology.area_reference,
                )
            )
        if zone.topology.floor_reference is not None:
            result.append(
                CanonicalReferenceBindingV3(
                    f"{prefix}.topology.floor_reference",
                    False,
                    zone.topology.floor_reference,
                )
            )
        result.append(
            CanonicalReferenceBindingV3(
                f"{prefix}.primary_temperature_sensor.provider_reference",
                True,
                zone.primary_temperature_sensor.provider_reference,
            )
        )
    for source_index, source in enumerate(configuration.heating.heat_sources):
        prefix = f"heating.heat_sources[{source_index}]"
        if source.provider_reference is not None:
            result.append(
                CanonicalReferenceBindingV3(
                    f"{prefix}.provider_reference",
                    False,
                    source.provider_reference,
                )
            )
        result.extend(
            (
                CanonicalReferenceBindingV3(
                    f"{prefix}.command_strategy.enable_permission.command_target_reference",
                    True,
                    source.command_strategy.enable_permission.command_target_reference,
                ),
                CanonicalReferenceBindingV3(
                    f"{prefix}.command_strategy.disable_permission.command_target_reference",
                    True,
                    source.command_strategy.disable_permission.command_target_reference,
                ),
            )
        )
        if source.observations.reported_actuator_state_reference is not None:
            result.append(
                CanonicalReferenceBindingV3(
                    f"{prefix}.observations.reported_actuator_state_reference",
                    True,
                    source.observations.reported_actuator_state_reference,
                )
            )
        if source.observations.physical_operation_reference is not None:
            result.append(
                CanonicalReferenceBindingV3(
                    f"{prefix}.observations.physical_operation_reference",
                    False,
                    source.observations.physical_operation_reference,
                )
            )
    for delivery_index, delivery in enumerate(configuration.heating.heat_delivery):
        if delivery.actuator_reference is not None:
            result.append(
                CanonicalReferenceBindingV3(
                    f"heating.heat_delivery[{delivery_index}].actuator_reference",
                    True,
                    delivery.actuator_reference,
                )
            )
    return tuple(result)


class CanonicalConfigurationValidationV3(BaseModel):
    """Assessment of exactly one immutable draft revision."""

    report_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)
    draft_revision: int = Field(ge=1)
    draft_fingerprint: str = Field(pattern=_HASH_PATTERN)
    evaluated_at: datetime
    reference_health: tuple[CanonicalReferenceHealthV3, ...]
    activation_ready: bool
    issue_codes: tuple[str, ...] = ()

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_must_be_aware(cls, value: datetime) -> datetime:
        return aware_datetime(value, "evaluated_at")

    @field_validator("issue_codes", mode="after")
    @classmethod
    def issue_codes_are_deterministic(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def readiness_has_no_unresolved_required_reference(self) -> CanonicalConfigurationValidationV3:
        if self.activation_ready and any(
            item.activation_required and not item.runtime_ready for item in self.reference_health
        ):
            raise ValueError("activation-ready v3 validation contains an unresolved runtime reference")
        return self

    def assesses(self, draft: CanonicalConfigurationDraftV3) -> bool:
        return (
            self.draft_id == draft.draft_id
            and self.draft_revision == draft.revision
            and self.draft_fingerprint == draft.content_fingerprint
        )


class ActiveCanonicalConfigurationV3(BaseModel):
    """Exact active authority plus editing and runtime evidence."""

    active_reference: ActiveReference
    canonical_revision: CanonicalConfigurationRevisionV3
    configuration_scopes: ConfigurationScopesV3
    provenance: ImmutableJsonMapping
    reference_health: tuple[CanonicalReferenceHealthV3, ...]
    runtime_evidence: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("provenance", "runtime_evidence", mode="after")
    @classmethod
    def mappings_must_be_immutable(cls, value: object, info: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, str(getattr(info, "field_name", "evidence")))

    @model_validator(mode="after")
    def authority_identity_must_match(self) -> ActiveCanonicalConfigurationV3:
        revision = self.canonical_revision
        active = self.active_reference
        if active.scope_key != revision.scope_key:
            raise ValueError("active reference scope does not match canonical v3 revision")
        if active.canonical_revision_id != revision.revision_id:
            raise ValueError("active reference does not select the returned canonical v3 revision")
        if active.semantic_configuration_fingerprint != revision.semantic_configuration_fingerprint:
            raise ValueError("active reference fingerprint does not match canonical v3 revision")
        if self.configuration_scopes != ConfigurationScopesV3(
            heating=revision.heating,
            diagnostics=revision.diagnostics,
            notifications=revision.notifications,
        ):
            raise ValueError("active configuration scopes do not match the canonical v3 revision")
        return self


class CanonicalConfigurationRepositoryV3(Protocol):
    async def get_active_reference(self, scope: tuple[str, str, str]) -> ActiveReference | None: ...

    async def get_canonical_revision(
        self,
        revision_id: str,
    ) -> CanonicalConfigurationRevision | CanonicalConfigurationRevisionV3: ...

    async def get_canonical_revision_v3(self, revision_id: str) -> CanonicalConfigurationRevisionV3: ...

    async def add_canonical_revision_v3(self, revision: CanonicalConfigurationRevisionV3) -> None: ...

    async def save_canonical_draft_v3(self, draft: CanonicalConfigurationDraftV3) -> None: ...

    async def get_canonical_draft_v3(self, draft_id: str) -> CanonicalConfigurationDraftV3: ...

    async def list_canonical_drafts_v3(self) -> tuple[CanonicalConfigurationDraftV3, ...]: ...

    async def delete_canonical_draft_v3(self, draft_id: str, *, expected_revision: int) -> None: ...

    async def save_canonical_validation_v3(self, report: CanonicalConfigurationValidationV3) -> None: ...

    async def get_canonical_validation_v3(self, report_id: str) -> CanonicalConfigurationValidationV3: ...


class CanonicalConfigurationLifecycleV3:
    """Frontend-neutral clone/edit/validate/canonicalize lifecycle."""

    def __init__(self, repository: CanonicalConfigurationRepositoryV3) -> None:
        self._repository = repository

    async def reopen_draft(self, draft_id: str) -> CanonicalConfigurationDraftV3:
        """Return the exact latest persisted revision of one v3 draft."""

        return await self._repository.get_canonical_draft_v3(draft_id)

    async def list_drafts(self) -> tuple[CanonicalConfigurationDraftV3, ...]:
        """List each persisted v3 draft at its latest immutable revision."""

        return await self._repository.list_canonical_drafts_v3()

    async def abandon_draft(self, draft_id: str, *, expected_revision: int) -> None:
        """Delete only editable draft state, never canonical or active authority."""

        await self._repository.delete_canonical_draft_v3(
            draft_id,
            expected_revision=expected_revision,
        )

    async def read_active(
        self,
        scope: tuple[str, str, str],
        *,
        reference_health: tuple[CanonicalReferenceHealthV3, ...] = (),
        runtime_evidence: Mapping[str, object] | None = None,
    ) -> ActiveCanonicalConfigurationV3:
        active = await self._repository.get_active_reference(scope)
        if active is None:
            raise SetupConflictError("canonical v3 configuration scope has no active revision")
        revision = await self._repository.get_canonical_revision_v3(active.canonical_revision_id)
        _require_active_revision_v3(active, revision)
        return ActiveCanonicalConfigurationV3(
            active_reference=active,
            canonical_revision=revision,
            configuration_scopes=ConfigurationScopesV3(
                heating=revision.heating,
                diagnostics=revision.diagnostics,
                notifications=revision.notifications,
            ),
            provenance={
                "actor": revision.actor,
                "source": revision.source,
                "change_kind": revision.change_kind,
                "reason": revision.reason,
                "created_at": revision.created_at,
                "parent_revision_id": revision.parent_revision_id,
                "lineage": revision.lineage,
                "import_provenance": revision.import_provenance,
                "migration_provenance": revision.migration_provenance,
            },
            reference_health=reference_health,
            runtime_evidence=runtime_evidence or {},
        )

    async def clone_active_to_draft(
        self,
        scope: tuple[str, str, str],
        *,
        draft_id: str,
        created_at: datetime,
        expected_active_generation: int,
    ) -> CanonicalConfigurationDraftV3:
        active = await self._repository.get_active_reference(scope)
        if active is None:
            raise SetupConflictError("cannot edit canonical v3 configuration without an active revision")
        if active.generation != expected_active_generation:
            raise SetupConflictError("active generation changed before canonical v3 edit started")
        revision = await self._repository.get_canonical_revision_v3(active.canonical_revision_id)
        _require_active_revision_v3(active, revision)
        draft = CanonicalConfigurationDraftV3(
            draft_id=draft_id,
            revision=1,
            configuration_id=revision.configuration_id,
            base_active_revision_id=revision.revision_id,
            base_active_generation=active.generation,
            canonical_revision=revision.revision + 1,
            parent_revision_id=revision.revision_id,
            environment_id=revision.environment_id,
            provider=revision.provider,
            provider_instance_id=revision.provider_instance_id,
            created_at=created_at,
            updated_at=created_at,
            heating=revision.heating,
            diagnostics=revision.diagnostics,
            notifications=revision.notifications,
            lineage=revision.lineage,
            import_provenance=revision.import_provenance,
            migration_provenance=revision.migration_provenance,
        )
        await self._repository.save_canonical_draft_v3(draft)
        return draft

    async def start_greenfield_draft(
        self,
        *,
        draft_id: str,
        configuration_id: str,
        environment_id: str,
        provider: str,
        provider_instance_id: str,
        created_at: datetime,
        scopes: ConfigurationScopesV3,
    ) -> CanonicalConfigurationDraftV3:
        """Persist the first editable v3 authority candidate without activation."""

        _require_new_v1_deferred_defaults(scopes)
        scope = (environment_id, "heating", configuration_id)
        if await self._repository.get_active_reference(scope) is not None:
            raise SetupConflictError("greenfield canonical v3 scope already has active authority")
        draft = CanonicalConfigurationDraftV3(
            draft_id=draft_id,
            revision=1,
            configuration_id=configuration_id,
            base_active_revision_id=None,
            base_active_generation=0,
            canonical_revision=1,
            parent_revision_id=None,
            environment_id=environment_id,
            provider=provider,
            provider_instance_id=provider_instance_id,
            created_at=created_at,
            updated_at=created_at,
            heating=scopes.heating,
            diagnostics=scopes.diagnostics,
            notifications=scopes.notifications,
            lineage={"authoring_origin": "greenfield_v3"},
        )
        await self._repository.save_canonical_draft_v3(draft)
        return draft

    async def start_conversion_draft(
        self,
        projection: CanonicalConfigurationRevisionV3,
        *,
        draft_id: str,
        created_at: datetime,
        expected_active_revision_id: str | None,
        expected_active_generation: int,
    ) -> CanonicalConfigurationDraftV3:
        """Persist a deterministic migrated projection as an inactive v3 draft."""

        scope = projection.scope_key
        active = await self._repository.get_active_reference(scope)
        active_revision_id = None if active is None else active.canonical_revision_id
        active_generation = 0 if active is None else active.generation
        if active_revision_id != expected_active_revision_id or active_generation != expected_active_generation:
            raise SetupConflictError("active authority changed before canonical v3 conversion")
        if expected_active_revision_id is not None and projection.parent_revision_id != expected_active_revision_id:
            raise SetupConflictError("canonical v3 conversion parent does not match active authority")
        draft = CanonicalConfigurationDraftV3(
            draft_id=draft_id,
            revision=1,
            configuration_id=projection.configuration_id,
            base_active_revision_id=expected_active_revision_id,
            base_active_generation=expected_active_generation,
            canonical_revision=projection.revision,
            parent_revision_id=projection.parent_revision_id,
            environment_id=projection.environment_id,
            provider=projection.provider,
            provider_instance_id=projection.provider_instance_id,
            created_at=created_at,
            updated_at=created_at,
            heating=projection.heating,
            diagnostics=projection.diagnostics,
            notifications=projection.notifications,
            lineage={
                **dict(projection.lineage),
                "authoring_origin": "canonical_v2_conversion",
                "conversion_projection_revision_id": projection.revision_id,
            },
            import_provenance=projection.import_provenance,
            migration_provenance=projection.migration_provenance,
        )
        await self._repository.save_canonical_draft_v3(draft)
        return draft

    async def update_draft(
        self,
        draft_id: str,
        *,
        expected_revision: int,
        updated_at: datetime,
        scopes: ConfigurationScopesV3,
    ) -> CanonicalConfigurationDraftV3:
        current = await self._repository.get_canonical_draft_v3(draft_id)
        _require_deferred_fields_unchanged(current.scopes, scopes)
        updated = current.next_revision(
            expected_revision=expected_revision,
            updated_at=updated_at,
            scopes=scopes,
        )
        await self._repository.save_canonical_draft_v3(updated)
        return updated

    async def validate_draft(
        self,
        draft_id: str,
        *,
        report_id: str,
        evaluated_at: datetime,
        reference_health: tuple[CanonicalReferenceHealthV3, ...],
    ) -> CanonicalConfigurationValidationV3:
        draft = await self._repository.get_canonical_draft_v3(draft_id)
        _require_complete_reference_health(draft, reference_health)
        unresolved = tuple(item for item in reference_health if item.activation_required and not item.runtime_ready)
        report = CanonicalConfigurationValidationV3(
            report_id=report_id,
            draft_id=draft.draft_id,
            draft_revision=draft.revision,
            draft_fingerprint=draft.content_fingerprint,
            evaluated_at=evaluated_at,
            reference_health=reference_health,
            activation_ready=not unresolved,
            issue_codes=tuple(f"canonical_v3.reference.{item.status.value.lower()}" for item in unresolved),
        )
        await self._repository.save_canonical_validation_v3(report)
        return report

    async def canonicalize_draft(
        self,
        draft_id: str,
        *,
        validation_report_id: str,
        revision_id: str,
        created_at: datetime,
        actor: str,
        source: str,
        change_kind: str,
        reason: str,
        core_version: str,
        fresh_reference_health: tuple[CanonicalReferenceHealthV3, ...],
        integration_version: str | None = None,
    ) -> CanonicalConfigurationRevisionV3:
        draft = await self._repository.get_canonical_draft_v3(draft_id)
        report = await self._repository.get_canonical_validation_v3(validation_report_id)
        if not report.assesses(draft):
            raise SetupConflictError("canonical v3 validation does not assess the current draft revision")
        if not report.activation_ready:
            raise SetupConflictError("canonical v3 draft is not activation-ready")
        _require_complete_reference_health(draft, fresh_reference_health)
        unresolved = tuple(
            item for item in fresh_reference_health if item.activation_required and not item.runtime_ready
        )
        if unresolved:
            issue_codes = ", ".join(
                sorted({f"canonical_v3.reference.{item.status.value.lower()}" for item in unresolved})
            )
            raise SetupConflictError(f"canonical v3 reference health changed before canonicalization: {issue_codes}")
        scope = (draft.environment_id, "heating", draft.configuration_id)
        active = await self._repository.get_active_reference(scope)
        active_revision_id = None if active is None else active.canonical_revision_id
        active_generation = 0 if active is None else active.generation
        if active_revision_id != draft.base_active_revision_id or active_generation != draft.base_active_generation:
            raise SetupConflictError("active canonical v3 authority changed while the draft was edited")
        canonical_revision = draft.canonical_revision
        parent_revision_id = draft.parent_revision_id
        if active is not None:
            base = await self._repository.get_canonical_revision(active.canonical_revision_id)
            if isinstance(base, CanonicalConfigurationRevisionV3):
                _require_active_revision_v3(active, base)
                if (
                    draft.configuration_id != base.configuration_id
                    or draft.environment_id != base.environment_id
                    or draft.provider != base.provider
                    or draft.provider_instance_id != base.provider_instance_id
                ):
                    raise SetupConflictError("canonical v3 draft identity does not match its base active revision")
            elif (
                active.scope_key != (base.environment_id, base.module_key, base.module_instance_id)
                or active.semantic_configuration_fingerprint != base.semantic_configuration_fingerprint
                or draft.lineage.get("authoring_origin") != "canonical_v2_conversion"
                or draft.environment_id != base.environment_id
                or draft.provider != base.provider
                or draft.provider_instance_id != base.provider_instance_id
            ):
                raise SetupConflictError("canonical v3 conversion draft does not match its active v2 authority")
            canonical_revision = base.revision + 1
            parent_revision_id = base.revision_id
        canonical = CanonicalConfigurationRevisionV3(
            configuration_id=draft.configuration_id,
            revision_id=revision_id,
            revision=canonical_revision,
            parent_revision_id=parent_revision_id,
            environment_id=draft.environment_id,
            provider=draft.provider,
            provider_instance_id=draft.provider_instance_id,
            created_at=created_at,
            actor=actor,
            source=source,
            change_kind=change_kind,
            reason=reason,
            core_version=core_version,
            integration_version=integration_version,
            heating=draft.heating,
            diagnostics=draft.diagnostics,
            notifications=draft.notifications,
            lineage={
                **dict(draft.lineage),
                "draft_id": draft.draft_id,
                "draft_revision": draft.revision,
                "base_active_revision_id": draft.base_active_revision_id,
                "base_active_generation": draft.base_active_generation,
            },
            import_provenance=draft.import_provenance,
            migration_provenance=draft.migration_provenance,
        )
        await self._repository.add_canonical_revision_v3(canonical)
        return canonical


def _require_complete_reference_health(
    configuration: CanonicalConfigurationDraftV3,
    reference_health: tuple[CanonicalReferenceHealthV3, ...],
) -> None:
    expected = {item.canonical_path: item for item in canonical_reference_bindings_v3(configuration)}
    actual = {item.canonical_path: item for item in reference_health}
    if len(actual) != len(reference_health):
        raise SetupConflictError("canonical v3 reference health contains duplicate paths")
    if set(actual) != set(expected):
        raise SetupConflictError("canonical v3 reference health does not cover the current draft bindings")
    for path, binding in expected.items():
        health = actual[path]
        if (
            health.activation_required != binding.activation_required
            or health.reference.semantic_data() != binding.reference.semantic_data()
        ):
            raise SetupConflictError(f"canonical v3 reference health does not assess current binding: {path}")


def _require_new_v1_deferred_defaults(scopes: ConfigurationScopesV3) -> None:
    source = scopes.heating.heat_sources[0]
    if source.observations.physical_operation_reference is not None:
        raise SetupConflictError(
            "physical heat-source operation evidence is deferred and cannot be authored in Single-Zone Heating v1"
        )
    if scopes.diagnostics.debug_policy.until_changed is not NEW_CONFIGURATION_DEBUG_UNTIL_CHANGED:
        raise SetupConflictError(
            "until-changed Debug policy is deferred and cannot be authored in Single-Zone Heating v1"
        )


def _require_deferred_fields_unchanged(
    current: ConfigurationScopesV3,
    proposed: ConfigurationScopesV3,
) -> None:
    current_physical = current.heating.heat_sources[0].observations.physical_operation_reference
    proposed_physical = proposed.heating.heat_sources[0].observations.physical_operation_reference
    if current_physical != proposed_physical:
        raise SetupConflictError(
            "physical heat-source operation evidence is deferred and cannot be edited in Single-Zone Heating v1"
        )
    if current.diagnostics.debug_policy.until_changed != proposed.diagnostics.debug_policy.until_changed:
        raise SetupConflictError(
            "until-changed Debug policy is deferred and cannot be edited in Single-Zone Heating v1"
        )


def _require_active_revision_v3(
    active: ActiveReference,
    revision: CanonicalConfigurationRevisionV3,
) -> None:
    if active.scope_key != revision.scope_key:
        raise SetupConflictError("active reference scope does not match canonical v3 revision")
    if active.canonical_revision_id != revision.revision_id:
        raise SetupConflictError("active reference does not select the canonical v3 revision")
    if active.semantic_configuration_fingerprint != revision.semantic_configuration_fingerprint:
        raise SetupConflictError("active reference fingerprint does not match canonical v3 revision")
