"""Controlel Home Assistant custom integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from controlel.application.runtime.control_runtime import ControlRuntime as CoreControlRuntime
from controlel.domain.capabilities.temperature_capability import (
    TemperatureCapability,
)
from controlel.domain.entities.zone import Zone
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.infrastructure.time.system_clock import SystemClock

from .config import HomeAssistantIntegrationConfig, integration_config_from_entry
from .event_loop_bridge import HomeAssistantEventLoopBridge
from .failure_sink import HomeAssistantScheduledFailureSink, clear_entry_issues
from .heat_source import HomeAssistantHeatSourcePort
from .host import HomeAssistantControlelHost
from .measurement_ingestion import HomeAssistantMeasurementMapper
from .runtime_executor import HomeAssistantRuntimeExecutor
from .scheduler import HomeAssistantScheduler

LOGGER = logging.getLogger(__name__)
PLATFORMS = ("sensor", "binary_sensor")


class ControlRuntime(CoreControlRuntime):
    """Use HA state objects, rather than an empty core evaluation, to begin regulation."""

    def start(self) -> None:
        """Start the HA-owned lifecycle without fabricating a measurement."""


@dataclass
class ControlelEntryRuntime:
    host: HomeAssistantControlelHost | None
    config: HomeAssistantIntegrationConfig
    reloading: bool = False


if TYPE_CHECKING:
    type ControlelConfigEntry = ConfigEntry[ControlelEntryRuntime]
else:
    type ControlelConfigEntry = Any


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlelConfigEntry,
) -> bool:
    """Set up one Controlel runtime from a config entry."""
    config = integration_config_from_entry(entry.data, entry.options)
    zone_control = config.zone_control
    heat_source_configuration = config.heat_source_configuration

    sensor_repository = SensorRepository()
    zone_repository = ZoneRepository()
    sensor = Sensor(
        sensor_id=zone_control.sensor_id,
        zone_id=zone_control.zone_id,
        name=zone_control.sensor_name,
        capabilities=[TemperatureCapability()],
    )
    zone = Zone(
        zone_id=zone_control.zone_id,
        primary_sensor_id=zone_control.sensor_id,
        primary_measurement_max_age=zone_control.primary_measurement_max_age,
        name=zone_control.zone_name,
        target_temperature=zone_control.target_temperature,
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
            binding=heat_source_configuration.binding,
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
            heating_turn_on_differential=zone_control.heating_turn_on_differential,
            heating_turn_off_differential=zone_control.heating_turn_off_differential,
            heat_demand_confirmation_duration=(zone_control.heat_demand_confirmation_duration),
            minimum_heating_on_time=heat_source_configuration.minimum_heating_on_time,
            minimum_heating_off_time=heat_source_configuration.minimum_heating_off_time,
        )
        host = HomeAssistantControlelHost(
            hass=hass,
            runtime=runtime,
            executor=executor,
            measurement_mapper=HomeAssistantMeasurementMapper(config.sensor_binding),
            failure_sink=failure_sink,
            config=config,
            core_version=metadata.version("controlel"),
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

    entry.runtime_data = ControlelEntryRuntime(host=host, config=config)
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await host.async_stop()
        entry.runtime_data.host = None
        raise
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ControlelConfigEntry,
) -> bool:
    """Unload the entry through the host's terminal serialized stop path."""
    runtime_data = entry.runtime_data
    platforms_unloaded = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )
    host = runtime_data.host
    if host is not None:
        await host.async_stop()
        runtime_data.host = None
    return platforms_unloaded


async def async_remove_entry(
    hass: HomeAssistant,
    entry: ControlelConfigEntry,
) -> None:
    """Remove Repairs issues that belong to a deleted config entry."""
    clear_entry_issues(hass, entry.entry_id)


async def _async_update_listener(
    hass: HomeAssistant,
    entry: ControlelConfigEntry,
) -> None:
    """Update the title and reload once after an atomic options change."""

    runtime_data = entry.runtime_data
    config = integration_config_from_entry(entry.data, entry.options)
    if runtime_data.config == config and entry.title == config.zone_name:
        return
    if runtime_data.reloading:
        return
    runtime_data.reloading = True
    if entry.title != config.zone_name:
        hass.config_entries.async_update_entry(
            entry,
            title=config.zone_name,
        )
    await hass.config_entries.async_reload(entry.entry_id)
    LOGGER.info("Controlel configuration reloaded entry_id=%s", entry.entry_id)
