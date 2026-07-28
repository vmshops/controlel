"""Privacy-minimized diagnostics for one Controlel config entry."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import ControlelEntryRuntime
from .config import HomeAssistantIntegrationConfig
from .operational import snapshot_to_dict, trace_to_dict


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


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry[ControlelEntryRuntime],
) -> dict[str, Any]:
    runtime_data = entry.runtime_data
    host = runtime_data.host
    if host is None:
        return {
            "configuration": _normalized_config(runtime_data.config),
            "runtime": {"status": "unloaded"},
        }

    snapshot = host.snapshot_source.snapshot_at(datetime.now(UTC))
    registry = er.async_get(hass)
    entity_ids = sorted(item.entity_id for item in er.async_entries_for_config_entry(registry, entry.entry_id))
    return {
        "configuration": _normalized_config(runtime_data.config),
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
