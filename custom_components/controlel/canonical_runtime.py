"""Canonical Heating runtime selection and compilation for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from controlel.application.configuration.heating_setup_adapter import (
    HEAT_DELIVERY_ACTUATOR_ROLE,
    HEATING_SETUP_SCHEMA_VERSION,
    PRIMARY_TEMPERATURE_ROLE,
    REPORTED_SOURCE_STATE_ROLE,
    HeatingSetupAdapter,
    HeatingSetupPayload,
)
from controlel.application.setup import (
    ActiveReference,
    CanonicalConfigurationRevision,
    DraftRevision,
    EffectiveRuntimeConfiguration,
    IdentityQuality,
    LoadedRuntimeConfiguration,
    ReferenceResolutionStatus,
    derive_real_runtime_configuration,
)
from controlel.domain.notifications import NotificationPolicy, NotificationRecipient
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId
from controlel.infrastructure.home_assistant import (
    ACTIVE_REFERENCE_KEY,
    HomeAssistantDiscoveryAdapter,
    HomeAssistantEphemeralEndpoint,
    HomeAssistantReferenceResolver,
)

from .config import (
    HomeAssistantConfigurationError,
    HomeAssistantHeatSourceBinding,
    HomeAssistantIntegrationConfig,
    HomeAssistantServiceCall,
    integration_config_from_entry,
)
from .const import CONTROL_MODE_CUSTOM, CONTROL_MODE_SIMPLE
from .setup_backend import SetupBackend, async_get_setup_backend

_STAGED_RUNTIME_KEY = "controlel_staged_canonical_runtime"


@dataclass(frozen=True)
class RuntimeConfigurationSelection:
    """One complete, non-mixed configuration selected for runtime composition."""

    config: HomeAssistantIntegrationConfig
    loaded_configuration: LoadedRuntimeConfiguration | None
    activation_attempt_id: str | None = None

    @property
    def is_activation_candidate(self) -> bool:
        return self.activation_attempt_id is not None


def stage_candidate_runtime(hass: Any, entry_id: str, selection: RuntimeConfigurationSelection) -> None:
    """Stage one already-compiled candidate for the serialized HA reload."""

    if not selection.is_activation_candidate or selection.loaded_configuration is None:
        raise ValueError("staged candidate runtime requires activation identity and canonical stamp")
    staged = hass.data.setdefault(_STAGED_RUNTIME_KEY, {})
    if entry_id in staged:
        raise RuntimeError("a canonical runtime candidate is already staged for this config entry")
    staged[entry_id] = selection


def clear_staged_candidate_runtime(hass: Any, entry_id: str) -> None:
    """Remove an activation-only runtime selection after handover or rollback."""

    staged = hass.data.get(_STAGED_RUNTIME_KEY)
    if not isinstance(staged, dict):
        return
    staged.pop(entry_id, None)
    if not staged:
        hass.data.pop(_STAGED_RUNTIME_KEY, None)


def staged_candidate_runtime(hass: Any, entry_id: str) -> RuntimeConfigurationSelection | None:
    staged = hass.data.get(_STAGED_RUNTIME_KEY)
    if not isinstance(staged, dict):
        return None
    value = staged.get(entry_id)
    return value if isinstance(value, RuntimeConfigurationSelection) else None


async def async_select_runtime_configuration(
    hass: Any,
    entry: Any,
) -> tuple[RuntimeConfigurationSelection, SetupBackend]:
    """Select staged candidate, canonical authority, or unchanged legacy fallback."""

    backend = await async_get_setup_backend(hass, entry)
    staged = staged_candidate_runtime(hass, entry.entry_id)
    if staged is not None:
        return staged, backend

    raw_reference = entry.data.get(ACTIVE_REFERENCE_KEY)
    if raw_reference is None:
        return RuntimeConfigurationSelection(integration_config_from_entry(entry.data, entry.options), None), backend

    try:
        active = ActiveReference.model_validate(raw_reference)
    except (TypeError, ValueError) as error:
        raise HomeAssistantConfigurationError("canonical active reference is invalid") from error
    revision = await backend.repository.get_canonical_revision(active.canonical_revision_id)
    _require_active_revision(active, revision)
    return await async_compile_canonical_runtime(hass, revision), backend


async def async_compile_canonical_runtime(
    hass: Any,
    revision: CanonicalConfigurationRevision,
    *,
    activation_attempt_id: str | None = None,
) -> RuntimeConfigurationSelection:
    """Freshly validate, resolve, and compile one immutable Heating revision."""

    if revision.module_key != HeatingSetupAdapter.module_key:
        raise HomeAssistantConfigurationError("canonical revision is not a Heating configuration")
    if revision.module_schema_version != HEATING_SETUP_SCHEMA_VERSION:
        raise HomeAssistantConfigurationError("canonical Heating revision uses an unsupported schema version")
    if revision.provider != "home_assistant":
        raise HomeAssistantConfigurationError("canonical Heating revision uses a non-Home-Assistant provider")

    payload = _payload(revision)
    captured_at = datetime.now(UTC)
    snapshot = await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
        hass,
        snapshot_id=f"runtime:{revision.revision_id}:{captured_at.isoformat()}",
        captured_at=captured_at,
        ephemeral_endpoints=_ephemeral_endpoints(revision, payload),
    )
    if (
        revision.environment_id != snapshot.provider_instance_id
        or revision.provider_instance_id != snapshot.provider_instance_id
    ):
        raise HomeAssistantConfigurationError("canonical Heating revision belongs to another Home Assistant instance")

    resolver = HomeAssistantReferenceResolver()
    draft = DraftRevision(
        draft_id=f"runtime-validation:{revision.revision_id}",
        revision=1,
        environment_id=revision.environment_id,
        module_key=revision.module_key,
        module_instance_id=revision.module_instance_id,
        module_schema_version=revision.module_schema_version,
        created_at=revision.created_at,
        updated_at=revision.created_at,
        settings=revision.module_payload,
        bindings=revision.bindings,
    )
    report = HeatingSetupAdapter().validate(
        draft,
        report_id=f"runtime-validation:{revision.revision_id}:{captured_at.isoformat()}",
        evaluated_at=captured_at,
        discovery_snapshot=snapshot,
        reference_resolver=resolver,
        resolution_generation=1,
    )
    if not report.activation_ready:
        codes = ", ".join(sorted({issue.code for issue in report.issues if issue.severity.value == "ERROR"}))
        raise HomeAssistantConfigurationError(f"canonical Heating revision is not runtime-ready: {codes}")

    resolved = {}
    for binding in revision.bindings:
        resolution = resolver.resolve(binding.reference, snapshot)
        if resolution.status not in {ReferenceResolutionStatus.RESOLVED, ReferenceResolutionStatus.EPHEMERAL}:
            raise HomeAssistantConfigurationError(
                f"canonical Heating binding {binding.role} is not resolvable: {resolution.status.value}"
            )
        if resolution.resolved_reference is None:
            raise HomeAssistantConfigurationError(f"canonical Heating binding {binding.role} has no resolved reference")
        resolved[binding.role] = resolution.resolved_reference
    effective = derive_real_runtime_configuration(revision, resolved)
    return RuntimeConfigurationSelection(
        config=compile_effective_heating_config(effective),
        loaded_configuration=LoadedRuntimeConfiguration(
            canonical_revision_id=revision.revision_id,
            semantic_configuration_fingerprint=revision.semantic_configuration_fingerprint,
            environment_id=revision.environment_id,
            module_key=revision.module_key,
            module_instance_id=revision.module_instance_id,
        ),
        activation_attempt_id=activation_attempt_id,
    )


def compile_effective_heating_config(
    effective: EffectiveRuntimeConfiguration,
) -> HomeAssistantIntegrationConfig:
    """Compile wholly from one canonical effective projection, never legacy data."""

    if effective.module_key != HeatingSetupAdapter.module_key:
        raise HomeAssistantConfigurationError("effective runtime configuration is not Heating")
    if effective.module_schema_version != HEATING_SETUP_SCHEMA_VERSION:
        raise HomeAssistantConfigurationError("effective Heating configuration uses an unsupported schema version")
    payload = HeatingSetupPayload.model_validate(effective.module_payload)
    bindings = {binding.role: binding.reference.current_locator for binding in effective.bindings}

    primary_temperature = _required_locator(bindings, PRIMARY_TEMPERATURE_ROLE)
    enable_target = _required_locator(bindings, payload.source_enable.target_binding_role)
    disable_target = _required_locator(bindings, payload.source_disable.target_binding_role)
    reported_source = (
        None
        if payload.reported_source_state_binding_role is None
        else _required_locator(bindings, REPORTED_SOURCE_STATE_ROLE)
    )
    heat_delivery_actuator = (
        None
        if payload.heat_delivery_actuator_binding_role is None
        else _required_locator(bindings, HEAT_DELIVERY_ACTUATOR_ROLE)
    )
    diagnostic = payload.diagnostic_policy
    notifications = payload.notification_policy
    return HomeAssistantIntegrationConfig(
        sensor_id=SensorId(payload.sensor_id),
        sensor_name=payload.sensor_name,
        temperature_entity_id=primary_temperature,
        zone_id=ZoneId(payload.zone_id),
        zone_name=payload.zone_name,
        target_temperature=Temperature(payload.target_temperature_celsius),
        heating_turn_on_differential=payload.heating_turn_on_differential_celsius,
        heating_turn_off_differential=payload.heating_turn_off_differential_celsius,
        minimum_heating_on_time=timedelta(seconds=payload.minimum_heating_on_seconds),
        minimum_heating_off_time=timedelta(seconds=payload.minimum_heating_off_seconds),
        primary_measurement_max_age=timedelta(seconds=payload.primary_measurement_max_age_seconds),
        max_future_skew=timedelta(seconds=payload.maximum_future_skew_seconds),
        indeterminate_grace_period=timedelta(seconds=payload.indeterminate_grace_period_seconds),
        indeterminate_timeout_action=payload.indeterminate_timeout_action,
        heat_source=HomeAssistantHeatSourceBinding(
            enable_heating=HomeAssistantServiceCall(
                payload.source_enable.domain,
                payload.source_enable.service,
                enable_target,
            ),
            disable_heating=HomeAssistantServiceCall(
                payload.source_disable.domain,
                payload.source_disable.service,
                disable_target,
            ),
        ),
        heat_source_control_mode={
            "simple": CONTROL_MODE_SIMPLE,
            "custom": CONTROL_MODE_CUSTOM,
        }[payload.source_control_mode],
        controlled_entity_id=reported_source,
        diagnostic_profile=diagnostic.diagnostic_profile,
        debug_duration=(
            None if diagnostic.debug_duration_seconds is None else timedelta(seconds=diagnostic.debug_duration_seconds)
        ),
        configured_debug_duration=timedelta(seconds=diagnostic.configured_debug_duration_seconds),
        diagnostic_profile_before_debug=diagnostic.diagnostic_profile_before_debug,
        heat_demand_confirmation_duration=timedelta(seconds=payload.heat_demand_confirmation_seconds),
        heat_delivery_mode=payload.heat_delivery_mode,
        heat_delivery_actuator_entity_id=heat_delivery_actuator,
        heat_delivery_ownership=payload.heat_delivery_ownership,
        heat_delivery_assist_policy=payload.heat_delivery_assist_policy,
        heat_delivery_assist_target=payload.heat_delivery_assist_target_celsius,
        notification_policy=NotificationPolicy(
            enabled=notifications.enabled,
            recipients=tuple(
                NotificationRecipient(
                    recipient.recipient_id,
                    recipient.transport,
                    recipient.target,
                    enabled=recipient.enabled,
                    minimum_level=recipient.minimum_level,
                    categories=recipient.categories,
                )
                for recipient in notifications.recipients
            ),
            maximum_per_window=notifications.maximum_per_window,
            rate_window=timedelta(seconds=notifications.rate_window_seconds),
            critical_maximum_per_window=notifications.critical_maximum_per_window,
            critical_rate_window=timedelta(seconds=notifications.critical_rate_window_seconds),
            history_capacity=notifications.history_capacity,
        ),
    )


def _payload(revision: CanonicalConfigurationRevision) -> HeatingSetupPayload:
    try:
        return HeatingSetupPayload.model_validate(revision.module_payload)
    except (TypeError, ValueError) as error:
        raise HomeAssistantConfigurationError("canonical Heating payload is invalid") from error


def _ephemeral_endpoints(
    revision: CanonicalConfigurationRevision,
    payload: HeatingSetupPayload,
) -> tuple[HomeAssistantEphemeralEndpoint, ...]:
    service_domains = {
        payload.source_enable.target_binding_role: payload.source_enable.domain,
        payload.source_disable.target_binding_role: payload.source_disable.domain,
    }
    endpoints = []
    for binding in revision.bindings:
        reference = binding.reference
        if reference.identity_quality is not IdentityQuality.EPHEMERAL:
            continue
        locator = reference.current_locator
        if locator is None:
            raise HomeAssistantConfigurationError(f"ephemeral Heating binding {binding.role} has no locator")
        domain = service_domains.get(binding.role)
        if domain is None:
            evidence_domain = reference.recovery_evidence.get("domain")
            domain = evidence_domain if isinstance(evidence_domain, str) else locator.partition(".")[0]
        endpoints.append(
            HomeAssistantEphemeralEndpoint(
                current_locator=locator,
                domain=domain,
                device_registry_id=reference.device_registry_id,
                area_id=reference.area_id,
                floor_id=reference.floor_id,
            )
        )
    return tuple(endpoints)


def _required_locator(bindings: dict[str, str | None], role: str) -> str:
    locator = bindings.get(role)
    if locator is None:
        raise HomeAssistantConfigurationError(f"canonical Heating binding {role} has no runtime locator")
    return locator


def _require_active_revision(
    active: ActiveReference,
    revision: CanonicalConfigurationRevision,
) -> None:
    if active.scope_key != (revision.environment_id, revision.module_key, revision.module_instance_id):
        raise HomeAssistantConfigurationError("canonical active reference scope does not match its revision")
    if active.semantic_configuration_fingerprint != revision.semantic_configuration_fingerprint:
        raise HomeAssistantConfigurationError("canonical active reference fingerprint does not match its revision")
