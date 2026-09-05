"""Privacy-minimized diagnostics for one Controlel config entry."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from controlel.application.state.heating_diagnostics import heating_diagnostics_to_dict
from controlel.infrastructure.home_assistant import active_reference_for_module

from . import ControlelEntryRuntime
from .config import HomeAssistantIntegrationConfig
from .const import (
    CONF_CONTROLLED_ENTITY_ID,
    CONF_DEBUG_DURATION,
    CONF_DEBUG_UNTIL_CHANGED,
    CONF_DIAGNOSTIC_PROFILE,
    CONF_DIAGNOSTIC_PROFILE_BEFORE_DEBUG,
    CONF_DISABLE_SERVICE_DOMAIN,
    CONF_DISABLE_SERVICE_NAME,
    CONF_DISABLE_TARGET_ENTITY_ID,
    CONF_ENABLE_SERVICE_DOMAIN,
    CONF_ENABLE_SERVICE_NAME,
    CONF_ENABLE_TARGET_ENTITY_ID,
    CONF_HEAT_DELIVERY_ACTUATOR_ENTITY_ID,
    CONF_HEAT_DELIVERY_ASSIST_POLICY,
    CONF_HEAT_DELIVERY_ASSIST_TARGET,
    CONF_HEAT_DELIVERY_MODE,
    CONF_HEAT_DELIVERY_OWNERSHIP,
    CONF_HEAT_DEMAND_CONFIRMATION_DURATION,
    CONF_HEAT_SOURCE_CONTROL_MODE,
    CONF_HEATING_TURN_OFF_DIFFERENTIAL,
    CONF_HEATING_TURN_ON_DIFFERENTIAL,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_INDETERMINATE_TIMEOUT_ACTION,
    CONF_MAX_FUTURE_SKEW,
    CONF_MINIMUM_HEATING_OFF_TIME,
    CONF_MINIMUM_HEATING_ON_TIME,
    CONF_PRIMARY_MEASUREMENT_MAX_AGE,
    CONF_SENSOR_ID,
    CONF_SENSOR_NAME,
    CONF_TARGET_TEMPERATURE,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_ZONE_ID,
    CONF_ZONE_NAME,
    CONTROL_MODE_CUSTOM,
)
from .lifecycle_diagnostics import lifecycle_failures_for_entry
from .operational import snapshot_to_dict, trace_to_dict
from .setup_backend import async_get_setup_backend

_COMMON_MUTABLE_KEYS = (
    CONF_ZONE_NAME,
    CONF_SENSOR_NAME,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_TARGET_TEMPERATURE,
    CONF_HEATING_TURN_ON_DIFFERENTIAL,
    CONF_HEATING_TURN_OFF_DIFFERENTIAL,
    CONF_HEAT_DEMAND_CONFIRMATION_DURATION,
    CONF_MINIMUM_HEATING_ON_TIME,
    CONF_MINIMUM_HEATING_OFF_TIME,
    CONF_PRIMARY_MEASUREMENT_MAX_AGE,
    CONF_MAX_FUTURE_SKEW,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_INDETERMINATE_TIMEOUT_ACTION,
    CONF_HEAT_SOURCE_CONTROL_MODE,
    CONF_DIAGNOSTIC_PROFILE,
    CONF_DEBUG_DURATION,
    CONF_DEBUG_UNTIL_CHANGED,
    CONF_DIAGNOSTIC_PROFILE_BEFORE_DEBUG,
    CONF_HEAT_DELIVERY_MODE,
    CONF_HEAT_DELIVERY_ACTUATOR_ENTITY_ID,
    CONF_HEAT_DELIVERY_OWNERSHIP,
    CONF_HEAT_DELIVERY_ASSIST_POLICY,
    CONF_HEAT_DELIVERY_ASSIST_TARGET,
)
_CUSTOM_BINDING_KEYS = (
    CONF_ENABLE_SERVICE_DOMAIN,
    CONF_ENABLE_SERVICE_NAME,
    CONF_ENABLE_TARGET_ENTITY_ID,
    CONF_DISABLE_SERVICE_DOMAIN,
    CONF_DISABLE_SERVICE_NAME,
    CONF_DISABLE_TARGET_ENTITY_ID,
)
_RAW_ALLOWLIST = (
    CONF_SENSOR_ID,
    CONF_ZONE_ID,
    *_COMMON_MUTABLE_KEYS,
    CONF_CONTROLLED_ENTITY_ID,
    *_CUSTOM_BINDING_KEYS,
)
_MUTABLE_ALLOWLIST = (
    *_COMMON_MUTABLE_KEYS,
    CONF_CONTROLLED_ENTITY_ID,
    *_CUSTOM_BINDING_KEYS,
)


def _service_call(call: object) -> dict[str, str]:
    return {
        "domain": call.domain,
        "service": call.service,
        "target_entity_id": call.target_entity_id,
    }


def _normalized_config(config: HomeAssistantIntegrationConfig) -> dict[str, Any]:
    return {
        "zone_name": config.zone_name,
        "zone_id": config.zone_id.value,
        "sensor_name": config.sensor_name,
        "sensor_id": config.sensor_id.value,
        "temperature_entity_id": config.temperature_entity_id,
        "target_temperature": config.target_temperature.value,
        "heating_turn_on_differential": config.heating_turn_on_differential,
        "heating_turn_off_differential": config.heating_turn_off_differential,
        "heat_demand_confirmation_duration_seconds": (config.heat_demand_confirmation_duration.total_seconds()),
        "heating_enable_threshold": (config.target_temperature.value - config.heating_turn_on_differential),
        "heating_disable_threshold": (config.target_temperature.value + config.heating_turn_off_differential),
        "minimum_heating_on_time_seconds": config.minimum_heating_on_time.total_seconds(),
        "minimum_heating_off_time_seconds": config.minimum_heating_off_time.total_seconds(),
        "diagnostic_profile": config.diagnostic_profile,
        "debug_duration_seconds": (
            config.debug_duration.total_seconds() if config.debug_duration is not None else None
        ),
        "configured_debug_duration_seconds": (config.configured_debug_duration.total_seconds()),
        "diagnostic_profile_before_debug": config.diagnostic_profile_before_debug,
        "primary_measurement_max_age_seconds": config.primary_measurement_max_age.total_seconds(),
        "max_future_skew_seconds": config.max_future_skew.total_seconds(),
        "indeterminate_grace_period_seconds": config.indeterminate_grace_period.total_seconds(),
        "indeterminate_timeout_action": config.indeterminate_timeout_action.value,
        "heat_source_control_mode": config.heat_source_control_mode,
        "controlled_entity_id": config.controlled_entity_id,
        "enable_service": _service_call(config.heat_source.enable_heating),
        "disable_service": _service_call(config.heat_source.disable_heating),
        "heat_delivery_mode": config.heat_delivery_mode,
        "actuator_entity_id": config.heat_delivery_actuator_entity_id,
        "actuator_ownership": config.heat_delivery_ownership,
        "assist_policy": config.heat_delivery_assist_policy,
        "assist_target_temperature": config.heat_delivery_assist_target,
        "notification_policy": {
            "enabled": config.notification_policy.enabled,
            "configured_recipient_count": len(config.notification_policy.recipients),
            "recipients": [
                {
                    "recipient_id": recipient.recipient_id,
                    "transport": recipient.transport,
                    "target_configured": bool(recipient.target),
                    "enabled": recipient.enabled,
                    "minimum_level": recipient.minimum_level.value,
                    "categories": [category.value for category in recipient.categories],
                }
                for recipient in config.notification_policy.recipients
            ],
            "maximum_per_window": config.notification_policy.maximum_per_window,
            "rate_window_seconds": config.notification_policy.rate_window.total_seconds(),
            "critical_maximum_per_window": config.notification_policy.critical_maximum_per_window,
            "critical_rate_window_seconds": config.notification_policy.critical_rate_window.total_seconds(),
            "history_capacity": config.notification_policy.history_capacity,
        },
    }


def _heat_delivery_state(state: Any) -> dict[str, Any]:
    def command(value: Any | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return {
            "actuator_id": value.actuator_id.value,
            "zone_id": value.zone_id.value,
            "kind": value.kind.value,
            "value": value.value,
            "requested_at": value.requested_at.isoformat(),
        }

    return {
        "actuator_id": state.actuator_id.value,
        "zone_id": state.zone_id.value,
        "heat_delivery_mode": state.mode.value,
        "actuator_ownership": state.ownership.value,
        "actuator_capabilities": {
            name: getattr(state.capabilities, name) for name in state.capabilities.__dataclass_fields__
        },
        "assist_policy": state.assist_policy.value,
        "assist_active": state.assist_active,
        "zone_target_temperature": state.zone_target_temperature,
        "zone_measurement_temperature": state.zone_measurement_temperature,
        "normal_actuator_target": state.normal_actuator_target,
        "commanded_actuator_target": state.commanded_target_temperature,
        "reported_actuator_target": state.reported_target_temperature,
        "commanded_position": state.commanded_position,
        "reported_position": state.reported_position,
        "commanded_binary_open": state.commanded_binary_open,
        "reported_binary_open": state.reported_binary_open,
        "commanded_remote_temperature": state.commanded_remote_temperature,
        "last_requested_actuator_command": command(state.last_requested_command),
        "last_successful_actuator_command": command(state.last_successful_command),
        "last_actuator_command_outcome": (
            state.last_command_outcome.value if state.last_command_outcome is not None else None
        ),
        "last_actuator_command_timestamp": (
            state.last_command_timestamp.isoformat() if state.last_command_timestamp is not None else None
        ),
        "actuator_failure_active": state.actuator_failure_active,
        "actuator_failure_reason": state.actuator_failure_reason,
    }


def _configuration_provenance(
    data: Mapping[str, Any],
    options: Mapping[str, Any],
    config: HomeAssistantIntegrationConfig,
) -> dict[str, Any]:
    mutable_keys = (
        (*_COMMON_MUTABLE_KEYS, *_CUSTOM_BINDING_KEYS)
        if config.heat_source_control_mode == CONTROL_MODE_CUSTOM
        else (*_COMMON_MUTABLE_KEYS, CONF_CONTROLLED_ENTITY_ID)
    )
    return {
        "legacy_data_values": _allowlisted(data, _RAW_ALLOWLIST),
        "mutable_options_values": _allowlisted(options, _MUTABLE_ALLOWLIST),
        "effective_normalized_values": _normalized_config(config),
        "user_facing_timing_values": {
            "primary_measurement_max_age_minutes": {
                "value": config.primary_measurement_max_age.total_seconds() / 60,
                "unit": "minutes",
            },
            "max_future_skew_seconds": {
                "value": config.max_future_skew.total_seconds(),
                "unit": "seconds",
            },
            "indeterminate_grace_period_minutes": {
                "value": config.indeterminate_grace_period.total_seconds() / 60,
                "unit": "minutes",
            },
            "minimum_heating_on_time_minutes": {
                "value": config.minimum_heating_on_time.total_seconds() / 60,
                "unit": "minutes",
            },
            "minimum_heating_off_time_minutes": {
                "value": config.minimum_heating_off_time.total_seconds() / 60,
                "unit": "minutes",
            },
            "heat_demand_confirmation_duration_minutes": {
                "value": (config.heat_demand_confirmation_duration.total_seconds() / 60),
                "unit": "minutes",
            },
            "debug_duration_minutes": {
                "value": config.configured_debug_duration.total_seconds() / 60,
                "unit": "minutes",
            },
        },
        "precedence_source": {key: _precedence_source(key, data, options) for key in mutable_keys},
    }


def _allowlisted(
    values: Mapping[str, Any],
    keys: tuple[str, ...],
) -> dict[str, Any]:
    return {key: values[key] for key in keys if key in values}


def _precedence_source(
    key: str,
    data: Mapping[str, Any],
    options: Mapping[str, Any],
) -> str:
    if key in options:
        return "config_entry.options"
    if key in data:
        return "config_entry.data"
    if key == CONF_HEAT_SOURCE_CONTROL_MODE:
        bindings = (CONF_CONTROLLED_ENTITY_ID, *_CUSTOM_BINDING_KEYS)
        if any(binding in options for binding in bindings):
            return "config_entry.options"
        if any(binding in data for binding in bindings):
            return "config_entry.data"
    if key == CONF_CONTROLLED_ENTITY_ID:
        if CONF_ENABLE_TARGET_ENTITY_ID in options:
            return "config_entry.options"
        if CONF_ENABLE_TARGET_ENTITY_ID in data:
            return "config_entry.data"
    if key in {
        CONF_HEATING_TURN_ON_DIFFERENTIAL,
        CONF_HEATING_TURN_OFF_DIFFERENTIAL,
        CONF_HEAT_DEMAND_CONFIRMATION_DURATION,
        CONF_MINIMUM_HEATING_ON_TIME,
        CONF_MINIMUM_HEATING_OFF_TIME,
        CONF_DIAGNOSTIC_PROFILE,
        CONF_DEBUG_DURATION,
        CONF_DEBUG_UNTIL_CHANGED,
        CONF_DIAGNOSTIC_PROFILE_BEFORE_DEBUG,
    }:
        return "legacy_compatibility_default"
    return "new_entry_default"


def _config_entry_state(entry: ConfigEntry[ControlelEntryRuntime]) -> str:
    state = getattr(entry, "state", "unknown")
    return str(getattr(state, "value", state))


async def _configuration_readiness(
    hass: HomeAssistant,
    entry: ConfigEntry[ControlelEntryRuntime],
    runtime_data: ControlelEntryRuntime | None,
) -> dict[str, object]:
    heating_active = active_reference_for_module(entry.data, "heating")
    water_active = active_reference_for_module(entry.data, "water_safety")
    host = None if runtime_data is None else runtime_data.host
    water_host = None if runtime_data is None else runtime_data.water_safety_host
    backend = await async_get_setup_backend(hass, entry)
    drafts = await backend.configuration_v3.list_drafts()
    latest_draft = max(drafts, key=lambda item: item.updated_at) if drafts else None
    return {
        "config_entry_state": _config_entry_state(entry),
        "config_entry_reason": (None if getattr(entry, "reason", None) is None else str(entry.reason)),
        "heating": {
            "configured": heating_active is not None,
            "runtime_loaded": host is not None,
            "runtime_ready": bool(host is not None and host.frontend_api_setup_ready),
        },
        "water_safety": {
            "configured": water_active is not None,
            "runtime_loaded": water_host is not None,
        },
        "heating_draft": {
            "saved_count": len(drafts),
            "latest_revision": None if latest_draft is None else latest_draft.revision,
        },
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry[ControlelEntryRuntime],
) -> dict[str, Any]:
    runtime_data = getattr(entry, "runtime_data", None)
    host = None if runtime_data is None else runtime_data.host
    config = None if runtime_data is None else runtime_data.config
    result: dict[str, Any] = {
        "configuration": None if config is None else _normalized_config(config),
        "configuration_provenance": (
            None if config is None else _configuration_provenance(entry.data, entry.options, config)
        ),
        "configuration_readiness": await _configuration_readiness(hass, entry, runtime_data),
        "last_lifecycle_failure": lifecycle_failures_for_entry(hass, entry.entry_id),
        "runtime": {"status": "unloaded" if host is None else "active"},
    }
    if host is None:
        return result

    snapshot = host.snapshot_source.snapshot_at(datetime.now(UTC))
    registry = er.async_get(hass)
    entity_ids = sorted(item.entity_id for item in er.async_entries_for_config_entry(registry, entry.entry_id))
    source_resilience = await host.async_source_resilience_diagnostics()
    operational_events = host.operational_event_diagnostics()
    user_activities = host.user_activity_diagnostics()
    notification_policy = host.notification_diagnostics()
    result.update(
        {
            "versions": {
                "integration": snapshot.integration_version,
                "core": snapshot.core_version,
            },
            "operational_snapshot": snapshot_to_dict(snapshot),
            "decision_trace": trace_to_dict(host.snapshot_source.trace),
            "observability": host.observability.diagnostics(datetime.now(UTC)),
            "heat_delivery": [_heat_delivery_state(state) for state in host.heat_delivery_states],
            "heating_diagnostics": heating_diagnostics_to_dict(snapshot.heating_diagnostics),
            "runtime_supervision": host.runtime_supervision_diagnostics(),
            "operational_events": operational_events,
            "user_activities": user_activities,
            "notification_policy": notification_policy,
            "source_resilience": source_resilience,
            "counters": {
                "snapshot_revision": snapshot.revision,
                "decision_trace_records": len(host.snapshot_source.trace),
                "operational_event_records": operational_events["retained_count"],
                "user_activity_records": user_activities["retained_count"],
                "duplicate_commands_suppressed": snapshot.duplicate_commands_suppressed,
            },
            "entity_ids": entity_ids,
            "active_issue_ids": list(host.active_issue_ids),
        }
    )
    return result
