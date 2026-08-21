"""Frontend-neutral Home Assistant host workflow for Heating Setup v0.1."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from controlel.application.configuration.heating_setup_adapter import (
    HeatingRecommendationSet,
    HeatingRoleRecommendation,
    HeatingSetupAdapter,
    HeatingSetupCandidate,
)
from controlel.application.setup import (
    BindingSelection,
    CanonicalConfigurationRevision,
    DiscoverySnapshot,
    DraftRevision,
    SetupConflictError,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from controlel.application.setup.json_data import (
    FrozenJsonMapping,
    ImmutableJsonMapping,
    immutable_json_mapping,
)
from controlel.infrastructure.home_assistant.setup_discovery import HomeAssistantReferenceResolver
from controlel.infrastructure.home_assistant.setup_persistence import HomeAssistantSetupRepository


class DiscoverySnapshotLoader(Protocol):
    def __call__(self, snapshot_id: str, captured_at: datetime) -> Awaitable[DiscoverySnapshot]: ...


class SetupValidationStatus(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    NOT_VALIDATED = "NOT_VALIDATED"


class LegacyConfigurationStatusDTO(BaseModel):
    present: bool
    conversion_available: bool = False
    silently_merged: bool = False
    reason_code: str | None = None

    model_config = ConfigDict(frozen=True, extra="forbid")


class HeatingBindingSelectionRequest(BaseModel):
    role: str = Field(min_length=1)
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    user_confirmed: bool = False

    model_config = ConfigDict(frozen=True, extra="forbid")


class DiscoveredObjectDTO(BaseModel):
    object_kind: str
    native_id: str | None
    current_locator: str | None
    identity_quality: str
    device_registry_id: str | None
    area_id: str | None
    floor_id: str | None

    model_config = ConfigDict(frozen=True, extra="forbid")


class DiscoverySnapshotDTO(BaseModel):
    snapshot_id: str
    provider: str
    provider_instance_id: str
    captured_at: datetime
    content_fingerprint: str
    object_counts: ImmutableJsonMapping
    objects: tuple[DiscoveredObjectDTO, ...]

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("object_counts", mode="after")
    @classmethod
    def counts_must_be_immutable(cls, value: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, "discovery object counts")


class HeatingCandidateDTO(BaseModel):
    candidate_id: str
    role: str
    native_id: str | None
    current_locator: str | None
    identity_quality: str
    area_id: str | None
    floor_id: str | None
    capabilities: tuple[str, ...]
    confidence: str
    reason_codes: tuple[str, ...]
    evidence: ImmutableJsonMapping

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("evidence", mode="after")
    @classmethod
    def evidence_must_be_immutable(cls, value: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, "candidate evidence")


class HeatingRoleRecommendationDTO(BaseModel):
    role: str
    recommended: HeatingCandidateDTO | None
    alternatives: tuple[HeatingCandidateDTO, ...]
    explicit_confirmation_required: bool

    model_config = ConfigDict(frozen=True, extra="forbid")


class HeatingBindingSelectionDTO(BaseModel):
    role: str
    native_id: str | None
    current_locator: str | None
    identity_quality: str
    candidate_id: str | None
    user_confirmed: bool
    selection_origin: str
    resolution_status: str

    model_config = ConfigDict(frozen=True, extra="forbid")


class ValidationIssueDTO(BaseModel):
    code: str
    severity: str
    path: tuple[str, ...]
    module_role: str | None
    message_key: str
    parameters: ImmutableJsonMapping
    evidence: ImmutableJsonMapping
    suggested_action: str | None

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("parameters", "evidence", mode="after")
    @classmethod
    def mappings_must_be_immutable(cls, value: object, info: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, str(getattr(info, "field_name", "mapping")))


class HeatingSetupSessionDTO(BaseModel):
    draft_id: str
    draft_revision: int
    module_instance_id: str
    incomplete: bool
    activation_ready: bool
    validation_status: SetupValidationStatus
    validation_report_id: str | None
    blocking_issue_count: int
    warning_count: int
    settings: ImmutableJsonMapping
    selections: tuple[HeatingBindingSelectionDTO, ...]
    recommendations: tuple[HeatingRoleRecommendationDTO, ...]
    validation_issues: tuple[ValidationIssueDTO, ...]
    discovery: DiscoverySnapshotDTO
    canonical_revision_id: str | None = None
    active_revision_id: str | None = None
    legacy_configuration: LegacyConfigurationStatusDTO

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("settings", mode="after")
    @classmethod
    def settings_must_be_immutable(cls, value: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, "frontend draft settings")


class HeatingSetupHostService:
    """One resumable, non-activating Heating setup workflow over HA snapshots."""

    def __init__(
        self,
        repository: HomeAssistantSetupRepository,
        snapshot_loader: DiscoverySnapshotLoader,
        *,
        legacy_configuration: LegacyConfigurationStatusDTO | None = None,
    ) -> None:
        self._repository = repository
        self._snapshot_loader = snapshot_loader
        self._adapter = HeatingSetupAdapter()
        self._resolver = HomeAssistantReferenceResolver()
        self._legacy_configuration = legacy_configuration or LegacyConfigurationStatusDTO(present=False)

    async def get_discovery_snapshot(self, *, snapshot_id: str, captured_at: datetime) -> DiscoverySnapshotDTO:
        return _discovery_dto(await self._snapshot_loader(snapshot_id, captured_at))

    async def get_recommendations(
        self,
        *,
        snapshot_id: str,
        captured_at: datetime,
        preferred_area_id: str | None = None,
        preferred_floor_id: str | None = None,
    ) -> tuple[HeatingRoleRecommendationDTO, ...]:
        snapshot = await self._snapshot_loader(snapshot_id, captured_at)
        recommendations = self._adapter.recommend(
            snapshot,
            preferred_area_id=preferred_area_id,
            preferred_floor_id=preferred_floor_id,
        )
        return _recommendations_dto(recommendations)

    async def start_new_heating_setup(
        self,
        *,
        draft_id: str,
        module_instance_id: str,
        created_at: datetime,
        snapshot_id: str,
        report_id: str,
        settings: Mapping[str, object] | None = None,
        selections: tuple[HeatingBindingSelectionRequest, ...] = (),
        preferred_area_id: str | None = None,
        preferred_floor_id: str | None = None,
        base_active_revision_id: str | None = None,
    ) -> HeatingSetupSessionDTO:
        snapshot, recommendations = await self._discover_and_recommend(
            snapshot_id,
            created_at,
            preferred_area_id,
            preferred_floor_id,
        )
        selected, confirmed = _selection_request_maps(selections)
        draft = self._adapter.create_draft_from_recommendations(
            recommendations,
            selected_candidate_ids=selected,
            explicitly_confirmed_roles=confirmed,
            draft_id=draft_id,
            environment_id=snapshot.provider_instance_id,
            module_instance_id=module_instance_id,
            created_at=created_at,
            settings=settings or {},
            base_active_revision_id=base_active_revision_id,
        )
        await self._repository.save_draft(draft)
        report = self._validate(draft, snapshot, report_id=report_id, evaluated_at=created_at)
        await self._repository.save_validation_report(report)
        return await self._session(draft, snapshot, recommendations, report)

    async def reopen_heating_setup(
        self,
        draft_id: str,
        *,
        snapshot_id: str,
        captured_at: datetime,
        preferred_area_id: str | None = None,
        preferred_floor_id: str | None = None,
    ) -> HeatingSetupSessionDTO:
        draft = await self._repository.get_draft(draft_id)
        snapshot, recommendations = await self._discover_and_recommend(
            snapshot_id,
            captured_at,
            preferred_area_id,
            preferred_floor_id,
        )
        report = await self._repository.get_latest_validation_report(draft_id)
        return await self._session(draft, snapshot, recommendations, report)

    async def update_heating_draft(
        self,
        draft_id: str,
        *,
        expected_revision: int,
        updated_at: datetime,
        snapshot_id: str,
        report_id: str,
        settings: Mapping[str, object],
        selections: tuple[HeatingBindingSelectionRequest, ...],
        preferred_area_id: str | None = None,
        preferred_floor_id: str | None = None,
    ) -> HeatingSetupSessionDTO:
        current = await self._repository.get_draft(draft_id)
        if current.revision != expected_revision:
            raise SetupConflictError(
                f"draft changed before update: expected {expected_revision}, found {current.revision}"
            )
        snapshot, recommendations = await self._discover_and_recommend(
            snapshot_id,
            updated_at,
            preferred_area_id,
            preferred_floor_id,
        )
        selected, confirmed = _selection_request_maps(selections)
        materialized = self._adapter.create_draft_from_recommendations(
            recommendations,
            selected_candidate_ids=selected,
            explicitly_confirmed_roles=confirmed,
            draft_id=current.draft_id,
            environment_id=current.environment_id,
            module_instance_id=current.module_instance_id,
            created_at=current.created_at,
            settings=settings,
            base_active_revision_id=current.base_active_revision_id,
        )
        updated = current.next_revision(
            updated_at=updated_at,
            settings=settings,
            bindings=materialized.bindings,
        )
        await self._repository.save_draft(updated)
        report = self._validate(updated, snapshot, report_id=report_id, evaluated_at=updated_at)
        await self._repository.save_validation_report(report)
        return await self._session(updated, snapshot, recommendations, report)

    async def validate_heating_draft(
        self,
        draft_id: str,
        *,
        snapshot_id: str,
        evaluated_at: datetime,
        report_id: str,
        preferred_area_id: str | None = None,
        preferred_floor_id: str | None = None,
    ) -> HeatingSetupSessionDTO:
        draft = await self._repository.get_draft(draft_id)
        snapshot, recommendations = await self._discover_and_recommend(
            snapshot_id,
            evaluated_at,
            preferred_area_id,
            preferred_floor_id,
        )
        report = self._validate(draft, snapshot, report_id=report_id, evaluated_at=evaluated_at)
        await self._repository.save_validation_report(report)
        return await self._session(draft, snapshot, recommendations, report)

    async def canonicalize_heating_draft(
        self,
        draft_id: str,
        *,
        snapshot_id: str,
        created_at: datetime,
        validation_report_id: str,
        configuration_id: str,
        revision_id: str,
        revision: int,
        actor: str,
        source: str,
        change_kind: str,
        reason: str,
        core_version: str,
        integration_version: str | None = None,
        parent_revision_id: str | None = None,
        preferred_area_id: str | None = None,
        preferred_floor_id: str | None = None,
    ) -> HeatingSetupSessionDTO:
        draft = await self._repository.get_draft(draft_id)
        snapshot, recommendations = await self._discover_and_recommend(
            snapshot_id,
            created_at,
            preferred_area_id,
            preferred_floor_id,
        )
        report = self._validate(
            draft,
            snapshot,
            report_id=validation_report_id,
            evaluated_at=created_at,
        )
        await self._repository.save_validation_report(report)
        canonical = self._adapter.canonicalize(
            draft,
            report,
            configuration_id=configuration_id,
            revision_id=revision_id,
            revision=revision,
            provider=snapshot.provider,
            provider_instance_id=snapshot.provider_instance_id,
            created_at=created_at,
            actor=actor,
            source=source,
            change_kind=change_kind,
            reason=reason,
            core_version=core_version,
            integration_version=integration_version,
            parent_revision_id=parent_revision_id,
        )
        await self._repository.add_canonical_revision(canonical)
        return await self._session(
            draft,
            snapshot,
            recommendations,
            report,
            canonical_revision=canonical,
        )

    async def _discover_and_recommend(
        self,
        snapshot_id: str,
        captured_at: datetime,
        preferred_area_id: str | None,
        preferred_floor_id: str | None,
    ) -> tuple[DiscoverySnapshot, HeatingRecommendationSet]:
        snapshot = await self._snapshot_loader(snapshot_id, captured_at)
        recommendations = self._adapter.recommend(
            snapshot,
            preferred_area_id=preferred_area_id,
            preferred_floor_id=preferred_floor_id,
        )
        return snapshot, recommendations

    def _validate(
        self,
        draft: DraftRevision,
        snapshot: DiscoverySnapshot,
        *,
        report_id: str,
        evaluated_at: datetime,
    ) -> ValidationReport:
        return self._adapter.validate(
            draft,
            report_id=report_id,
            evaluated_at=evaluated_at,
            discovery_snapshot=snapshot,
            reference_resolver=self._resolver,
            resolution_generation=draft.revision,
        )

    async def _session(
        self,
        draft: DraftRevision,
        snapshot: DiscoverySnapshot,
        recommendations: HeatingRecommendationSet,
        report: ValidationReport | None,
        *,
        canonical_revision: CanonicalConfigurationRevision | None = None,
    ) -> HeatingSetupSessionDTO:
        report_current = report is not None and report.assesses(draft)
        snapshot_current = (
            report is not None and report.assesses(draft) and report.discovery_snapshot_id == snapshot.snapshot_id
        )
        if report is None:
            validation_status = SetupValidationStatus.NOT_VALIDATED
        elif report_current and snapshot_current:
            validation_status = SetupValidationStatus.CURRENT
        else:
            validation_status = SetupValidationStatus.STALE
        issues = report.issues if report is not None else ()
        blocking_count = sum(issue.severity is ValidationSeverity.ERROR for issue in issues)
        warning_count = sum(issue.severity is ValidationSeverity.WARNING for issue in issues)
        activation_ready = bool(
            report is not None and validation_status is SetupValidationStatus.CURRENT and report.activation_ready
        )
        incomplete = report is None or any(
            issue.code == "heating.required_binding_missing"
            or (issue.code == "heating.invalid_setting" and issue.parameters.get("error_type") == "missing")
            for issue in issues
        )
        active = await self._repository.get_active_reference(
            (draft.environment_id, draft.module_key, draft.module_instance_id)
        )
        return HeatingSetupSessionDTO(
            draft_id=draft.draft_id,
            draft_revision=draft.revision,
            module_instance_id=draft.module_instance_id,
            incomplete=incomplete,
            activation_ready=activation_ready,
            validation_status=validation_status,
            validation_report_id=None if report is None else report.report_id,
            blocking_issue_count=blocking_count,
            warning_count=warning_count,
            settings=dict(draft.settings),
            selections=tuple(
                _selection_dto(binding, snapshot, self._resolver)
                for binding in sorted(draft.bindings, key=lambda item: item.role)
            ),
            recommendations=_recommendations_dto(recommendations),
            validation_issues=tuple(_validation_issue_dto(issue) for issue in issues),
            discovery=_discovery_dto(snapshot),
            canonical_revision_id=None if canonical_revision is None else canonical_revision.revision_id,
            active_revision_id=None if active is None else active.canonical_revision_id,
            legacy_configuration=self._legacy_configuration,
        )


def _selection_request_maps(
    selections: tuple[HeatingBindingSelectionRequest, ...],
) -> tuple[dict[str, str], frozenset[str]]:
    roles = tuple(selection.role for selection in selections)
    if len(roles) != len(set(roles)):
        raise ValueError("Heating draft update contains duplicate roles")
    return (
        {selection.role: selection.candidate_id for selection in selections},
        frozenset(selection.role for selection in selections if selection.user_confirmed),
    )


def _candidate_dto(candidate: HeatingSetupCandidate) -> HeatingCandidateDTO:
    reference = candidate.reference
    return HeatingCandidateDTO(
        candidate_id=candidate.candidate_id,
        role=candidate.role,
        native_id=reference.native_id,
        current_locator=reference.current_locator,
        identity_quality=reference.identity_quality.value,
        area_id=reference.area_id,
        floor_id=reference.floor_id,
        capabilities=candidate.capabilities,
        confidence=candidate.confidence.value,
        reason_codes=candidate.reason_codes,
        evidence=dict(candidate.evidence),
    )


def _recommendation_dto(recommendation: HeatingRoleRecommendation) -> HeatingRoleRecommendationDTO:
    return HeatingRoleRecommendationDTO(
        role=recommendation.role,
        recommended=(
            None
            if recommendation.recommended_candidate is None
            else _candidate_dto(recommendation.recommended_candidate)
        ),
        alternatives=tuple(_candidate_dto(item) for item in recommendation.alternatives),
        explicit_confirmation_required=recommendation.explicit_confirmation_required,
    )


def _recommendations_dto(recommendations: HeatingRecommendationSet) -> tuple[HeatingRoleRecommendationDTO, ...]:
    return tuple(_recommendation_dto(item) for item in recommendations.recommendations)


def _selection_dto(
    binding: BindingSelection,
    snapshot: DiscoverySnapshot,
    resolver: HomeAssistantReferenceResolver,
) -> HeatingBindingSelectionDTO:
    candidate_id = binding.provenance.get("candidate_id")
    return HeatingBindingSelectionDTO(
        role=binding.role,
        native_id=binding.reference.native_id,
        current_locator=binding.reference.current_locator,
        identity_quality=binding.reference.identity_quality.value,
        candidate_id=candidate_id if isinstance(candidate_id, str) else None,
        user_confirmed=binding.user_confirmed,
        selection_origin=binding.selection_origin.value,
        resolution_status=resolver.resolve(binding.reference, snapshot).status.value,
    )


def _validation_issue_dto(issue: ValidationIssue) -> ValidationIssueDTO:
    return ValidationIssueDTO(
        code=issue.code,
        severity=issue.severity.value,
        path=issue.path,
        module_role=issue.module_role,
        message_key=issue.message_key,
        parameters=dict(issue.parameters),
        evidence=dict(issue.evidence),
        suggested_action=issue.suggested_action,
    )


def _discovery_dto(snapshot: DiscoverySnapshot) -> DiscoverySnapshotDTO:
    if snapshot.content_fingerprint is None:
        raise ValueError("validated discovery snapshot has no content fingerprint")
    counts = Counter(item.object_kind for item in snapshot.objects)
    return DiscoverySnapshotDTO(
        snapshot_id=snapshot.snapshot_id,
        provider=snapshot.provider,
        provider_instance_id=snapshot.provider_instance_id,
        captured_at=snapshot.captured_at,
        content_fingerprint=snapshot.content_fingerprint,
        object_counts=dict(sorted(counts.items())),
        objects=tuple(
            DiscoveredObjectDTO(
                object_kind=item.object_kind,
                native_id=item.native_id,
                current_locator=item.current_locator,
                identity_quality=item.identity_quality.value,
                device_registry_id=item.device_registry_id,
                area_id=item.area_id,
                floor_id=item.floor_id,
            )
            for item in snapshot.objects
        ),
    )
