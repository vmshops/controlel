"""Versioned setup adapter for the Water Safety v1 module."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from controlel.application.setup.json_data import canonical_json
from controlel.application.setup.model import (
    CanonicalConfigurationRevision,
    DraftRevision,
    IdentityQuality,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
    ValidationSubjectKind,
)

WATER_SAFETY_MODULE_KEY = "water_safety"
WATER_SAFETY_SETUP_SCHEMA_VERSION = 1
WATER_SAFETY_VALIDATOR_POLICY_VERSION = 1
WATER_SAFETY_SENSOR_ROLE = "water_safety.moisture_sensor"
NOTIFICATION_ROLE_PREFIX = "water_safety.notification."
SIREN_ROLE_PREFIX = "water_safety.siren."
MAX_NOTIFICATION_TARGETS = 16
MAX_SIREN_TARGETS = 16
MAX_MESSAGE_LENGTH = 2_000
MAX_UNAVAILABLE_GRACE_SECONDS = 86_400.0
MAX_FAULT_REPEAT_SECONDS = 604_800.0


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

    @model_validator(mode="after")
    def output_roles_must_not_overlap(self) -> WaterSafetySetupPayload:
        if set(self.notification_target_roles) & set(self.siren_target_roles):
            raise ValueError("notification and siren roles must not overlap")
        return self


class WaterSafetySetupAdapter:
    """Validate and canonicalize only Water Safety-owned setup semantics."""

    module_key = WATER_SAFETY_MODULE_KEY
    module_schema_version = WATER_SAFETY_SETUP_SCHEMA_VERSION
    validator_policy_version = WATER_SAFETY_VALIDATOR_POLICY_VERSION

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
