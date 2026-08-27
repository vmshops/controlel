"""Explicit, non-activating migration from canonical Heating v2 to schema v3."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from re import fullmatch
from typing import Literal, cast

from controlel.application.configuration.canonical_v3 import (
    CANONICAL_CONFIGURATION_V3_MIGRATION_POLICY_VERSION,
    CanonicalConfigurationRevisionV3,
    DiagnosticDebugPolicyV3,
    DiagnosticsConfigurationV3,
    HeatingConfigurationV3,
    HeatingGlobalConfigurationV3,
    HeatSourceCommandStrategyV3,
    HeatSourceConfigurationV3,
    HeatSourceObservationBindingsV3,
    HeatSourceProtectionPolicyV3,
    NotificationRecipientConfigurationV3,
    NotificationsConfigurationV3,
    PrimaryTemperatureSensorV3,
    ProviderServiceCallV3,
    ZoneConfigurationV3,
    ZoneDemandPolicyV3,
    ZoneHeatDeliveryConfigurationV3,
    ZoneTopologyV3,
)
from controlel.application.configuration.heating_setup_adapter import (
    HEATING_SETUP_SCHEMA_VERSION,
    PRIMARY_TEMPERATURE_ROLE,
    SOURCE_DISABLE_TARGET_ROLE,
    SOURCE_ENABLE_TARGET_ROLE,
    HeatingSetupAdapter,
    HeatingSetupPayload,
)
from controlel.application.setup.model import (
    BindingSelection,
    CanonicalConfigurationRevision,
    IdentityQuality,
    ProviderReference,
)

_HEAT_SOURCE_ID = "main_heat_source"
_HEAT_SOURCE_DISPLAY_NAME = "Main heat source"
_ZONE_ID_FALLBACK = "main_zone"
_SENSOR_ID_FALLBACK = "primary_temperature_sensor"
_MIGRATION_CONTRACT = "canonical_heating_v2_to_scoped_configuration_v3"
_TOPOLOGY_PROJECTION_RULE = "primary_temperature_binding_topology_v1"
_LOGICAL_ID_PATTERN = r"[a-z0-9_]+"


class CanonicalV2ToV3MigrationError(ValueError):
    """A v2 revision cannot be represented truthfully by the v3 contract."""


def migrate_heating_v2_revision_to_v3(
    revision: CanonicalConfigurationRevision,
    *,
    revision_id: str,
    created_at: datetime,
    actor: str = "system:migration",
    source: str = "canonical_v2_to_v3",
    reason: str = "separate_canonical_configuration_ownership",
    binding_overrides: Mapping[str, ProviderReference] | None = None,
) -> CanonicalConfigurationRevisionV3:
    """Build but never persist or activate one deterministic v3 successor.

    Historical values are copied field-for-field. Modern new-configuration
    defaults are not consulted by this adapter.
    """

    if revision.module_key != HeatingSetupAdapter.module_key:
        raise CanonicalV2ToV3MigrationError("canonical v2 revision is not Heating")
    if revision.module_schema_version != HEATING_SETUP_SCHEMA_VERSION:
        raise CanonicalV2ToV3MigrationError("canonical v2 revision uses an unsupported Heating schema")
    payload = HeatingSetupPayload.model_validate(revision.module_payload)
    overrides = dict(binding_overrides or {})
    source_bindings = {binding.role: binding for binding in revision.bindings}
    unknown_overrides = set(overrides) - set(source_bindings)
    if unknown_overrides:
        raise CanonicalV2ToV3MigrationError(
            f"v2 binding overrides contain unknown roles: {', '.join(sorted(unknown_overrides))}"
        )
    bindings = {
        role: binding.model_copy(update={"reference": overrides.get(role, binding.reference)})
        for role, binding in source_bindings.items()
    }

    primary_binding = _required_binding(bindings, PRIMARY_TEMPERATURE_ROLE)
    _require_stable(primary_binding.reference, "primary temperature sensor")
    topology = _project_topology(primary_binding.reference)
    sensor_id, sensor_id_remapped = _migrated_logical_id(
        payload.sensor_id,
        fallback=_SENSOR_ID_FALLBACK,
        provider_references=(primary_binding.reference,),
    )
    zone_id, zone_id_remapped = _migrated_logical_id(
        payload.zone_id,
        fallback=_ZONE_ID_FALLBACK,
        provider_references=((topology.area_reference,) if topology.area_reference is not None else ()),
    )

    enable_binding = _required_binding(bindings, SOURCE_ENABLE_TARGET_ROLE)
    disable_binding = _required_binding(bindings, SOURCE_DISABLE_TARGET_ROLE)
    _require_stable(enable_binding.reference, "heat-source enable command target")
    _require_stable(disable_binding.reference, "heat-source disable command target")
    reported_binding = _optional_binding(bindings, payload.reported_source_state_binding_role)
    if reported_binding is not None:
        _require_stable(reported_binding.reference, "reported source actuator state")

    delivery_binding = _optional_binding(bindings, payload.heat_delivery_actuator_binding_role)
    if delivery_binding is not None:
        _require_stable(delivery_binding.reference, "heat-delivery actuator")

    steady_profile = (
        payload.diagnostic_policy.diagnostic_profile_before_debug
        if payload.diagnostic_policy.diagnostic_profile == "debug"
        else payload.diagnostic_policy.diagnostic_profile
    )
    if steady_profile not in {"basic", "detailed"}:
        raise CanonicalV2ToV3MigrationError("v2 diagnostics have no representable steady profile")

    notifications = payload.notification_policy
    migrated_notifications = NotificationsConfigurationV3(
        enabled=notifications.enabled,
        recipients=tuple(
            NotificationRecipientConfigurationV3(
                recipient_id=recipient.recipient_id,
                transport=recipient.transport,
                target=recipient.target,
                enabled=recipient.enabled,
                minimum_level=recipient.minimum_level,
                categories=recipient.categories,
            )
            for recipient in notifications.recipients
        ),
        maximum_per_window=notifications.maximum_per_window,
        rate_window_seconds=notifications.rate_window_seconds,
        critical_maximum_per_window=notifications.critical_maximum_per_window,
        critical_rate_window_seconds=notifications.critical_rate_window_seconds,
        history_capacity=notifications.history_capacity,
    )

    assist_policy = cast(
        Literal["no_assist", "always_assist_while_heating"],
        payload.heat_delivery_assist_policy,
    )
    delivery_mode = cast(Literal["unmanaged", "setpoint_assist"], payload.heat_delivery_mode)
    delivery_ownership = cast(Literal["device_owned", "controlel_owned"], payload.heat_delivery_ownership)
    source_mode = cast(Literal["simple", "custom"], payload.source_control_mode)
    migrated = CanonicalConfigurationRevisionV3(
        # ActiveReference CAS is scoped by the v2 module instance.  Carry that
        # stable Controlel identity forward so an active v2 revision can be
        # replaced atomically by its v3 successor.
        configuration_id=revision.module_instance_id,
        revision_id=revision_id,
        revision=revision.revision + 1,
        parent_revision_id=revision.revision_id,
        environment_id=revision.environment_id,
        provider=revision.provider,
        provider_instance_id=revision.provider_instance_id,
        created_at=created_at,
        actor=actor,
        source=source,
        change_kind="MIGRATE",
        reason=reason,
        core_version=revision.core_version,
        integration_version=revision.integration_version,
        heating=HeatingConfigurationV3.model_validate(
            {
                "global": HeatingGlobalConfigurationV3(
                    maximum_future_skew_seconds=payload.maximum_future_skew_seconds,
                ),
                "zones": (
                    ZoneConfigurationV3(
                        zone_id=zone_id,
                        display_name=payload.zone_name,
                        topology=topology,
                        primary_temperature_sensor=PrimaryTemperatureSensorV3(
                            sensor_id=sensor_id,
                            display_name=payload.sensor_name,
                            provider_reference=primary_binding.reference,
                        ),
                        demand_policy=ZoneDemandPolicyV3(
                            target_temperature_celsius=payload.target_temperature_celsius,
                            heating_turn_on_differential_celsius=payload.heating_turn_on_differential_celsius,
                            heating_turn_off_differential_celsius=payload.heating_turn_off_differential_celsius,
                            heat_demand_confirmation_seconds=payload.heat_demand_confirmation_seconds,
                            primary_measurement_max_age_seconds=payload.primary_measurement_max_age_seconds,
                        ),
                    ),
                ),
                "heat_sources": (
                    HeatSourceConfigurationV3(
                        heat_source_id=_HEAT_SOURCE_ID,
                        display_name=_HEAT_SOURCE_DISPLAY_NAME,
                        provider_reference=_shared_stable_source_reference(enable_binding, disable_binding),
                        command_strategy=HeatSourceCommandStrategyV3(
                            mode=source_mode,
                            enable_permission=ProviderServiceCallV3(
                                domain=payload.source_enable.domain,
                                service=payload.source_enable.service,
                                command_target_reference=enable_binding.reference,
                            ),
                            disable_permission=ProviderServiceCallV3(
                                domain=payload.source_disable.domain,
                                service=payload.source_disable.service,
                                command_target_reference=disable_binding.reference,
                            ),
                        ),
                        observations=HeatSourceObservationBindingsV3(
                            reported_actuator_state_reference=(
                                reported_binding.reference if reported_binding is not None else None
                            ),
                            physical_operation_reference=None,
                        ),
                        protection=HeatSourceProtectionPolicyV3(
                            indeterminate_grace_period_seconds=payload.indeterminate_grace_period_seconds,
                            indeterminate_timeout_action=payload.indeterminate_timeout_action,
                            minimum_heating_on_seconds=payload.minimum_heating_on_seconds,
                            minimum_heating_off_seconds=payload.minimum_heating_off_seconds,
                        ),
                    ),
                ),
                "heat_delivery": (
                    ZoneHeatDeliveryConfigurationV3(
                        zone_id=zone_id,
                        mode=delivery_mode,
                        actuator_reference=(delivery_binding.reference if delivery_binding is not None else None),
                        ownership=delivery_ownership,
                        assist_policy=assist_policy,
                        assist_target_celsius=payload.heat_delivery_assist_target_celsius,
                    ),
                ),
            }
        ),
        diagnostics=DiagnosticsConfigurationV3(
            steady_profile=steady_profile,
            debug_policy=DiagnosticDebugPolicyV3(
                configured_duration_seconds=payload.diagnostic_policy.configured_debug_duration_seconds,
                until_changed=payload.diagnostic_policy.debug_until_changed,
            ),
        ),
        notifications=migrated_notifications,
        lineage={
            **dict(revision.lineage),
            "migrated_from_revision_id": revision.revision_id,
            "migrated_from_document_hash": revision.document_hash,
            "migrated_from_semantic_configuration_fingerprint": (revision.semantic_configuration_fingerprint),
        },
        import_provenance=revision.import_provenance,
        migration_provenance={
            **dict(revision.migration_provenance),
            "v2_to_v3": {
                "contract": _MIGRATION_CONTRACT,
                "policy_version": CANONICAL_CONFIGURATION_V3_MIGRATION_POLICY_VERSION,
                "source_module_schema_version": revision.module_schema_version,
                "source_configuration_id": revision.configuration_id,
                "source_module_instance_id": revision.module_instance_id,
                "historical_values_preserved": True,
                "synthesized_heat_source_id": _HEAT_SOURCE_ID,
                "synthesized_heat_source_display_name": _HEAT_SOURCE_DISPLAY_NAME,
                "logical_identity_projection": {
                    "zone_id_remapped": zone_id_remapped,
                    "source_zone_id": payload.zone_id if zone_id_remapped else None,
                    "sensor_id_remapped": sensor_id_remapped,
                    "source_sensor_id": payload.sensor_id if sensor_id_remapped else None,
                },
                "topology_projection_rule": _TOPOLOGY_PROJECTION_RULE,
                "active_debug_runtime_state_excluded": payload.diagnostic_policy.diagnostic_profile == "debug",
                "steady_profile_source": (
                    "diagnostic_profile_before_debug"
                    if payload.diagnostic_policy.diagnostic_profile == "debug"
                    else "diagnostic_profile"
                ),
                "ha_always_assist_default_drift_preserved": (
                    payload.heat_delivery_assist_policy == "always_assist_while_heating"
                ),
                "binding_resolution": {
                    role: {
                        "source_reference": source_bindings[role].reference.document_data(),
                        "resolved_reference": reference.document_data(),
                    }
                    for role, reference in sorted(overrides.items())
                },
            },
        },
    )
    return migrated


def _required_binding(bindings: dict[str, BindingSelection], role: str) -> BindingSelection:
    try:
        return bindings[role]
    except KeyError as error:
        raise CanonicalV2ToV3MigrationError(f"canonical v2 revision is missing binding {role}") from error


def _optional_binding(
    bindings: dict[str, BindingSelection],
    role: str | None,
) -> BindingSelection | None:
    if role is None:
        return None
    return _required_binding(bindings, role)


def _require_stable(reference: ProviderReference, label: str) -> None:
    if reference.identity_quality is not IdentityQuality.STABLE:
        raise CanonicalV2ToV3MigrationError(
            f"{label} binding must be resolved to stable provider identity before v3 migration"
        )


def _migrated_logical_id(
    candidate: str,
    *,
    fallback: str,
    provider_references: tuple[ProviderReference, ...],
) -> tuple[str, bool]:
    provider_values = {
        value
        for reference in provider_references
        for value in (reference.native_id, reference.current_locator)
        if value is not None
    }
    if fullmatch(_LOGICAL_ID_PATTERN, candidate) is not None and candidate not in provider_values:
        return candidate, False
    projected = fallback
    suffix = 2
    while projected in provider_values:
        projected = f"{fallback}_{suffix}"
        suffix += 1
    return projected, True


def _project_topology(primary: ProviderReference) -> ZoneTopologyV3:
    area_reference = None
    if primary.area_id is not None:
        area_reference = ProviderReference(
            provider=primary.provider,
            provider_instance_id=primary.provider_instance_id,
            object_kind="home_assistant.area",
            native_id=primary.area_id,
            identity_quality=IdentityQuality.STABLE,
            floor_id=primary.floor_id,
            recovery_evidence={"projection_rule": _TOPOLOGY_PROJECTION_RULE},
        )
    floor_reference = None
    if primary.floor_id is not None:
        floor_reference = ProviderReference(
            provider=primary.provider,
            provider_instance_id=primary.provider_instance_id,
            object_kind="home_assistant.floor",
            native_id=primary.floor_id,
            identity_quality=IdentityQuality.STABLE,
            recovery_evidence={"projection_rule": _TOPOLOGY_PROJECTION_RULE},
        )
    return ZoneTopologyV3(
        area_reference=area_reference,
        floor_reference=floor_reference,
    )


def _shared_stable_source_reference(
    enable: BindingSelection,
    disable: BindingSelection,
) -> ProviderReference | None:
    if enable.reference.identity_quality is not IdentityQuality.STABLE:
        return None
    if enable.reference.semantic_data() != disable.reference.semantic_data():
        return None
    return enable.reference
