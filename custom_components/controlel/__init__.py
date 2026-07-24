"""Controlel Home Assistant custom integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.domain.capabilities.temperature_capability import (
    TemperatureCapability,
)
from controlel.domain.entities.zone import Zone
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.infrastructure.time.system_clock import SystemClock

from .config import integration_config_from_entry_data
from .event_loop_bridge import HomeAssistantEventLoopBridge
from .failure_sink import HomeAssistantScheduledFailureSink
from .heat_source import HomeAssistantHeatSourcePort
from .host import HomeAssistantControlelHost
from .measurement_ingestion import HomeAssistantMeasurementMapper
from .runtime_executor import HomeAssistantRuntimeExecutor
from .scheduler import HomeAssistantScheduler

LOGGER = logging.getLogger(__name__)


@dataclass
class ControlelEntryRuntime:
    host: HomeAssistantControlelHost | None


if TYPE_CHECKING:
    type ControlelConfigEntry = ConfigEntry[ControlelEntryRuntime]
else:
    type ControlelConfigEntry = Any


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlelConfigEntry,
) -> bool:
    """Set up one Controlel runtime from a config entry."""
    config = integration_config_from_entry_data(entry.data)

    sensor_repository = SensorRepository()
    zone_repository = ZoneRepository()
    sensor = Sensor(
        sensor_id=config.sensor_id,
        zone_id=config.zone_id,
        name=config.sensor_name,
        capabilities=[TemperatureCapability()],
    )
    zone = Zone(
        zone_id=config.zone_id,
        primary_sensor_id=config.sensor_id,
        primary_measurement_max_age=config.primary_measurement_max_age,
        name=config.zone_name,
        target_temperature=config.target_temperature,
    )
    if sensor.zone_id != zone.zone_id or zone.primary_sensor_id != sensor.sensor_id:
        raise ValueError("Controlel sensor and primary-zone configuration do not match")
    sensor_repository.add(sensor)
    zone_repository.add(zone)

    executor = HomeAssistantRuntimeExecutor()
    host: HomeAssistantControlelHost | None = None
    failure_sink: HomeAssistantScheduledFailureSink | None = None
    try:
        bridge = HomeAssistantEventLoopBridge(hass.loop)

        def submit_runtime_callback(callback) -> None:
            if host is not None:
                host.submit_scheduled_callback(callback)

        scheduler = HomeAssistantScheduler(
            hass=hass,
            bridge=bridge,
            submit_runtime_callback=submit_runtime_callback,
        )
        failure_sink = HomeAssistantScheduledFailureSink(
            hass=hass,
            bridge=bridge,
            entry_id=entry.entry_id,
            logger=LOGGER,
        )
        heat_source_port = HomeAssistantHeatSourcePort(
            hass=hass,
            bridge=bridge,
            binding=config.heat_source,
            on_success=failure_sink.clear_service_failure_issue,
        )
        runtime = ControlRuntime(
            sensor_repository=sensor_repository,
            zone_repository=zone_repository,
            heat_source_port=heat_source_port,
            clock=SystemClock(),
            scheduler=scheduler,
            scheduled_failure_sink=failure_sink,
            max_future_skew=config.max_future_skew,
            indeterminate_grace_period=config.indeterminate_grace_period,
            indeterminate_timeout_action=config.indeterminate_timeout_action,
        )
        host = HomeAssistantControlelHost(
            hass=hass,
            runtime=runtime,
            executor=executor,
            measurement_mapper=HomeAssistantMeasurementMapper(config.sensor_binding),
            failure_sink=failure_sink,
            temperature_entity_id=config.temperature_entity_id,
            logger=LOGGER,
        )
        failure_sink.bind_fatal_handler(host.request_fatal_shutdown)
        await host.async_initialize()
    except BaseException:
        try:
            if host is not None:
                host.clear_transient_issues()
                await host.async_stop()
            else:
                if failure_sink is not None:
                    failure_sink.clear_transient_issues()
                await executor.async_close()
        except Exception:
            LOGGER.exception("Failed to clean up a partially constructed Controlel host")
        raise

    entry.runtime_data = ControlelEntryRuntime(host=host)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ControlelConfigEntry,
) -> bool:
    """Unload the entry through the host's terminal serialized stop path."""
    runtime_data = entry.runtime_data
    host = runtime_data.host
    if host is not None:
        await host.async_stop()
        runtime_data.host = None
    return True
