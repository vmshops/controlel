"""Deterministic one-way conversion of legacy Heating configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from controlel.application.configuration.heating_setup_adapter import (
    HEAT_DELIVERY_ACTUATOR_ROLE,
    HEATING_SETUP_SCHEMA_VERSION,
    PRIMARY_TEMPERATURE_ROLE,
    REPORTED_SOURCE_STATE_ROLE,
    SOURCE_DISABLE_TARGET_ROLE,
    SOURCE_ENABLE_TARGET_ROLE,
    HeatingDiagnosticPolicy,
    HeatingNotificationPolicy,
    HeatingNotificationRecipient,
    HeatingServiceCallSetup,
    HeatingSetupAdapter,
    HeatingSetupPayload,
)
from controlel.application.setup import (
    BindingSelection,
    CanonicalConfigurationRevision,
    DraftRevision,
    IdentityQuality,
    ProviderReference,
    SelectionOrigin,
    ValidationReport,
)

from .config import HomeAssistantIntegrationConfig, HomeAssistantServiceCall
from .const import CONTROL_MODE_CUSTOM, CONTROL_MODE_SIMPLE

_HOME_ASSISTANT_PROVIDER = "home_assistant"
_HOME_ASSISTANT_ENDPOINT_KIND = "home_assistant.endpoint"
_MIGRATION_CONTRACT = "home_assistant_integration_config_to_heating_v2"


class LegacyHeatingConversionError(ValueError):
    """Raised when a legacy value cannot be represented exactly by Heating v2."""


class LegacyHeatingConversionResult(BaseModel):
    """A validated canonical revision that has deliberately not been activated."""

    canonical_revision: CanonicalConfigurationRevision
    validation_report: ValidationReport
    activated: Literal[False] = False

    model_config = ConfigDict(frozen=True, extra="forbid")


# This table is both documentation and a completeness guard for the legacy dataclass.
# One legacy field may intentionally contribute to more than one canonical location.
LEGACY_FIELD_MAPPINGS: Mapping[str, tuple[str, ...]] = {
    "sensor_id": ("module_payload.sensor_id", "logical_identities.sensor_id"),
    "sensor_name": ("module_payload.sensor_name",),
    "temperature_entity_id": (f"bindings.{PRIMARY_TEMPERATURE_ROLE}",),
    "zone_id": ("module_payload.zone_id", "logical_identities.zone_id"),
    "zone_name": ("module_payload.zone_name",),
    "target_temperature": ("module_payload.target_temperature_celsius",),
    "heating_turn_on_differential": ("module_payload.heating_turn_on_differential_celsius",),
    "heating_turn_off_differential": ("module_payload.heating_turn_off_differential_celsius",),
    "minimum_heating_on_time": ("module_payload.minimum_heating_on_seconds",),
    "minimum_heating_off_time": ("module_payload.minimum_heating_off_seconds",),
    "primary_measurement_max_age": ("module_payload.primary_measurement_max_age_seconds",),
    "max_future_skew": ("module_payload.maximum_future_skew_seconds",),
    "indeterminate_grace_period": ("module_payload.indeterminate_grace_period_seconds",),
    "indeterminate_timeout_action": ("module_payload.indeterminate_timeout_action",),
    "heat_source": (
        "module_payload.source_enable",
        "module_payload.source_disable",
        f"bindings.{SOURCE_ENABLE_TARGET_ROLE}",
        f"bindings.{SOURCE_DISABLE_TARGET_ROLE}",
    ),
    "heat_source_control_mode": ("module_payload.source_control_mode",),
    "controlled_entity_id": (
        "module_payload.reported_source_state_binding_role",
        f"bindings.{REPORTED_SOURCE_STATE_ROLE}",
    ),
    "diagnostic_profile": ("module_payload.diagnostic_policy.diagnostic_profile",),
    "debug_duration": ("module_payload.diagnostic_policy.debug_until_changed",),
    "configured_debug_duration": ("module_payload.diagnostic_policy.configured_debug_duration_seconds",),
    "diagnostic_profile_before_debug": ("module_payload.diagnostic_policy.diagnostic_profile_before_debug",),
    "heat_demand_confirmation_duration": ("module_payload.heat_demand_confirmation_seconds",),
    "heat_delivery_mode": ("module_payload.heat_delivery_mode",),
    "heat_delivery_actuator_entity_id": (
        "module_payload.heat_delivery_actuator_binding_role",
        f"bindings.{HEAT_DELIVERY_ACTUATOR_ROLE}",
    ),
    "heat_delivery_ownership": ("module_payload.heat_delivery_ownership",),
    "heat_delivery_assist_policy": ("module_payload.heat_delivery_assist_policy",),
    "heat_delivery_assist_target": ("module_payload.heat_delivery_assist_target_celsius",),
    "notification_policy": ("module_payload.notification_policy",),
}


def convert_legacy_heating_config(
    legacy: HomeAssistantIntegrationConfig,
    *,
    environment_id: str,
    provider_instance_id: str,
    module_instance_id: str,
    configuration_id: str,
    revision_id: str,
    created_at: datetime,
    core_version: str,
    integration_version: str | None,
    revision: int = 1,
    parent_revision_id: str | None = None,
) -> LegacyHeatingConversionResult:
    """Convert one effective legacy config without persistence or activation.

    Legacy entity IDs do not prove Home Assistant registry identity. Converted
    references therefore preserve the exact locator with truthful EPHEMERAL
    identity until a later, explicit binding review resolves them.
    """

    _assert_mapping_is_complete()
    debug_until_changed = _debug_until_changed(legacy)
    source_mode, source_bindings, reported_role = _source_configuration(
        legacy,
        provider_instance_id=provider_instance_id,
    )
    heat_delivery_bindings, actuator_role = _heat_delivery_configuration(
        legacy,
        provider_instance_id=provider_instance_id,
    )
    bindings = (
        _migrated_binding(
            PRIMARY_TEMPERATURE_ROLE,
            legacy.temperature_entity_id,
            provider_instance_id=provider_instance_id,
            source_field="temperature_entity_id",
        ),
        *source_bindings,
        *heat_delivery_bindings,
    )
    diagnostic_policy = HeatingDiagnosticPolicy(
        diagnostic_profile=legacy.diagnostic_profile,  # type: ignore[arg-type]
        configured_debug_duration_seconds=_exact_seconds(
            legacy.configured_debug_duration,
            "configured_debug_duration",
        ),
        debug_until_changed=debug_until_changed,
        diagnostic_profile_before_debug=legacy.diagnostic_profile_before_debug,  # type: ignore[arg-type]
    )
    notification_policy = HeatingNotificationPolicy(
        enabled=legacy.notification_policy.enabled,
        recipients=tuple(
            HeatingNotificationRecipient(
                recipient_id=recipient.recipient_id,
                transport=recipient.transport,  # type: ignore[arg-type]
                target=recipient.target,
                enabled=recipient.enabled,
                minimum_level=recipient.minimum_level,
                categories=recipient.categories,
            )
            for recipient in legacy.notification_policy.recipients
        ),
        maximum_per_window=legacy.notification_policy.maximum_per_window,
        rate_window_seconds=_exact_seconds(legacy.notification_policy.rate_window, "notification rate_window"),
        critical_maximum_per_window=legacy.notification_policy.critical_maximum_per_window,
        critical_rate_window_seconds=_exact_seconds(
            legacy.notification_policy.critical_rate_window,
            "notification critical_rate_window",
        ),
        history_capacity=legacy.notification_policy.history_capacity,
    )
    payload = HeatingSetupPayload(
        zone_id=legacy.zone_id.value,
        zone_name=legacy.zone_name,
        sensor_id=legacy.sensor_id.value,
        sensor_name=legacy.sensor_name,
        target_temperature_celsius=legacy.target_temperature.value,
        primary_measurement_max_age_seconds=_exact_seconds(
            legacy.primary_measurement_max_age,
            "primary_measurement_max_age",
        ),
        maximum_future_skew_seconds=_exact_seconds(legacy.max_future_skew, "max_future_skew"),
        indeterminate_grace_period_seconds=_exact_seconds(
            legacy.indeterminate_grace_period,
            "indeterminate_grace_period",
        ),
        indeterminate_timeout_action=legacy.indeterminate_timeout_action,
        heating_turn_on_differential_celsius=legacy.heating_turn_on_differential,
        heating_turn_off_differential_celsius=legacy.heating_turn_off_differential,
        heat_demand_confirmation_seconds=_exact_seconds(
            legacy.heat_demand_confirmation_duration,
            "heat_demand_confirmation_duration",
        ),
        minimum_heating_on_seconds=_exact_seconds(legacy.minimum_heating_on_time, "minimum_heating_on_time"),
        minimum_heating_off_seconds=_exact_seconds(legacy.minimum_heating_off_time, "minimum_heating_off_time"),
        source_control_mode=source_mode,
        source_enable=_service_call(legacy.heat_source.enable_heating, SOURCE_ENABLE_TARGET_ROLE),
        source_disable=_service_call(legacy.heat_source.disable_heating, SOURCE_DISABLE_TARGET_ROLE),
        reported_source_state_binding_role=reported_role,
        heat_delivery_mode=legacy.heat_delivery_mode,
        heat_delivery_actuator_binding_role=actuator_role,
        heat_delivery_ownership=legacy.heat_delivery_ownership,
        heat_delivery_assist_policy=legacy.heat_delivery_assist_policy,
        heat_delivery_assist_target_celsius=legacy.heat_delivery_assist_target,
        diagnostic_policy=diagnostic_policy,
        notification_policy=notification_policy,
    )
    migration_provenance = {
        "conversion_contract": _MIGRATION_CONTRACT,
        "legacy_contract": HomeAssistantIntegrationConfig.__name__,
        "legacy_field_count": len(LEGACY_FIELD_MAPPINGS),
        "target_module_schema_version": HEATING_SETUP_SCHEMA_VERSION,
        "validator_policy_version": HeatingSetupAdapter.validator_policy_version,
    }
    draft = DraftRevision(
        draft_id=f"legacy-migration:{revision_id}",
        revision=1,
        environment_id=environment_id,
        module_key=HeatingSetupAdapter.module_key,
        module_instance_id=module_instance_id,
        module_schema_version=HEATING_SETUP_SCHEMA_VERSION,
        created_at=created_at,
        updated_at=created_at,
        settings=payload.model_dump(mode="json"),
        bindings=bindings,
        lineage={"created_by_conversion_contract": _MIGRATION_CONTRACT},
        migration_provenance=migration_provenance,
    )
    adapter = HeatingSetupAdapter()
    report = adapter.validate(
        draft,
        report_id=f"legacy-migration-validation:{revision_id}",
        evaluated_at=created_at,
    )
    if not report.activation_ready:
        issue_paths = ", ".join(".".join(issue.path) or issue.code for issue in report.issues)
        raise LegacyHeatingConversionError(
            f"legacy configuration is not representable by Heating schema v2: {issue_paths}"
        )
    canonical = adapter.canonicalize(
        draft,
        report,
        configuration_id=configuration_id,
        revision_id=revision_id,
        revision=revision,
        provider=_HOME_ASSISTANT_PROVIDER,
        provider_instance_id=provider_instance_id,
        created_at=created_at,
        actor="system:migration",
        source="home_assistant_legacy_config",
        change_kind="MIGRATE",
        reason="legacy_to_canonical_heating_v2",
        core_version=core_version,
        integration_version=integration_version,
        parent_revision_id=parent_revision_id,
    )
    return LegacyHeatingConversionResult(
        canonical_revision=canonical,
        validation_report=report,
    )


def _assert_mapping_is_complete() -> None:
    actual = {field.name for field in fields(HomeAssistantIntegrationConfig)}
    declared = set(LEGACY_FIELD_MAPPINGS)
    if actual != declared:
        missing = ", ".join(sorted(actual - declared)) or "none"
        unknown = ", ".join(sorted(declared - actual)) or "none"
        raise LegacyHeatingConversionError(
            f"legacy field mapping is incomplete (missing: {missing}; unknown: {unknown})"
        )


def _debug_until_changed(legacy: HomeAssistantIntegrationConfig) -> bool:
    if legacy.debug_duration is None:
        return True
    if legacy.debug_duration != legacy.configured_debug_duration:
        raise LegacyHeatingConversionError(
            "debug_duration differs from configured_debug_duration and cannot be represented losslessly"
        )
    return False


def _source_configuration(
    legacy: HomeAssistantIntegrationConfig,
    *,
    provider_instance_id: str,
) -> tuple[str, tuple[BindingSelection, ...], str | None]:
    enable = legacy.heat_source.enable_heating
    disable = legacy.heat_source.disable_heating
    if legacy.heat_source_control_mode == CONTROL_MODE_SIMPLE:
        controlled = legacy.controlled_entity_id
        expected = (
            enable.domain == "switch"
            and enable.service == "turn_on"
            and disable.domain == "switch"
            and disable.service == "turn_off"
            and enable.target_entity_id == controlled
            and disable.target_entity_id == controlled
        )
        if controlled is None or not expected:
            raise LegacyHeatingConversionError(
                "simple source control fields disagree and cannot be represented losslessly"
            )
        reference = _ephemeral_reference(controlled, provider_instance_id=provider_instance_id)
        return (
            "simple",
            (
                _migrated_binding_from_reference(
                    SOURCE_ENABLE_TARGET_ROLE,
                    reference,
                    source_field="heat_source",
                ),
                _migrated_binding_from_reference(
                    SOURCE_DISABLE_TARGET_ROLE,
                    reference,
                    source_field="heat_source",
                ),
                _migrated_binding_from_reference(
                    REPORTED_SOURCE_STATE_ROLE,
                    reference,
                    source_field="controlled_entity_id",
                ),
            ),
            REPORTED_SOURCE_STATE_ROLE,
        )
    if legacy.heat_source_control_mode == CONTROL_MODE_CUSTOM:
        if legacy.controlled_entity_id is not None:
            raise LegacyHeatingConversionError(
                "custom source control with controlled_entity_id cannot be represented losslessly"
            )
        return (
            "custom",
            (
                _migrated_binding(
                    SOURCE_ENABLE_TARGET_ROLE,
                    enable.target_entity_id,
                    provider_instance_id=provider_instance_id,
                    source_field="heat_source",
                ),
                _migrated_binding(
                    SOURCE_DISABLE_TARGET_ROLE,
                    disable.target_entity_id,
                    provider_instance_id=provider_instance_id,
                    source_field="heat_source",
                ),
            ),
            None,
        )
    raise LegacyHeatingConversionError(
        f"unsupported legacy heat_source_control_mode: {legacy.heat_source_control_mode}"
    )


def _heat_delivery_configuration(
    legacy: HomeAssistantIntegrationConfig,
    *,
    provider_instance_id: str,
) -> tuple[tuple[BindingSelection, ...], str | None]:
    actuator = legacy.heat_delivery_actuator_entity_id
    if legacy.heat_delivery_mode == "unmanaged":
        if actuator is not None:
            raise LegacyHeatingConversionError(
                "unmanaged heat delivery with an actuator cannot be represented losslessly"
            )
        return (), None
    if legacy.heat_delivery_mode == "setpoint_assist":
        if actuator is None:
            raise LegacyHeatingConversionError("setpoint_assist has no actuator entity")
        return (
            (
                _migrated_binding(
                    HEAT_DELIVERY_ACTUATOR_ROLE,
                    actuator,
                    provider_instance_id=provider_instance_id,
                    source_field="heat_delivery_actuator_entity_id",
                ),
            ),
            HEAT_DELIVERY_ACTUATOR_ROLE,
        )
    raise LegacyHeatingConversionError(f"unsupported legacy heat_delivery_mode: {legacy.heat_delivery_mode}")


def _service_call(call: HomeAssistantServiceCall, role: str) -> HeatingServiceCallSetup:
    return HeatingServiceCallSetup(
        domain=call.domain,
        service=call.service,
        target_binding_role=role,
    )


def _migrated_binding(
    role: str,
    locator: str,
    *,
    provider_instance_id: str,
    source_field: str,
) -> BindingSelection:
    return _migrated_binding_from_reference(
        role,
        _ephemeral_reference(locator, provider_instance_id=provider_instance_id),
        source_field=source_field,
    )


def _migrated_binding_from_reference(
    role: str,
    reference: ProviderReference,
    *,
    source_field: str,
) -> BindingSelection:
    return BindingSelection(
        role=role,
        reference=reference,
        selection_origin=SelectionOrigin.MIGRATED,
        user_confirmed=True,
        provenance={
            "conversion_contract": _MIGRATION_CONTRACT,
            "legacy_source_field": source_field,
        },
    )


def _ephemeral_reference(locator: str, *, provider_instance_id: str) -> ProviderReference:
    return ProviderReference(
        provider=_HOME_ASSISTANT_PROVIDER,
        provider_instance_id=provider_instance_id,
        object_kind=_HOME_ASSISTANT_ENDPOINT_KIND,
        identity_quality=IdentityQuality.EPHEMERAL,
        current_locator=locator,
        recovery_evidence={"domain": locator.partition(".")[0]},
    )


def _exact_seconds(value: timedelta, field_name: str) -> float:
    seconds = value.total_seconds()
    if timedelta(seconds=seconds) != value:
        raise LegacyHeatingConversionError(f"{field_name} cannot be represented losslessly as canonical seconds")
    return seconds
