"""First module adapter for the module-neutral Setup v0.1 kernel."""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from controlel.application.setup.discovery import (
    ProviderReferenceResolution,
    ProviderReferenceResolver,
    ReferenceResolutionStatus,
)
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
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.notifications import (
    DEFAULT_CRITICAL_MAXIMUM_PER_WINDOW,
    DEFAULT_CRITICAL_RATE_WINDOW,
    DEFAULT_NOTIFICATION_HISTORY_CAPACITY,
    DEFAULT_NOTIFICATION_MAXIMUM_PER_WINDOW,
    DEFAULT_NOTIFICATION_RATE_WINDOW,
    MAX_CRITICAL_MAXIMUM_PER_WINDOW,
    MAX_CRITICAL_RATE_WINDOW,
    MAX_NOTIFICATION_HISTORY_CAPACITY,
    MAX_NOTIFICATION_MAXIMUM_PER_WINDOW,
    MAX_NOTIFICATION_RATE_WINDOW,
    MAX_NOTIFICATION_RECIPIENTS,
    NotificationLevel,
)
from controlel.domain.operational_events import OperationalEventCategory

POLICY_LESS_HEATING_SETUP_SCHEMA_VERSION = 1
HEATING_SETUP_SCHEMA_VERSION = 2
PRIMARY_TEMPERATURE_ROLE = "heating.primary_temperature"
SOURCE_ENABLE_TARGET_ROLE = "heating.source.enable_target"
SOURCE_DISABLE_TARGET_ROLE = "heating.source.disable_target"
REPORTED_SOURCE_STATE_ROLE = "heating.source.reported_state"
HEAT_DELIVERY_ACTUATOR_ROLE = "heating.heat_delivery.actuator"
HEATING_RECOMMENDATION_POLICY_VERSION = 1
_HA_ENTITY_KIND = "home_assistant.entity"
_HA_ENDPOINT_KIND = "home_assistant.endpoint"
_CLIMATE_TARGET_TEMPERATURE_FEATURE = 1
_DEFAULT_CONFIGURED_DEBUG_DURATION_SECONDS = 3600.0
_IDENTIFIER_PATTERN = r"^[a-z0-9_]+$"
_HOME_ASSISTANT_NOTIFY_TARGET_PATTERN = r"^notify\.[a-z0-9_]+$"


class RecommendationConfidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class HeatingSetupCandidate(BaseModel):
    """One snapshot-local, non-authoritative candidate for a Heating role."""

    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: str = Field(min_length=1)
    reference: ProviderReference
    capabilities: tuple[str, ...] = Field(min_length=1)
    confidence: RecommendationConfidence
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
        return immutable_json_mapping(value, "Heating candidate evidence")


class HeatingRoleRecommendation(BaseModel):
    """Ordered advice for one role; it is not a binding selection."""

    role: str = Field(min_length=1)
    recommended_candidate: HeatingSetupCandidate | None = None
    alternatives: tuple[HeatingSetupCandidate, ...] = ()
    confidence: RecommendationConfidence | None = None
    reason_codes: tuple[str, ...] = ()
    explicit_confirmation_required: bool = True

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def recommendation_must_be_consistent(self) -> HeatingRoleRecommendation:
        all_candidates = self.candidates
        if any(candidate.role != self.role for candidate in all_candidates):
            raise ValueError("Heating recommendation candidates must match the recommendation role")
        if len({candidate.candidate_id for candidate in all_candidates}) != len(all_candidates):
            raise ValueError("Heating recommendation candidate IDs must be unique per role")
        if self.recommended_candidate is None:
            if self.confidence is not None or self.reason_codes:
                raise ValueError("a role without a recommendation cannot carry recommendation confidence or reasons")
        elif self.confidence is not self.recommended_candidate.confidence:
            raise ValueError("recommendation confidence must describe the recommended candidate")
        return self

    @property
    def candidates(self) -> tuple[HeatingSetupCandidate, ...]:
        if self.recommended_candidate is None:
            return self.alternatives
        return (self.recommended_candidate, *self.alternatives)


class HeatingRecommendationSet(BaseModel):
    """Deterministic Heating advice tied to one immutable discovery snapshot."""

    snapshot_id: str = Field(min_length=1)
    snapshot_content_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(min_length=1)
    provider_instance_id: str = Field(min_length=1)
    module_schema_version: int = HEATING_SETUP_SCHEMA_VERSION
    recommendation_policy_version: int = HEATING_RECOMMENDATION_POLICY_VERSION
    recommendations: tuple[HeatingRoleRecommendation, ...]

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def recommendations_must_have_unique_roles(self) -> HeatingRecommendationSet:
        roles = tuple(recommendation.role for recommendation in self.recommendations)
        if len(set(roles)) != len(roles):
            raise ValueError("Heating recommendations must have unique roles")
        object.__setattr__(self, "recommendations", tuple(sorted(self.recommendations, key=lambda item: item.role)))
        return self

    def candidate(self, role: str, candidate_id: str) -> HeatingSetupCandidate:
        recommendation = next((item for item in self.recommendations if item.role == role), None)
        if recommendation is None:
            raise ValueError(f"unsupported Heating recommendation role: {role}")
        candidate = next((item for item in recommendation.candidates if item.candidate_id == candidate_id), None)
        if candidate is None:
            raise ValueError(f"candidate {candidate_id} is not available for role {role}")
        return candidate


class HeatingServiceCallSetup(BaseModel):
    """Lossless arbitrary Home Assistant service invocation binding."""

    domain: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    service: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    target_binding_role: str = Field(min_length=1)

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("domain")
    @classmethod
    def domain_must_not_call_controlel(cls, value: str) -> str:
        if value == "controlel":
            raise ValueError("Controlel cannot call its own integration service domain")
        return value


class HeatingDiagnosticPolicy(BaseModel):
    """Normalized configured diagnostics behavior; runtime expiry state is excluded."""

    diagnostic_profile: Literal["basic", "detailed", "debug"] = "basic"
    configured_debug_duration_seconds: float = Field(
        default=_DEFAULT_CONFIGURED_DEBUG_DURATION_SECONDS,
        gt=0,
    )
    debug_until_changed: bool = Field(default=False, strict=True)
    diagnostic_profile_before_debug: Literal["basic", "detailed"] = "detailed"

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("configured_debug_duration_seconds", mode="before")
    @classmethod
    def configured_duration_must_be_finite_seconds(cls, value: object) -> float:
        return _finite_configured_duration(value, "configured Debug duration")

    @property
    def debug_duration_seconds(self) -> float | None:
        """Return the effective configured expiry duration without runtime deadline state."""

        if self.debug_until_changed:
            return None
        return self.configured_debug_duration_seconds


class HeatingNotificationRecipient(BaseModel):
    """One normalized notification recipient with its unredacted transport target."""

    recipient_id: str = Field(min_length=1, pattern=_IDENTIFIER_PATTERN)
    transport: Literal["home_assistant_notify"] = "home_assistant_notify"
    target: str = Field(min_length=1, pattern=_HOME_ASSISTANT_NOTIFY_TARGET_PATTERN)
    enabled: bool = Field(default=True, strict=True)
    minimum_level: NotificationLevel = NotificationLevel.OPERATIONAL
    categories: tuple[OperationalEventCategory, ...] = ()

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("categories", mode="after")
    @classmethod
    def categories_must_be_deterministic(
        cls,
        value: tuple[OperationalEventCategory, ...],
    ) -> tuple[OperationalEventCategory, ...]:
        return tuple(sorted(set(value), key=lambda item: item.value))

    @property
    def target_configured(self) -> bool:
        """Expose the redaction-safe meaning used by diagnostics projections."""

        return bool(self.target)


class HeatingNotificationPolicy(BaseModel):
    """Deterministic bounded notification configuration in canonical units."""

    enabled: bool = Field(default=False, strict=True)
    recipients: tuple[HeatingNotificationRecipient, ...] = ()
    maximum_per_window: int = Field(
        default=DEFAULT_NOTIFICATION_MAXIMUM_PER_WINDOW,
        ge=1,
        le=MAX_NOTIFICATION_MAXIMUM_PER_WINDOW,
        strict=True,
    )
    rate_window_seconds: float = Field(
        default=DEFAULT_NOTIFICATION_RATE_WINDOW.total_seconds(),
        ge=1,
        le=MAX_NOTIFICATION_RATE_WINDOW.total_seconds(),
    )
    critical_maximum_per_window: int = Field(
        default=DEFAULT_CRITICAL_MAXIMUM_PER_WINDOW,
        ge=1,
        le=MAX_CRITICAL_MAXIMUM_PER_WINDOW,
        strict=True,
    )
    critical_rate_window_seconds: float = Field(
        default=DEFAULT_CRITICAL_RATE_WINDOW.total_seconds(),
        ge=1,
        le=MAX_CRITICAL_RATE_WINDOW.total_seconds(),
    )
    history_capacity: int = Field(
        default=DEFAULT_NOTIFICATION_HISTORY_CAPACITY,
        ge=1,
        le=MAX_NOTIFICATION_HISTORY_CAPACITY,
        strict=True,
    )

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("rate_window_seconds", "critical_rate_window_seconds", mode="before")
    @classmethod
    def rate_windows_must_be_finite_seconds(cls, value: object, info: object) -> float:
        return _finite_configured_duration(value, str(getattr(info, "field_name", "notification window")))

    @model_validator(mode="after")
    def recipients_must_be_bounded_and_unique(self) -> HeatingNotificationPolicy:
        if len(self.recipients) > MAX_NOTIFICATION_RECIPIENTS:
            raise ValueError(f"notification recipients must not exceed {MAX_NOTIFICATION_RECIPIENTS}")
        recipient_ids = tuple(recipient.recipient_id for recipient in self.recipients)
        if len(recipient_ids) != len(set(recipient_ids)):
            raise ValueError("notification recipient IDs must be unique")
        enabled_bindings = tuple(
            (recipient.transport, recipient.target) for recipient in self.recipients if recipient.enabled
        )
        if len(enabled_bindings) != len(set(enabled_bindings)):
            raise ValueError("enabled notification transport and target bindings must be unique")
        return self


class HeatingSetupPayload(BaseModel):
    """Small normalized Heating v2 payload with canonical units and explicit policies."""

    zone_id: str = Field(min_length=1)
    zone_name: str = Field(min_length=1)
    sensor_id: str = Field(min_length=1)
    sensor_name: str = Field(min_length=1)
    target_temperature_celsius: float
    primary_measurement_max_age_seconds: float = Field(gt=0)
    maximum_future_skew_seconds: float = Field(ge=0)
    indeterminate_grace_period_seconds: float = Field(ge=0)
    indeterminate_timeout_action: HeatingAction = HeatingAction.DISABLE_HEATING
    heating_turn_on_differential_celsius: float = Field(default=0.0, ge=0)
    heating_turn_off_differential_celsius: float = Field(default=0.0, ge=0)
    heat_demand_confirmation_seconds: float = Field(default=0.0, ge=0)
    minimum_heating_on_seconds: float = Field(default=0.0, ge=0)
    minimum_heating_off_seconds: float = Field(default=0.0, ge=0)
    source_control_mode: str = "custom"
    source_enable: HeatingServiceCallSetup
    source_disable: HeatingServiceCallSetup
    reported_source_state_binding_role: str | None = None
    heat_delivery_mode: str = "unmanaged"
    heat_delivery_actuator_binding_role: str | None = None
    heat_delivery_ownership: str = "device_owned"
    heat_delivery_assist_policy: str = "no_assist"
    heat_delivery_assist_target_celsius: float = 30.0
    diagnostic_policy: HeatingDiagnosticPolicy = Field(default_factory=HeatingDiagnosticPolicy)
    notification_policy: HeatingNotificationPolicy = Field(default_factory=HeatingNotificationPolicy)

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator(
        "target_temperature_celsius",
        "primary_measurement_max_age_seconds",
        "maximum_future_skew_seconds",
        "indeterminate_grace_period_seconds",
        "heating_turn_on_differential_celsius",
        "heating_turn_off_differential_celsius",
        "heat_demand_confirmation_seconds",
        "minimum_heating_on_seconds",
        "minimum_heating_off_seconds",
        "heat_delivery_assist_target_celsius",
    )
    @classmethod
    def numeric_values_must_be_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("heating numeric configuration must be finite")
        return value

    @model_validator(mode="after")
    def service_roles_must_match_supported_bindings(self) -> HeatingSetupPayload:
        if self.source_enable.target_binding_role != SOURCE_ENABLE_TARGET_ROLE:
            raise ValueError(f"source_enable target must use {SOURCE_ENABLE_TARGET_ROLE}")
        if self.source_disable.target_binding_role != SOURCE_DISABLE_TARGET_ROLE:
            raise ValueError(f"source_disable target must use {SOURCE_DISABLE_TARGET_ROLE}")
        if self.reported_source_state_binding_role not in {None, REPORTED_SOURCE_STATE_ROLE}:
            raise ValueError(f"reported source state must use {REPORTED_SOURCE_STATE_ROLE}")
        if self.source_control_mode not in {"simple", "custom"}:
            raise ValueError("source_control_mode must be simple or custom")
        if self.source_control_mode == "simple":
            if (self.source_enable.domain, self.source_enable.service) != ("switch", "turn_on"):
                raise ValueError("simple source_enable must use switch.turn_on")
            if (self.source_disable.domain, self.source_disable.service) != ("switch", "turn_off"):
                raise ValueError("simple source_disable must use switch.turn_off")
        if self.reported_source_state_binding_role is not None and self.source_control_mode != "simple":
            raise ValueError("reported source state is currently supported only for simple source control")
        if self.heat_delivery_mode not in {"unmanaged", "setpoint_assist"}:
            raise ValueError("heat_delivery_mode must be unmanaged or setpoint_assist")
        if self.heat_delivery_ownership not in {"device_owned", "controlel_owned"}:
            raise ValueError("heat_delivery_ownership is invalid")
        if self.heat_delivery_assist_policy not in {"no_assist", "always_assist_while_heating"}:
            raise ValueError("heat_delivery_assist_policy is invalid")
        if self.heat_delivery_mode == "setpoint_assist":
            if self.heat_delivery_actuator_binding_role != HEAT_DELIVERY_ACTUATOR_ROLE:
                raise ValueError(f"setpoint_assist requires {HEAT_DELIVERY_ACTUATOR_ROLE}")
            if self.heat_delivery_ownership != "controlel_owned":
                raise ValueError("setpoint_assist requires Controlel ownership")
        elif self.heat_delivery_actuator_binding_role is not None:
            raise ValueError("unmanaged heat delivery cannot select an actuator binding")
        return self


class HeatingSetupAdapter:
    """Validate and canonicalize only Heating-owned setup semantics."""

    module_key = "heating"
    module_schema_version = HEATING_SETUP_SCHEMA_VERSION
    validator_policy_version = 3
    recommendation_policy_version = HEATING_RECOMMENDATION_POLICY_VERSION
    required_roles = frozenset(
        {
            PRIMARY_TEMPERATURE_ROLE,
            SOURCE_ENABLE_TARGET_ROLE,
            SOURCE_DISABLE_TARGET_ROLE,
        }
    )
    supported_roles = frozenset(
        {
            *required_roles,
            REPORTED_SOURCE_STATE_ROLE,
            HEAT_DELIVERY_ACTUATOR_ROLE,
        }
    )

    def recommend(
        self,
        snapshot: DiscoverySnapshot,
        *,
        preferred_area_id: str | None = None,
        preferred_floor_id: str | None = None,
    ) -> HeatingRecommendationSet:
        """Derive transparent snapshot-local advice without selecting a binding."""

        snapshot_fingerprint = snapshot.content_fingerprint
        if snapshot_fingerprint is None:
            raise ValueError("validated discovery snapshot has no content fingerprint")
        recommendations: list[HeatingRoleRecommendation] = []
        for role in sorted(self.supported_roles):
            candidates = tuple(
                sorted(
                    (
                        candidate
                        for reference in snapshot.objects
                        if (
                            candidate := _heating_candidate(
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
            recommended = next(
                (
                    candidate
                    for candidate in candidates
                    if "command.custom_service_target.unverified" not in candidate.capabilities
                ),
                None,
            )
            alternatives = tuple(
                candidate
                for candidate in candidates
                if recommended is None or candidate.candidate_id != recommended.candidate_id
            )
            recommendations.append(
                HeatingRoleRecommendation(
                    role=role,
                    recommended_candidate=recommended,
                    alternatives=alternatives,
                    confidence=recommended.confidence if recommended is not None else None,
                    reason_codes=recommended.reason_codes if recommended is not None else (),
                )
            )
        return HeatingRecommendationSet(
            snapshot_id=snapshot.snapshot_id,
            snapshot_content_fingerprint=snapshot_fingerprint,
            provider=snapshot.provider,
            provider_instance_id=snapshot.provider_instance_id,
            recommendations=tuple(recommendations),
        )

    def create_draft_from_recommendations(
        self,
        recommendations: HeatingRecommendationSet,
        *,
        selected_candidate_ids: Mapping[str, str],
        explicitly_confirmed_roles: Collection[str],
        draft_id: str,
        environment_id: str,
        module_instance_id: str,
        created_at: datetime,
        settings: Mapping[str, object],
        base_active_revision_id: str | None = None,
    ) -> DraftRevision:
        """Persist only explicit selections; a recommendation never confirms itself."""

        if (
            recommendations.module_schema_version != self.module_schema_version
            or recommendations.recommendation_policy_version != self.recommendation_policy_version
        ):
            raise ValueError("Heating recommendation contract is not supported by this adapter")
        unknown_confirmations = set(explicitly_confirmed_roles) - set(selected_candidate_ids)
        if unknown_confirmations:
            raise ValueError("cannot confirm a Heating role that was not explicitly selected")
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
            settings=settings,
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
        discovery_snapshot: DiscoverySnapshot | None = None,
        reference_resolver: ProviderReferenceResolver | None = None,
        discovery_snapshot_id: str | None = None,
        resolution_generation: int | None = None,
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        supported_contract = (
            draft.module_key == self.module_key and draft.module_schema_version == self.module_schema_version
        )
        if not supported_contract:
            policy_less_schema = (
                draft.module_key == self.module_key
                and draft.module_schema_version == POLICY_LESS_HEATING_SETUP_SCHEMA_VERSION
            )
            issues.append(
                _issue(
                    (
                        "heating.policy_less_schema_v1_requires_recanonicalization"
                        if policy_less_schema
                        else "heating.unsupported_module_contract"
                    ),
                    ("module_schema_version",),
                    (
                        "setup.heating.policy_less_schema_v1_requires_recanonicalization"
                        if policy_less_schema
                        else "setup.heating.unsupported_module_contract"
                    ),
                    parameters={
                        "actual_module_schema_version": draft.module_schema_version,
                        "required_module_schema_version": self.module_schema_version,
                    },
                    suggested_action=(
                        "create_explicit_policy_bearing_schema_v2_draft"
                        if policy_less_schema
                        else "use_supported_heating_module_contract"
                    ),
                )
            )
        normalized: HeatingSetupPayload | None = None
        if supported_contract:
            try:
                normalized = HeatingSetupPayload.model_validate(draft.settings)
            except ValidationError as error:
                for detail in error.errors(include_url=False):
                    issues.append(
                        ValidationIssue(
                            code="heating.invalid_setting",
                            severity=ValidationSeverity.ERROR,
                            path=tuple(str(part) for part in detail["loc"]),
                            message_key="setup.heating.invalid_setting",
                            parameters={"error_type": detail["type"]},
                        )
                    )
        required_roles = set(self.required_roles)
        if normalized is not None and normalized.heat_delivery_mode == "setpoint_assist":
            required_roles.add(HEAT_DELIVERY_ACTUATOR_ROLE)
        if normalized is not None and normalized.reported_source_state_binding_role is not None:
            required_roles.add(REPORTED_SOURCE_STATE_ROLE)
        bindings_by_role = {binding.role: binding for binding in draft.bindings}
        unsupported_roles = set(bindings_by_role) - set(self.supported_roles)
        for role in sorted(unsupported_roles):
            issues.append(
                _issue(
                    "heating.unsupported_binding_role",
                    ("bindings", role),
                    "setup.heating.unsupported_binding_role",
                    role=role,
                )
            )
        roles_requiring_confirmation = required_roles | (set(self.supported_roles) & set(bindings_by_role))
        for role in sorted(roles_requiring_confirmation):
            binding = bindings_by_role.get(role)
            if binding is None:
                issues.append(
                    _issue(
                        "heating.required_binding_missing",
                        ("bindings", role),
                        "setup.heating.required_binding_missing",
                        role=role,
                    )
                )
            elif not binding.user_confirmed:
                issues.append(
                    _issue(
                        "heating.binding_confirmation_required",
                        ("bindings", role),
                        "setup.heating.binding_confirmation_required",
                        role=role,
                    )
                )
        if normalized is not None and normalized.source_control_mode == "simple":
            source_bindings = tuple(
                bindings_by_role.get(role) for role in (SOURCE_ENABLE_TARGET_ROLE, SOURCE_DISABLE_TARGET_ROLE)
            )
            if all(binding is not None for binding in source_bindings):
                enable_binding, disable_binding = source_bindings
                assert enable_binding is not None and disable_binding is not None
                if enable_binding.reference.semantic_data() != disable_binding.reference.semantic_data():
                    issues.append(
                        _issue(
                            "heating.simple_source_binding_mismatch",
                            ("bindings", SOURCE_DISABLE_TARGET_ROLE),
                            "setup.heating.simple_source_binding_mismatch",
                            role=SOURCE_DISABLE_TARGET_ROLE,
                        )
                    )
                reported_binding = bindings_by_role.get(REPORTED_SOURCE_STATE_ROLE)
                if (
                    normalized.reported_source_state_binding_role is not None
                    and reported_binding is not None
                    and reported_binding.reference.semantic_data() != enable_binding.reference.semantic_data()
                ):
                    issues.append(
                        _issue(
                            "heating.reported_source_binding_mismatch",
                            ("bindings", REPORTED_SOURCE_STATE_ROLE),
                            "setup.heating.reported_source_binding_mismatch",
                            role=REPORTED_SOURCE_STATE_ROLE,
                        )
                    )
        effective_snapshot_id = discovery_snapshot_id
        if discovery_snapshot is not None:
            effective_snapshot_id = discovery_snapshot.snapshot_id
            if discovery_snapshot_id is not None and discovery_snapshot_id != discovery_snapshot.snapshot_id:
                issues.append(
                    _issue(
                        "heating.discovery_snapshot_mismatch",
                        ("discovery_snapshot_id",),
                        "setup.heating.discovery_snapshot_mismatch",
                        parameters={
                            "expected": discovery_snapshot.snapshot_id,
                            "provided": discovery_snapshot_id,
                        },
                    )
                )
            if reference_resolver is None:
                issues.append(
                    _issue(
                        "heating.reference_resolver_unavailable",
                        ("bindings",),
                        "setup.heating.reference_resolver_unavailable",
                    )
                )
            else:
                for binding in sorted(draft.bindings, key=lambda item: item.role):
                    if binding.role not in self.supported_roles:
                        continue
                    resolution = reference_resolver.resolve(binding.reference, discovery_snapshot)
                    issues.extend(
                        _resolution_issues(
                            binding,
                            resolution,
                            normalized=normalized,
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
            discovery_snapshot_id=effective_snapshot_id,
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
        if draft.module_key != self.module_key or draft.module_schema_version != self.module_schema_version:
            if (
                draft.module_key == self.module_key
                and draft.module_schema_version == POLICY_LESS_HEATING_SETUP_SCHEMA_VERSION
            ):
                raise ValueError(
                    "policy-less Heating schema version 1 requires explicit migration or recanonicalization"
                )
            raise ValueError("Heating draft uses an unsupported module contract")
        if report.validator_policy_version != self.validator_policy_version:
            raise ValueError(
                f"Heating canonicalization requires validator policy version {self.validator_policy_version}"
            )
        normalized = HeatingSetupPayload.model_validate(draft.settings)
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
            logical_identities={"sensor_id": normalized.sensor_id, "zone_id": normalized.zone_id},
        )


def _heating_candidate(
    snapshot: DiscoverySnapshot,
    role: str,
    reference: ProviderReference,
    *,
    preferred_area_id: str | None,
    preferred_floor_id: str | None,
) -> HeatingSetupCandidate | None:
    classification = _classify_candidate(role, reference)
    if classification is None:
        return None
    confidence, capabilities, reasons = classification
    evidence: dict[str, object] = {
        "domain": _reference_domain(reference),
        "device_class": _evidence_string(reference, "device_class"),
        "original_device_class": _evidence_string(reference, "original_device_class"),
        "unit_of_measurement": _evidence_string(reference, "unit_of_measurement"),
        "supported_features": _supported_features(reference),
        "area_id": reference.area_id,
        "floor_id": reference.floor_id,
    }
    reason_codes = list(reasons)
    if preferred_area_id is not None:
        area_match = reference.area_id == preferred_area_id
        evidence["preferred_area_id"] = preferred_area_id
        evidence["preferred_area_match"] = area_match
        if area_match:
            reason_codes.append("heating.candidate.preferred_area_match")
    if preferred_floor_id is not None:
        floor_match = reference.floor_id == preferred_floor_id
        evidence["preferred_floor_id"] = preferred_floor_id
        evidence["preferred_floor_match"] = floor_match
        if floor_match:
            reason_codes.append("heating.candidate.preferred_floor_match")
    snapshot_fingerprint = snapshot.content_fingerprint
    if snapshot_fingerprint is None:
        raise ValueError("validated discovery snapshot has no content fingerprint")
    candidate_id = hashlib.sha256(
        canonical_json(
            {
                "snapshot_content_fingerprint": snapshot_fingerprint,
                "role": role,
                "reference": reference.document_data(),
                "recommendation_policy_version": HEATING_RECOMMENDATION_POLICY_VERSION,
            }
        ).encode("utf-8")
    ).hexdigest()
    return HeatingSetupCandidate(
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
) -> tuple[RecommendationConfidence, tuple[str, ...], tuple[str, ...]] | None:
    domain = _reference_domain(reference)
    if role == PRIMARY_TEMPERATURE_ROLE:
        if reference.object_kind != _HA_ENTITY_KIND or domain != "sensor":
            return None
        device_classes = {
            value
            for field in ("device_class", "original_device_class")
            if (value := _evidence_string(reference, field)) is not None
        }
        if "temperature" in device_classes:
            return (
                RecommendationConfidence.HIGH,
                ("measurement.temperature",),
                ("heating.candidate.temperature_device_class",),
            )
        if _is_temperature_unit(_evidence_string(reference, "unit_of_measurement")):
            return (
                RecommendationConfidence.MEDIUM,
                ("measurement.temperature",),
                ("heating.candidate.temperature_unit",),
            )
        locator = (reference.current_locator or "").lower()
        if "temperature" in locator or locator.endswith("_temp"):
            return (
                RecommendationConfidence.LOW,
                ("measurement.temperature.unverified",),
                ("heating.candidate.temperature_locator_hint",),
            )
        return None
    if role in {SOURCE_ENABLE_TARGET_ROLE, SOURCE_DISABLE_TARGET_ROLE}:
        if reference.object_kind == _HA_ENDPOINT_KIND and reference.identity_quality is IdentityQuality.EPHEMERAL:
            return (
                RecommendationConfidence.LOW,
                ("command.custom_service_target.unverified",),
                ("heating.candidate.ephemeral_custom_service_target",),
            )
        if reference.object_kind != _HA_ENTITY_KIND:
            return None
        if domain == "switch":
            return (
                RecommendationConfidence.HIGH,
                ("command.enable_disable",),
                ("heating.candidate.switch_enable_disable",),
            )
        if domain in {"climate", "water_heater"}:
            return (
                RecommendationConfidence.MEDIUM,
                ("command.custom_service_target",),
                ("heating.candidate.external_service_target",),
            )
        return (
            RecommendationConfidence.LOW,
            ("command.custom_service_target.unverified",),
            ("heating.candidate.external_service_target_unverified",),
        )
    if role == REPORTED_SOURCE_STATE_ROLE:
        if reference.object_kind != _HA_ENTITY_KIND:
            return None
        if domain is None:
            return None
        confidence = {
            "switch": RecommendationConfidence.HIGH,
            "binary_sensor": RecommendationConfidence.MEDIUM,
            "input_boolean": RecommendationConfidence.LOW,
        }.get(domain)
        if confidence is None:
            return None
        return (
            confidence,
            ("state.binary",),
            (f"heating.candidate.reported_state_{domain}",),
        )
    if role == HEAT_DELIVERY_ACTUATOR_ROLE:
        if (
            reference.object_kind == _HA_ENTITY_KIND
            and domain == "climate"
            and _supported_features(reference) & _CLIMATE_TARGET_TEMPERATURE_FEATURE
        ):
            return (
                RecommendationConfidence.HIGH,
                ("command.target_temperature",),
                ("heating.candidate.climate_target_temperature",),
            )
    return None


def _candidate_sort_key(
    candidate: HeatingSetupCandidate,
    *,
    preferred_area_id: str | None,
    preferred_floor_id: str | None,
) -> tuple[int, int, int, str, str, str]:
    confidence_rank = {
        RecommendationConfidence.HIGH: 0,
        RecommendationConfidence.MEDIUM: 1,
        RecommendationConfidence.LOW: 2,
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


def _resolution_issues(
    binding: BindingSelection,
    resolution: ProviderReferenceResolution,
    *,
    normalized: HeatingSetupPayload | None,
) -> tuple[ValidationIssue, ...]:
    role = binding.role
    status = resolution.status
    if status is ReferenceResolutionStatus.EPHEMERAL:
        if (
            role in {SOURCE_ENABLE_TARGET_ROLE, SOURCE_DISABLE_TARGET_ROLE}
            and normalized is not None
            and normalized.source_control_mode == "custom"
        ):
            return (
                _issue(
                    "heating.ephemeral_custom_service_target",
                    ("bindings", role),
                    "setup.heating.ephemeral_custom_service_target",
                    role=role,
                    severity=ValidationSeverity.WARNING,
                    evidence={"resolution_status": status.value},
                    suggested_action="confirm_external_service_target_stability",
                ),
            )
        return (
            _issue(
                "heating.ephemeral_important_binding",
                ("bindings", role),
                "setup.heating.ephemeral_important_binding",
                role=role,
                evidence={"resolution_status": status.value},
                suggested_action="select_registered_entity",
            ),
        )
    if status is not ReferenceResolutionStatus.RESOLVED:
        code_by_status = {
            ReferenceResolutionStatus.MISSING: "heating.binding_missing",
            ReferenceResolutionStatus.RECOVERY_CANDIDATE: "heating.binding_recovery_requires_confirmation",
            ReferenceResolutionStatus.AMBIGUOUS: "heating.binding_ambiguous",
            ReferenceResolutionStatus.ENVIRONMENT_MISMATCH: "heating.binding_environment_mismatch",
        }
        code = code_by_status.get(status, "heating.binding_unsupported_resolution")
        return (
            _issue(
                code,
                ("bindings", role),
                f"setup.{code}",
                role=role,
                evidence={
                    "resolution_status": status.value,
                    "recovery_candidate_ids": [
                        candidate.reference.native_id for candidate in resolution.recovery_candidates
                    ],
                },
                suggested_action="review_binding_resolution",
            ),
        )
    resolved = resolution.resolved_reference
    if resolved is None:
        raise ValueError("RESOLVED provider result did not carry a reference")
    issues = list(_capability_issues(role, resolved, normalized=normalized))
    if binding.reference.area_id != resolved.area_id or binding.reference.floor_id != resolved.floor_id:
        issues.append(
            _issue(
                "heating.binding_topology_changed",
                ("bindings", role),
                "setup.heating.binding_topology_changed",
                role=role,
                severity=ValidationSeverity.WARNING,
                evidence={
                    "selected_area_id": binding.reference.area_id,
                    "current_area_id": resolved.area_id,
                    "selected_floor_id": binding.reference.floor_id,
                    "current_floor_id": resolved.floor_id,
                },
                suggested_action="review_current_area_and_floor",
            )
        )
    return tuple(issues)


def _capability_issues(
    role: str,
    reference: ProviderReference,
    *,
    normalized: HeatingSetupPayload | None,
) -> tuple[ValidationIssue, ...]:
    domain = _reference_domain(reference)
    if role == PRIMARY_TEMPERATURE_ROLE:
        advertised_temperature = "temperature" in {
            value
            for field in ("device_class", "original_device_class")
            if (value := _evidence_string(reference, field)) is not None
        } or _is_temperature_unit(_evidence_string(reference, "unit_of_measurement"))
        if reference.object_kind != _HA_ENTITY_KIND or domain != "sensor" or not advertised_temperature:
            return (_capability_error(role, "measurement.temperature"),)
    elif role in {SOURCE_ENABLE_TARGET_ROLE, SOURCE_DISABLE_TARGET_ROLE}:
        if normalized is not None and normalized.source_control_mode == "simple":
            if reference.object_kind != _HA_ENTITY_KIND or domain != "switch":
                return (_capability_error(role, "command.enable_disable"),)
        elif reference.object_kind != _HA_ENTITY_KIND:
            return (_capability_error(role, "command.custom_service_target"),)
        elif domain != "switch":
            return (
                _issue(
                    "heating.custom_service_target_capability_unverified",
                    ("bindings", role),
                    "setup.heating.custom_service_target_capability_unverified",
                    role=role,
                    severity=ValidationSeverity.WARNING,
                    evidence={"domain": domain},
                    suggested_action="verify_external_service_contract",
                ),
            )
    elif role == REPORTED_SOURCE_STATE_ROLE:
        if reference.object_kind != _HA_ENTITY_KIND or domain not in {"switch", "binary_sensor", "input_boolean"}:
            return (_capability_error(role, "state.binary"),)
    elif role == HEAT_DELIVERY_ACTUATOR_ROLE:
        if (
            reference.object_kind != _HA_ENTITY_KIND
            or domain != "climate"
            or not (_supported_features(reference) & _CLIMATE_TARGET_TEMPERATURE_FEATURE)
        ):
            return (_capability_error(role, "command.target_temperature"),)
    return ()


def _capability_error(role: str, required_capability: str) -> ValidationIssue:
    return _issue(
        "heating.binding_capability_unsuitable",
        ("bindings", role),
        "setup.heating.binding_capability_unsuitable",
        role=role,
        parameters={"required_capability": required_capability},
        suggested_action="select_suitable_binding",
    )


def _reference_domain(reference: ProviderReference) -> str | None:
    return _evidence_string(reference, "domain")


def _evidence_string(reference: ProviderReference, key: str) -> str | None:
    value = reference.recovery_evidence.get(key)
    return value if isinstance(value, str) and value else None


def _supported_features(reference: ProviderReference) -> int:
    value = reference.recovery_evidence.get("supported_features", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _is_temperature_unit(value: str | None) -> bool:
    return value in {"°C", "°F", "K", "C", "F", "celsius", "fahrenheit", "kelvin"}


def _finite_configured_duration(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a finite number of seconds")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{label} must be a finite number of seconds")
    return result


def _issue(
    code: str,
    path: tuple[str, ...],
    message_key: str,
    *,
    role: str | None = None,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
    parameters: Mapping[str, object] | None = None,
    evidence: Mapping[str, object] | None = None,
    suggested_action: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=severity,
        path=path,
        module_role=role,
        message_key=message_key,
        parameters=parameters or {},
        evidence=evidence or {},
        suggested_action=suggested_action,
    )
