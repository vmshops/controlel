"""Controlel Home Assistant custom integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from controlel.application.ports.heat_source_port import HeatSourcePort
from controlel.application.runtime.control_runtime import ControlRuntime
from controlel.application.runtime.control_runtime_assembly import ControlRuntimeAssembly
from controlel.application.runtime.control_runtime_startup import ControlRuntimeStartup
from controlel.application.runtime.failsafe_runtime import FailsafeRuntime
from controlel.application.runtime.runtime_supervisor import RuntimeSupervisor
from controlel.application.services.operational_event_recorder import OperationalEventRecorder
from controlel.application.state.runtime_supervision_state import RuntimeHandoverEvidence
from controlel.domain.capabilities.temperature_capability import (
    TemperatureCapability,
)
from controlel.domain.entities.zone import Zone
from controlel.domain.operating_mode import SafeHeatingProfile
from controlel.domain.repositories.sensor_repository import SensorRepository
from controlel.domain.repositories.zone_repository import ZoneRepository
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.source_control import SourceCapabilities, SourceOwnership
from controlel.infrastructure.time.system_clock import SystemClock

from .config import HomeAssistantIntegrationConfig, integration_config_from_entry
from .event_loop_bridge import HomeAssistantEventLoopBridge
from .failure_sink import HomeAssistantScheduledFailureSink, clear_entry_issues
from .heat_source import HomeAssistantHeatSourcePort
from .host import HomeAssistantControlelHost
from .measurement_ingestion import HomeAssistantMeasurementMapper
from .notifications import HomeAssistantNotificationCoordinator, HomeAssistantNotificationTransport
from .runtime_executor import HomeAssistantRuntimeExecutor
from .scheduler import HomeAssistantScheduler

LOGGER = logging.getLogger(__name__)
PLATFORMS = ("sensor", "binary_sensor")


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
    core_version = await hass.async_add_executor_job(metadata.version, "controlel")
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
        heat_delivery_controller = None
        heat_delivery = config.heat_delivery_configuration
        if heat_delivery.mode == "setpoint_assist":
            from controlel.application.services.zone_heat_delivery_controller import (
                ZoneHeatDeliveryController,
            )
            from controlel.domain.heat_delivery import (
                HeatDeliveryActuatorConfiguration,
                HeatDeliveryActuatorId,
                HeatDeliveryAssistPolicy,
                HeatDeliveryCapabilities,
                HeatDeliveryMode,
                HeatDeliveryOwnership,
            )

            from .heat_delivery import HomeAssistantHeatDeliveryPort

            if heat_delivery.actuator_entity_id is None:
                raise ValueError("setpoint assist requires an actuator entity")
            actuator_id = HeatDeliveryActuatorId(heat_delivery.actuator_entity_id)
            actuator_configuration = HeatDeliveryActuatorConfiguration(
                actuator_id=actuator_id,
                zone_id=zone.zone_id,
                capabilities=HeatDeliveryCapabilities(can_set_target_temperature=True),
                mode=HeatDeliveryMode(heat_delivery.mode),
                ownership=HeatDeliveryOwnership(heat_delivery.ownership),
                assist_policy=HeatDeliveryAssistPolicy(heat_delivery.assist_policy),
                assist_target_temperature=heat_delivery.assist_target_temperature,
            )
            heat_delivery_controller = ZoneHeatDeliveryController(
                (actuator_configuration,),
                {
                    actuator_id: HomeAssistantHeatDeliveryPort(
                        hass=hass,
                        bridge=bridge,
                        entity_id=heat_delivery.actuator_entity_id,
                    )
                },
            )
        operational_event_recorder = OperationalEventRecorder()
        runtime_assembly = ControlRuntimeAssembly(
            sensor_repository=sensor_repository,
            zone_repository=zone_repository,
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
            heat_delivery_controller=heat_delivery_controller,
            source_ownership=SourceOwnership.CONTROLEL_OWNED,
            source_capabilities=SourceCapabilities(),
            operational_event_recorder=operational_event_recorder,
        )

        def build_runtime(
            source_port: HeatSourcePort,
            handover: RuntimeHandoverEvidence | None = None,
        ) -> ControlRuntime:
            runtime = runtime_assembly.build(source_port, handover=handover)
            return runtime

        def failsafe_factory(source_port: HeatSourcePort) -> FailsafeRuntime:
            return FailsafeRuntime(
                source_port,
                SafeHeatingProfile(
                    room_target_temperature=zone_control.target_temperature.value,
                    turn_on_differential=zone_control.heating_turn_on_differential,
                    turn_off_differential=zone_control.heating_turn_off_differential,
                    preferred_sensor_id=zone_control.sensor_id,
                ),
                minimum_on_time=heat_source_configuration.minimum_heating_on_time,
                minimum_off_time=heat_source_configuration.minimum_heating_off_time,
                capabilities=SourceCapabilities(),
                ownership=SourceOwnership.CONTROLEL_OWNED,
            )

        def restart_factory(source_port: HeatSourcePort, handover: RuntimeHandoverEvidence) -> ControlRuntime:
            candidate = build_runtime(source_port, handover)
            ControlRuntimeStartup(candidate).begin()
            if host is None:
                raise RuntimeError("Controlel host is unavailable during runtime restart")
            host.replace_runtime_after_handover(candidate)
            return candidate

        supervisor = RuntimeSupervisor(
            source=heat_source_port,
            clock=runtime_assembly.clock,
            scheduler=scheduler,
            failsafe_factory=failsafe_factory,
            restart_factory=restart_factory,
            operational_event_recorder=operational_event_recorder,
        )
        runtime = build_runtime(supervisor.normal_port())
        supervisor.attach_normal_runtime(runtime)
        notification_coordinator = HomeAssistantNotificationCoordinator(
            config.notification_policy,
            operational_event_recorder.stream.snapshot,
            HomeAssistantNotificationTransport(hass, config.notification_policy),
            LOGGER,
        )
        host = HomeAssistantControlelHost(
            hass=hass,
            runtime=runtime,
            executor=executor,
            measurement_mapper=HomeAssistantMeasurementMapper(config.sensor_binding),
            failure_sink=failure_sink,
            config=config,
            core_version=core_version,
            logger=LOGGER,
            runtime_supervisor=supervisor,
            scheduled_callback_cleanup=scheduler.cancel_all,
            notification_coordinator=notification_coordinator,
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
