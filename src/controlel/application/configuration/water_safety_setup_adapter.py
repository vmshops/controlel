"""Versioned setup adapter for the Water Safety v1 module."""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from controlel.application.setup.json_data import (
    FrozenJsonMapping,
    ImmutableJsonMapping,
    canonical_json,
    immutable_json_mapping,
)
from controlel.application.setup.model import (
    BindingSelection,
    CanonicalConfigurationRevision,
    DiscoverySnapshot,
    DraftRevision,
    IdentityQuality,
    ProviderReference,
    SelectionOrigin,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
    ValidationSubjectKind,
)

WATER_SAFETY_MODULE_KEY = "water_safety"
WATER_SAFETY_SETUP_SCHEMA_VERSION = 1
WATER_SAFETY_VALIDATOR_POLICY_VERSION = 1
WATER_SAFETY_RECOMMENDATION_POLICY_VERSION = 1
WATER_SAFETY_SENSOR_ROLE = "water_safety.moisture_sensor"
NOTIFICATION_ROLE_PREFIX = "water_safety.notification."
SIREN_ROLE_PREFIX = "water_safety.siren."
SHUTOFF_VALVE_ROLE_PREFIX = "water_safety.shutoff_valve."
DEFAULT_NOTIFICATION_ROLE = "water_safety.notification.primary"
MAX_NOTIFICATION_TARGETS = 16
MAX_SIREN_TARGETS = 16
MAX_SHUTOFF_VALVE_TARGETS = 16
MAX_MESSAGE_LENGTH = 2_000
MAX_UNAVAILABLE_GRACE_SECONDS = 86_400.0
MAX_FAULT_REPEAT_SECONDS = 604_800.0
_HA_ENTITY_KIND = "home_assistant.entity"
_HA_ENDPOINT_KIND = "home_assistant.endpoint"
_HA_VALVE_CLOSE_FEATURE = 2


class WaterSafetyRecommendationConfidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class WaterSafetySetupCandidate(BaseModel):
    """One snapshot-local, non-authoritative candidate for a Water Safety role."""

    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: str = Field(min_length=1)
    reference: ProviderReference
    capabilities: tuple[str, ...] = Field(min_length=1)
    confidence: WaterSafetyRecommendationConfidence
    reason_codes: tuple[str, ...] = Field(min_length=1)
    evidence: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))
    explicit_confirmation_required: bool = True

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("capabilities", "reason_codes", mode="after")
    @classmethod
    def string_sets_must_be_deterministic(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item for item in value):
            raise ValueError("candidate capabilities and reasons must be non-empty")
        return tuple(sorted(set(value)))

    @field_validator("evidence", mode="after")
    @classmethod
    def evidence_must_be_immutable(cls, value: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, "Water Safety candidate evidence")


class WaterSafetyRoleRecommendation(BaseModel):
    """Ordered advice for one role; it is not a binding selection."""

    role: str = Field(min_length=1)
    recommended_candidate: WaterSafetySetupCandidate | None = None
    alternatives: tuple[WaterSafetySetupCandidate, ...] = ()
    confidence: WaterSafetyRecommendationConfidence | None = None
    reason_codes: tuple[str, ...] = ()
    explicit_confirmation_required: bool = True

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def recommendation_must_be_consistent(self) -> WaterSafetyRoleRecommendation:
        all_candidates = self.candidates
        if any(candidate.role != self.role for candidate in all_candidates):
            raise ValueError("Water Safety recommendation candidates must match the recommendation role")
        if len({candidate.candidate_id for candidate in all_candidates}) != len(all_candidates):
            raise ValueError("Water Safety recommendation candidate IDs must be unique per role")
        if self.recommended_candidate is None:
            if self.confidence is not None or self.reason_codes:
                raise ValueError("a role without a recommendation cannot carry recommendation confidence or reasons")
        elif self.confidence is not self.recommended_candidate.confidence:
            raise ValueError("recommendation confidence must describe the recommended candidate")
        return self

    @property
    def candidates(self) -> tuple[WaterSafetySetupCandidate, ...]:
        if self.recommended_candidate is None:
            return self.alternatives
        return (self.recommended_candidate, *self.alternatives)


class WaterSafetyRecommendationSet(BaseModel):
    """Deterministic Water Safety advice tied to one immutable discovery snapshot."""

    snapshot_id: str = Field(min_length=1)
    snapshot_content_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(min_length=1)
    provider_instance_id: str = Field(min_length=1)
    module_schema_version: int = WATER_SAFETY_SETUP_SCHEMA_VERSION
    recommendation_policy_version: int = WATER_SAFETY_RECOMMENDATION_POLICY_VERSION
    recommendations: tuple[WaterSafetyRoleRecommendation, ...]

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def recommendations_must_have_unique_roles(self) -> WaterSafetyRecommendationSet:
        roles = tuple(recommendation.role for recommendation in self.recommendations)
        if len(set(roles)) != len(roles):
            raise ValueError("Water Safety recommendations must have unique roles")
        object.__setattr__(self, "recommendations", tuple(sorted(self.recommendations, key=lambda item: item.role)))
        return self

    def candidate(self, role: str, candidate_id: str) -> WaterSafetySetupCandidate:
        recommendation = next((item for item in self.recommendations if item.role == role), None)
        if recommendation is None:
            raise ValueError(f"unsupported Water Safety recommendation role: {role}")
        candidate = next((item for item in recommendation.candidates if item.candidate_id == candidate_id), None)
        if candidate is None:
            raise ValueError(f"candidate {candidate_id} is not available for role {role}")
        return candidate


class WaterSafetyMessages(BaseModel):
    """Optional user-authored message overrides; absent values use host defaults."""

    wet: str | None = Field(default=None, min_length=1, max_length=MAX_MESSAGE_LENGTH)
    recovery: str | None = Field(default=None, min_length=1, max_length=MAX_MESSAGE_LENGTH)
    fault: str | None = Field(default=None, min_length=1, max_length=MAX_MESSAGE_LENGTH)

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class WaterSafetySetupPayload(BaseModel):
    """Canonical Water Safety v1 semantics; meanings are frozen by schema version."""

    behavior_contract_version: Literal[1] = 1
    zone_id: str = Field(min_length=1)
    zone_name: str = Field(min_length=1)
    area_id: str = Field(min_length=1)
    area_name: str = Field(min_length=1)
    sensor_id: str = Field(min_length=1)
    critical_sensor: bool = False
    unavailable_grace_seconds: float = Field(default=60.0, ge=0, le=MAX_UNAVAILABLE_GRACE_SECONDS)
    fault_repeat_interval_seconds: float | None = Field(default=None, ge=1, le=MAX_FAULT_REPEAT_SECONDS)
    notification_target_roles: tuple[str, ...] = Field(min_length=1, max_length=MAX_NOTIFICATION_TARGETS)
    siren_target_roles: tuple[str, ...] = Field(default=(), max_length=MAX_SIREN_TARGETS)
    shutoff_valve_target_roles: tuple[str, ...] = Field(default=(), max_length=MAX_SHUTOFF_VALVE_TARGETS)
    messages: WaterSafetyMessages = Field(default_factory=WaterSafetyMessages)

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    @field_validator("unavailable_grace_seconds", "fault_repeat_interval_seconds")
    @classmethod
    def durations_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("Water Safety durations must be finite")
        return value

    @field_validator("notification_target_roles")
    @classmethod
    def notification_roles_must_be_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_roles(value, NOTIFICATION_ROLE_PREFIX, "notification")

    @field_validator("siren_target_roles")
    @classmethod
    def siren_roles_must_be_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_roles(value, SIREN_ROLE_PREFIX, "siren")

    @field_validator("shutoff_valve_target_roles")
    @classmethod
    def shutoff_valve_roles_must_be_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_roles(value, SHUTOFF_VALVE_ROLE_PREFIX, "shutoff valve")

    @model_validator(mode="after")
    def output_roles_must_not_overlap(self) -> WaterSafetySetupPayload:
        role_sets = (
            set(self.notification_target_roles),
            set(self.siren_target_roles),
            set(self.shutoff_valve_target_roles),
        )
        if any(left & right for index, left in enumerate(role_sets) for right in role_sets[index + 1 :]):
            raise ValueError("Water Safety output roles must not overlap")
        return self


class WaterSafetySetupAdapter:
    """Validate and canonicalize only Water Safety-owned setup semantics."""

    module_key = WATER_SAFETY_MODULE_KEY
    module_schema_version = WATER_SAFETY_SETUP_SCHEMA_VERSION
    validator_policy_version = WATER_SAFETY_VALIDATOR_POLICY_VERSION
    recommendation_policy_version = WATER_SAFETY_RECOMMENDATION_POLICY_VERSION

    def recommend(
        self,
        snapshot: DiscoverySnapshot,
        *,
        notification_roles: tuple[str, ...] = (DEFAULT_NOTIFICATION_ROLE,),
        siren_roles: tuple[str, ...] = (),
        shutoff_valve_roles: tuple[str, ...] = (),
        preferred_area_id: str | None = None,
        preferred_floor_id: str | None = None,
    ) -> WaterSafetyRecommendationSet:
        """Derive transparent snapshot-local advice without selecting a binding."""

        snapshot_fingerprint = snapshot.content_fingerprint
        if snapshot_fingerprint is None:
            raise ValueError("validated discovery snapshot has no content fingerprint")
        supported_roles = (
            WATER_SAFETY_SENSOR_ROLE,
            *notification_roles,
            *siren_roles,
            *shutoff_valve_roles,
        )
        recommendations: list[WaterSafetyRoleRecommendation] = []
        for role in sorted(supported_roles):
            candidates = tuple(
                sorted(
                    (
                        candidate
                        for reference in snapshot.objects
                        if (
                            candidate := _water_safety_candidate(
                                snapshot,
                                role,
                                reference,
                                preferred_area_id=preferred_area_id,
                                preferred_floor_id=preferred_floor_id,
                            )
                        )
                        is not None
                    ),
                    key=lambda item: _candidate_sort_key(
                        item,
                        preferred_area_id=preferred_area_id,
                        preferred_floor_id=preferred_floor_id,
                    ),
                )
            )
            recommended = candidates[0] if candidates else None
            alternatives = candidates[1:] if recommended is not None else ()
            recommendations.append(
                WaterSafetyRoleRecommendation(
                    role=role,
                    recommended_candidate=recommended,
                    alternatives=alternatives,
                    confidence=recommended.confidence if recommended is not None else None,
                    reason_codes=recommended.reason_codes if recommended is not None else (),
                )
            )
        return WaterSafetyRecommendationSet(
            snapshot_id=snapshot.snapshot_id,
            snapshot_content_fingerprint=snapshot_fingerprint,
            provider=snapshot.provider,
            provider_instance_id=snapshot.provider_instance_id,
            recommendations=tuple(recommendations),
        )

    def create_draft_from_recommendations(
        self,
        recommendations: WaterSafetyRecommendationSet,
        *,
        selected_candidate_ids: Mapping[str, str],
        explicitly_confirmed_roles: Collection[str],
        draft_id: str,
        environment_id: str,
        module_instance_id: str,
        created_at: datetime,
        settings: Mapping[str, object],
        base_active_revision_id: str | None = None,
        preferred_area_id: str | None = None,
        preferred_area_name: str | None = None,
        notification_roles: tuple[str, ...] = (DEFAULT_NOTIFICATION_ROLE,),
        siren_roles: tuple[str, ...] = (),
        shutoff_valve_roles: tuple[str, ...] = (),
    ) -> DraftRevision:
        """Persist only explicit selections; a recommendation never confirms itself."""

        if (
            recommendations.module_schema_version != self.module_schema_version
            or recommendations.recommendation_policy_version != self.recommendation_policy_version
        ):
            raise ValueError("Water Safety recommendation contract is not supported by this adapter")
        unknown_confirmations = set(explicitly_confirmed_roles) - set(selected_candidate_ids)
        if unknown_confirmations:
            raise ValueError("cannot confirm a Water Safety role that was not explicitly selected")
        moisture_candidate = (
            recommendations.candidate(WATER_SAFETY_SENSOR_ROLE, selected_candidate_ids[WATER_SAFETY_SENSOR_ROLE])
            if WATER_SAFETY_SENSOR_ROLE in selected_candidate_ids
            else None
        )
        merged_settings = _default_water_safety_settings(
            preferred_area_id=preferred_area_id,
            preferred_area_name=preferred_area_name,
            notification_roles=notification_roles,
            siren_roles=siren_roles,
            shutoff_valve_roles=shutoff_valve_roles,
            moisture_sensor_native_id=(None if moisture_candidate is None else moisture_candidate.reference.native_id),
            overrides=settings,
        )
        bindings: list[BindingSelection] = []
        for role, candidate_id in sorted(selected_candidate_ids.items()):
            candidate = recommendations.candidate(role, candidate_id)
            bindings.append(
                BindingSelection(
                    role=role,
                    reference=candidate.reference,
                    selection_origin=SelectionOrigin.RECOMMENDATION_ACCEPTED,
                    user_confirmed=role in explicitly_confirmed_roles,
                    provenance={
                        "discovery_snapshot_id": recommendations.snapshot_id,
                        "discovery_content_fingerprint": recommendations.snapshot_content_fingerprint,
                        "recommendation_policy_version": recommendations.recommendation_policy_version,
                        "candidate_id": candidate.candidate_id,
                        "confidence": candidate.confidence.value,
                        "reason_codes": candidate.reason_codes,
                    },
                )
            )
        return DraftRevision(
            draft_id=draft_id,
            revision=1,
            environment_id=environment_id,
            module_key=self.module_key,
            module_instance_id=module_instance_id,
            module_schema_version=self.module_schema_version,
            created_at=created_at,
            updated_at=created_at,
            base_active_revision_id=base_active_revision_id,
            settings=merged_settings,
            bindings=tuple(bindings),
            lineage={
                "created_from_discovery_snapshot_id": recommendations.snapshot_id,
                "recommendation_policy_version": recommendations.recommendation_policy_version,
            },
        )

    def validate(
        self,
        draft: DraftRevision,
        *,
        report_id: str,
        evaluated_at: datetime,
        discovery_snapshot_id: str | None = None,
        resolution_generation: int | None = None,
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        contract_supported = (
            draft.module_key == self.module_key and draft.module_schema_version == self.module_schema_version
        )
        if not contract_supported:
            issues.append(
                _issue(
                    "water_safety.unsupported_module_contract",
                    ("module_schema_version",),
                    "setup.water_safety.unsupported_module_contract",
                )
            )

        normalized: WaterSafetySetupPayload | None = None
        try:
            normalized = _validate_payload(draft.settings)
        except ValidationError as error:
            for detail in error.errors(include_url=False):
                issues.append(
                    ValidationIssue(
                        code="water_safety.invalid_setting",
                        severity=ValidationSeverity.ERROR,
                        path=tuple(str(part) for part in detail["loc"]),
                        message_key="setup.water_safety.invalid_setting",
                        parameters={"error_type": detail["type"]},
                    )
                )

        bindings_by_role = {binding.role: binding for binding in draft.bindings}
        expected_roles = {WATER_SAFETY_SENSOR_ROLE}
        if normalized is not None:
            expected_roles.update(normalized.notification_target_roles)
            expected_roles.update(normalized.siren_target_roles)
            expected_roles.update(normalized.shutoff_valve_target_roles)
        for role in sorted(set(bindings_by_role) - expected_roles):
            issues.append(
                _issue(
                    "water_safety.unsupported_binding_role",
                    ("bindings", role),
                    "setup.water_safety.unsupported_binding_role",
                    role=role,
                )
            )
        for role in sorted(expected_roles):
            binding = bindings_by_role.get(role)
            if binding is None:
                issues.append(
                    _issue(
                        "water_safety.required_binding_missing",
                        ("bindings", role),
                        "setup.water_safety.required_binding_missing",
                        role=role,
                    )
                )
                continue
            if not binding.user_confirmed:
                issues.append(
                    _issue(
                        "water_safety.binding_confirmation_required",
                        ("bindings", role),
                        "setup.water_safety.binding_confirmation_required",
                        role=role,
                    )
                )
            if binding.reference.identity_quality is not IdentityQuality.STABLE:
                issues.append(
                    _issue(
                        "water_safety.stable_reference_required",
                        ("bindings", role, "reference"),
                        "setup.water_safety.stable_reference_required",
                        role=role,
                    )
                )

        return ValidationReport(
            report_id=report_id,
            subject_kind=ValidationSubjectKind.DRAFT,
            subject_id=draft.draft_id,
            subject_revision=draft.revision,
            subject_fingerprint=draft.content_fingerprint,
            module_key=draft.module_key,
            module_schema_version=draft.module_schema_version,
            validator_policy_version=self.validator_policy_version,
            evaluated_at=evaluated_at,
            discovery_snapshot_id=discovery_snapshot_id,
            resolution_generation=resolution_generation,
            issues=tuple(issues),
            activation_ready=not any(issue.severity is ValidationSeverity.ERROR for issue in issues),
        )

    def canonicalize(
        self,
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
        integration_version: str | None = None,
        parent_revision_id: str | None = None,
    ) -> CanonicalConfigurationRevision:
        if report.validator_policy_version != self.validator_policy_version:
            raise ValueError("validation report uses an unsupported Water Safety validator policy")
        normalized = _validate_payload(draft.settings)
        return CanonicalConfigurationRevision.from_validated_draft(
            draft,
            report,
            configuration_id=configuration_id,
            revision_id=revision_id,
            revision=revision,
            provider=provider,
            provider_instance_id=provider_instance_id,
            created_at=created_at,
            actor=actor,
            source=source,
            change_kind=change_kind,
            reason=reason,
            core_version=core_version,
            integration_version=integration_version,
            parent_revision_id=parent_revision_id,
            normalized_payload=normalized.model_dump(mode="json"),
            logical_identities={
                "area_id": normalized.area_id,
                "sensor_id": normalized.sensor_id,
                "zone_id": normalized.zone_id,
            },
        )


def _canonical_roles(value: tuple[str, ...], prefix: str, label: str) -> tuple[str, ...]:
    if any(not role.startswith(prefix) or role == prefix for role in value):
        raise ValueError(f"{label} roles must use the {prefix} namespace")
    if value != tuple(sorted(set(value))):
        raise ValueError(f"{label} roles must be unique and sorted")
    return value


def _validate_payload(value: object) -> WaterSafetySetupPayload:
    """Validate immutable JSON input with strict scalar semantics."""

    return WaterSafetySetupPayload.model_validate_json(canonical_json(value))


def _issue(
    code: str,
    path: tuple[str, ...],
    message_key: str,
    *,
    role: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=ValidationSeverity.ERROR,
        path=path,
        module_role=role,
        message_key=message_key,
    )


def _water_safety_candidate(
    snapshot: DiscoverySnapshot,
    role: str,
    reference: ProviderReference,
    *,
    preferred_area_id: str | None,
    preferred_floor_id: str | None,
) -> WaterSafetySetupCandidate | None:
    classification = _classify_candidate(role, reference)
    if classification is None:
        return None
    confidence, capabilities, reasons = classification
    evidence: dict[str, object] = {
        "domain": _reference_domain(reference),
        "device_class": _evidence_string(reference, "device_class"),
        "original_device_class": _evidence_string(reference, "original_device_class"),
        "area_id": reference.area_id,
        "floor_id": reference.floor_id,
    }
    reason_codes = list(reasons)
    if preferred_area_id is not None:
        area_match = reference.area_id == preferred_area_id
        evidence["preferred_area_id"] = preferred_area_id
        evidence["preferred_area_match"] = area_match
        if area_match:
            reason_codes.append("water_safety.candidate.preferred_area_match")
    if preferred_floor_id is not None:
        floor_match = reference.floor_id == preferred_floor_id
        evidence["preferred_floor_id"] = preferred_floor_id
        evidence["preferred_floor_match"] = floor_match
        if floor_match:
            reason_codes.append("water_safety.candidate.preferred_floor_match")
    snapshot_fingerprint = snapshot.content_fingerprint
    if snapshot_fingerprint is None:
        raise ValueError("validated discovery snapshot has no content fingerprint")
    candidate_id = hashlib.sha256(
        canonical_json(
            {
                "snapshot_content_fingerprint": snapshot_fingerprint,
                "role": role,
                "reference": reference.document_data(),
                "recommendation_policy_version": WATER_SAFETY_RECOMMENDATION_POLICY_VERSION,
            }
        ).encode("utf-8")
    ).hexdigest()
    return WaterSafetySetupCandidate(
        candidate_id=candidate_id,
        role=role,
        reference=reference,
        capabilities=capabilities,
        confidence=confidence,
        reason_codes=tuple(reason_codes),
        evidence=evidence,
    )


def _classify_candidate(
    role: str,
    reference: ProviderReference,
) -> tuple[WaterSafetyRecommendationConfidence, tuple[str, ...], tuple[str, ...]] | None:
    if role == WATER_SAFETY_SENSOR_ROLE:
        return _classify_moisture(reference)
    if role.startswith(NOTIFICATION_ROLE_PREFIX):
        return _classify_notify(reference)
    if role.startswith(SIREN_ROLE_PREFIX):
        return _classify_siren(reference)
    if role.startswith(SHUTOFF_VALVE_ROLE_PREFIX):
        return _classify_shutoff_valve(reference)
    return None


def _classify_moisture(
    reference: ProviderReference,
) -> tuple[WaterSafetyRecommendationConfidence, tuple[str, ...], tuple[str, ...]] | None:
    if reference.object_kind != _HA_ENTITY_KIND:
        return None
    domain = _reference_domain(reference)
    device_classes = {
        value
        for field in ("device_class", "original_device_class")
        if (value := _evidence_string(reference, field)) is not None
    }
    if domain == "binary_sensor" and "moisture" in device_classes:
        return (
            WaterSafetyRecommendationConfidence.HIGH,
            ("measurement.moisture",),
            ("water_safety.candidate.moisture_binary_sensor",),
        )
    if domain == "sensor" and "moisture" in device_classes:
        return (
            WaterSafetyRecommendationConfidence.MEDIUM,
            ("measurement.moisture",),
            ("water_safety.candidate.moisture_sensor",),
        )
    locator = (reference.current_locator or "").lower()
    if "moisture" in locator or "leak" in locator or "water" in locator:
        return (
            WaterSafetyRecommendationConfidence.LOW,
            ("measurement.moisture.unverified",),
            ("water_safety.candidate.moisture_locator_hint",),
        )
    return None


def _classify_notify(
    reference: ProviderReference,
) -> tuple[WaterSafetyRecommendationConfidence, tuple[str, ...], tuple[str, ...]] | None:
    domain = _reference_domain(reference)
    if reference.object_kind == _HA_ENDPOINT_KIND and domain == "notify":
        return (
            WaterSafetyRecommendationConfidence.HIGH,
            ("notification.deliver",),
            ("water_safety.candidate.notify_service",),
        )
    if reference.identity_quality is IdentityQuality.STABLE:
        locator = (reference.current_locator or "").lower()
        if locator.startswith("notify."):
            return (
                WaterSafetyRecommendationConfidence.HIGH,
                ("notification.deliver",),
                ("water_safety.candidate.notify_locator",),
            )
        if "notify" in locator:
            return (
                WaterSafetyRecommendationConfidence.MEDIUM,
                ("notification.deliver",),
                ("water_safety.candidate.notify_locator_hint",),
            )
    return None


def _classify_siren(
    reference: ProviderReference,
) -> tuple[WaterSafetyRecommendationConfidence, tuple[str, ...], tuple[str, ...]] | None:
    if reference.object_kind != _HA_ENTITY_KIND:
        return None
    domain = _reference_domain(reference)
    if domain == "siren":
        return (
            WaterSafetyRecommendationConfidence.HIGH,
            ("alert.siren",),
            ("water_safety.candidate.siren_domain",),
        )
    if domain == "switch":
        locator = (reference.current_locator or "").lower()
        if "siren" in locator:
            return (
                WaterSafetyRecommendationConfidence.MEDIUM,
                ("alert.siren",),
                ("water_safety.candidate.siren_switch_locator",),
            )
    return None


def _classify_shutoff_valve(
    reference: ProviderReference,
) -> tuple[WaterSafetyRecommendationConfidence, tuple[str, ...], tuple[str, ...]] | None:
    if reference.object_kind != _HA_ENTITY_KIND or _reference_domain(reference) != "valve":
        return None
    device_classes = {
        value
        for field in ("device_class", "original_device_class")
        if (value := _evidence_string(reference, field)) is not None
    }
    supported_features = _evidence_integer(reference, "supported_features")
    if "water" not in device_classes or supported_features is None:
        return None
    if supported_features & _HA_VALVE_CLOSE_FEATURE == 0:
        return None
    return (
        WaterSafetyRecommendationConfidence.HIGH,
        ("safety.water_shutoff.close",),
        ("water_safety.candidate.water_valve_close",),
    )


def _candidate_sort_key(
    candidate: WaterSafetySetupCandidate,
    *,
    preferred_area_id: str | None,
    preferred_floor_id: str | None,
) -> tuple[int, int, int, str, str, str]:
    confidence_rank = {
        WaterSafetyRecommendationConfidence.HIGH: 0,
        WaterSafetyRecommendationConfidence.MEDIUM: 1,
        WaterSafetyRecommendationConfidence.LOW: 2,
    }[candidate.confidence]
    area_rank = 0 if preferred_area_id is None or candidate.reference.area_id == preferred_area_id else 1
    floor_rank = 0 if preferred_floor_id is None or candidate.reference.floor_id == preferred_floor_id else 1
    return (
        confidence_rank,
        area_rank,
        floor_rank,
        candidate.reference.current_locator or "",
        candidate.reference.native_id or "",
        canonical_json(candidate.reference.document_data()),
    )


def _default_water_safety_settings(
    *,
    preferred_area_id: str | None,
    preferred_area_name: str | None,
    notification_roles: tuple[str, ...],
    siren_roles: tuple[str, ...],
    shutoff_valve_roles: tuple[str, ...],
    moisture_sensor_native_id: str | None,
    overrides: Mapping[str, object],
) -> dict[str, object]:
    area_id = preferred_area_id or "default-area"
    area_name = preferred_area_name or area_id
    defaults: dict[str, object] = {
        "behavior_contract_version": 1,
        "zone_id": area_id,
        "zone_name": area_name,
        "area_id": area_id,
        "area_name": area_name,
        "sensor_id": moisture_sensor_native_id or "moisture-sensor",
        "critical_sensor": False,
        "unavailable_grace_seconds": 60.0,
        "fault_repeat_interval_seconds": None,
        "notification_target_roles": list(notification_roles),
        "siren_target_roles": list(siren_roles),
        "shutoff_valve_target_roles": list(shutoff_valve_roles),
        "messages": {},
    }
    merged = {**defaults, **dict(overrides)}
    return merged


def _reference_domain(reference: ProviderReference) -> str | None:
    return _evidence_string(reference, "domain")


def _evidence_string(reference: ProviderReference, key: str) -> str | None:
    value = reference.recovery_evidence.get(key)
    return value if isinstance(value, str) and value else None


def _evidence_integer(reference: ProviderReference, key: str) -> int | None:
    value = reference.recovery_evidence.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
