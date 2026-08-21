"""First module adapter for the module-neutral Setup v0.1 kernel."""

from __future__ import annotations

from datetime import datetime
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from controlel.application.setup.model import (
    CanonicalConfigurationRevision,
    DraftRevision,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
    ValidationSubjectKind,
)

HEATING_SETUP_SCHEMA_VERSION = 1
PRIMARY_TEMPERATURE_ROLE = "heating.primary_temperature"
SOURCE_ENABLE_TARGET_ROLE = "heating.source.enable_target"
SOURCE_DISABLE_TARGET_ROLE = "heating.source.disable_target"
HEAT_DELIVERY_ACTUATOR_ROLE = "heating.heat_delivery.actuator"


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


class HeatingSetupPayload(BaseModel):
    """Small normalized Heating v1 payload with canonical units."""

    zone_id: str = Field(min_length=1)
    zone_name: str = Field(min_length=1)
    sensor_id: str = Field(min_length=1)
    sensor_name: str = Field(min_length=1)
    target_temperature_celsius: float
    primary_measurement_max_age_seconds: float = Field(gt=0)
    maximum_future_skew_seconds: float = Field(ge=0)
    indeterminate_grace_period_seconds: float = Field(ge=0)
    indeterminate_timeout_action: str = "disable_heating"
    heating_turn_on_differential_celsius: float = Field(default=0.0, ge=0)
    heating_turn_off_differential_celsius: float = Field(default=0.0, ge=0)
    heat_demand_confirmation_seconds: float = Field(default=0.0, ge=0)
    minimum_heating_on_seconds: float = Field(default=0.0, ge=0)
    minimum_heating_off_seconds: float = Field(default=0.0, ge=0)
    source_control_mode: str = "custom"
    source_enable: HeatingServiceCallSetup
    source_disable: HeatingServiceCallSetup
    heat_delivery_mode: str = "unmanaged"
    heat_delivery_actuator_binding_role: str | None = None
    heat_delivery_ownership: str = "device_owned"
    heat_delivery_assist_policy: str = "no_assist"
    heat_delivery_assist_target_celsius: float = 30.0

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
        if self.source_control_mode not in {"simple", "custom"}:
            raise ValueError("source_control_mode must be simple or custom")
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
    validator_policy_version = 1
    required_roles = frozenset(
        {
            PRIMARY_TEMPERATURE_ROLE,
            SOURCE_ENABLE_TARGET_ROLE,
            SOURCE_DISABLE_TARGET_ROLE,
        }
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
        if draft.module_key != self.module_key or draft.module_schema_version != self.module_schema_version:
            issues.append(
                _issue(
                    "heating.unsupported_module_contract",
                    ("module_schema_version",),
                    "setup.heating.unsupported_module_contract",
                )
            )
        normalized: HeatingSetupPayload | None = None
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
        bindings_by_role = {binding.role: binding for binding in draft.bindings}
        roles_requiring_confirmation = required_roles | ({HEAT_DELIVERY_ACTUATOR_ROLE} & set(bindings_by_role))
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


def _issue(code: str, path: tuple[str, ...], message_key: str, *, role: str | None = None) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=ValidationSeverity.ERROR,
        path=path,
        module_role=role,
        message_key=message_key,
    )
