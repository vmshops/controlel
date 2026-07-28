"""Privacy-minimized diagnostics for one Controlel config entry."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import ControlelEntryRuntime
from .config import HomeAssistantIntegrationConfig
from .const import (
    CONF_CONTROLLED_ENTITY_ID,
    CONF_DISABLE_SERVICE_DOMAIN,
    CONF_DISABLE_SERVICE_NAME,
    CONF_DISABLE_TARGET_ENTITY_ID,
    CONF_ENABLE_SERVICE_DOMAIN,
    CONF_ENABLE_SERVICE_NAME,
    CONF_ENABLE_TARGET_ENTITY_ID,
    CONF_HEAT_SOURCE_CONTROL_MODE,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_INDETERMINATE_TIMEOUT_ACTION,
    CONF_MAX_FUTURE_SKEW,
    CONF_PRIMARY_MEASUREMENT_MAX_AGE,
    CONF_SENSOR_ID,
    CONF_SENSOR_NAME,
    CONF_TARGET_TEMPERATURE,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_ZONE_ID,
    CONF_ZONE_NAME,
    CONTROL_MODE_CUSTOM,
)
from .operational import snapshot_to_dict, trace_to_dict

_COMMON_MUTABLE_KEYS = (
    CONF_ZONE_NAME,
    CONF_SENSOR_NAME,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_TARGET_TEMPERATURE,
    CONF_PRIMARY_MEASUREMENT_MAX_AGE,
    CONF_MAX_FUTURE_SKEW,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_INDETERMINATE_TIMEOUT_ACTION,
    CONF_HEAT_SOURCE_CONTROL_MODE,
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
        "primary_measurement_max_age_seconds": config.primary_measurement_max_age.total_seconds(),
        "max_future_skew_seconds": config.max_future_skew.total_seconds(),
        "indeterminate_grace_period_seconds": config.indeterminate_grace_period.total_seconds(),
        "indeterminate_timeout_action": config.indeterminate_timeout_action.value,
        "heat_source_control_mode": config.heat_source_control_mode,
        "controlled_entity_id": config.controlled_entity_id,
        "enable_service": _service_call(config.heat_source.enable_heating),
        "disable_service": _service_call(config.heat_source.disable_heating),
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
    return "generated_new_entry_default"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry[ControlelEntryRuntime],
) -> dict[str, Any]:
    runtime_data = entry.runtime_data
    host = runtime_data.host
    if host is None:
        return {
            "configuration": _normalized_config(runtime_data.config),
            "configuration_provenance": _configuration_provenance(
                entry.data,
                entry.options,
                runtime_data.config,
            ),
            "runtime": {"status": "unloaded"},
        }

    snapshot = host.snapshot_source.snapshot_at(datetime.now(UTC))
    registry = er.async_get(hass)
    entity_ids = sorted(item.entity_id for item in er.async_entries_for_config_entry(registry, entry.entry_id))
    return {
        "configuration": _normalized_config(runtime_data.config),
        "configuration_provenance": _configuration_provenance(
            entry.data,
            entry.options,
            runtime_data.config,
        ),
        "versions": {
            "integration": snapshot.integration_version,
            "core": snapshot.core_version,
        },
        "operational_snapshot": snapshot_to_dict(snapshot),
        "decision_trace": trace_to_dict(host.snapshot_source.trace),
        "counters": {
            "snapshot_revision": snapshot.revision,
            "decision_trace_records": len(host.snapshot_source.trace),
            "duplicate_commands_suppressed": snapshot.duplicate_commands_suppressed,
        },
        "entity_ids": entity_ids,
        "active_issue_ids": list(host.active_issue_ids),
    }
