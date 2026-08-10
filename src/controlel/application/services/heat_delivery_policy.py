"""Deterministic Milestone 30 zone heat-delivery policy."""

from datetime import datetime

from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.heat_delivery import (
    HeatDeliveryActuatorConfiguration,
    HeatDeliveryAssistPolicy,
    HeatDeliveryCommand,
    HeatDeliveryCommandKind,
    HeatDeliveryMode,
    HeatDeliveryOwnership,
)


class HeatDeliveryPolicy:
    def desired_commands(
        self,
        configuration: HeatDeliveryActuatorConfiguration,
        *,
        confirmed_demand: BuildingHeatDemandStatus,
        zone_target_temperature: float,
        valid_zone_measurement_temperature: float | None,
        now: datetime,
    ) -> tuple[HeatDeliveryCommand, ...]:
        if confirmed_demand is BuildingHeatDemandStatus.INDETERMINATE:
            return ()
        commands: list[HeatDeliveryCommand] = []
        if configuration.ownership is HeatDeliveryOwnership.CONTROLEL_OWNED:
            if configuration.mode is HeatDeliveryMode.NATIVE:
                commands.append(
                    self._command(
                        configuration, HeatDeliveryCommandKind.SET_TARGET_TEMPERATURE, zone_target_temperature, now
                    )
                )
            elif configuration.mode is HeatDeliveryMode.SETPOINT_ASSIST:
                assist = (
                    confirmed_demand is BuildingHeatDemandStatus.HEAT_REQUIRED
                    and configuration.assist_policy is HeatDeliveryAssistPolicy.ALWAYS_ASSIST_WHILE_HEATING
                )
                value = configuration.assist_target_temperature if assist else zone_target_temperature
                if value is not None:
                    commands.append(
                        self._command(configuration, HeatDeliveryCommandKind.SET_TARGET_TEMPERATURE, value, now)
                    )
            elif configuration.mode is HeatDeliveryMode.DIRECT_POSITION:
                value = (
                    configuration.heating_position
                    if confirmed_demand is BuildingHeatDemandStatus.HEAT_REQUIRED
                    else configuration.idle_position
                )
                if value is not None:
                    commands.append(self._command(configuration, HeatDeliveryCommandKind.SET_POSITION, value, now))
            elif configuration.mode is HeatDeliveryMode.BINARY:
                commands.append(
                    self._command(
                        configuration,
                        HeatDeliveryCommandKind.SET_BINARY_OPEN,
                        confirmed_demand is BuildingHeatDemandStatus.HEAT_REQUIRED,
                        now,
                    )
                )
        if configuration.forward_remote_temperature and valid_zone_measurement_temperature is not None:
            commands.append(
                self._command(
                    configuration,
                    HeatDeliveryCommandKind.WRITE_REMOTE_TEMPERATURE,
                    valid_zone_measurement_temperature,
                    now,
                )
            )
        return tuple(commands)

    @staticmethod
    def _command(
        configuration: HeatDeliveryActuatorConfiguration,
        kind: HeatDeliveryCommandKind,
        value: float | bool,
        now: datetime,
    ) -> HeatDeliveryCommand:
        return HeatDeliveryCommand(
            actuator_id=configuration.actuator_id,
            zone_id=configuration.zone_id,
            kind=kind,
            value=value,
            requested_at=now,
        )
