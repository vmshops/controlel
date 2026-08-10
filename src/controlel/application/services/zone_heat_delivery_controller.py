"""Per-zone heat-delivery dispatch, evidence, and duplicate suppression."""

from dataclasses import replace
from datetime import datetime

from controlel.application.ports.heat_delivery_actuator_port import HeatDeliveryActuatorPort
from controlel.application.services.heat_delivery_policy import HeatDeliveryPolicy
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.heat_delivery import (
    HeatDeliveryActuatorConfiguration,
    HeatDeliveryActuatorId,
    HeatDeliveryAssistPolicy,
    HeatDeliveryCommand,
    HeatDeliveryCommandKind,
    HeatDeliveryCommandOutcome,
    HeatDeliveryFailureKind,
    HeatDeliveryMode,
    HeatDeliveryState,
)
from controlel.domain.value_objects.zone_id import ZoneId


class ZoneHeatDeliveryController:
    """Own independent state for an ordered set of zone actuators."""

    def __init__(
        self,
        configurations: tuple[HeatDeliveryActuatorConfiguration, ...],
        ports: dict[HeatDeliveryActuatorId, HeatDeliveryActuatorPort],
        policy: HeatDeliveryPolicy | None = None,
    ) -> None:
        ordered = tuple(sorted(configurations, key=lambda item: (item.zone_id.value, item.actuator_id.value)))
        ids = [item.actuator_id for item in ordered]
        if len(set(ids)) != len(ids):
            raise ValueError("heat-delivery actuator IDs must be unique")
        missing = [
            item.actuator_id.value
            for item in ordered
            if (item.mode is not HeatDeliveryMode.UNMANAGED or item.forward_remote_temperature)
            and item.actuator_id not in ports
        ]
        if missing:
            raise ValueError(f"missing heat-delivery actuator ports: {', '.join(missing)}")
        self._configurations = ordered
        self._ports = dict(ports)
        self._policy = policy or HeatDeliveryPolicy()
        self._states = {
            item.actuator_id: HeatDeliveryState(
                actuator_id=item.actuator_id,
                zone_id=item.zone_id,
                mode=item.mode,
                ownership=item.ownership,
                capabilities=item.capabilities,
                assist_policy=item.assist_policy,
            )
            for item in ordered
        }
        self._successful_values: dict[tuple[HeatDeliveryActuatorId, HeatDeliveryCommandKind], float | bool] = {}

    def evaluate_zone(
        self,
        *,
        zone_id: ZoneId,
        confirmed_demand: BuildingHeatDemandStatus,
        zone_target_temperature: float,
        valid_zone_measurement_temperature: float | None,
        now: datetime,
    ) -> tuple[HeatDeliveryState, ...]:
        for configuration in self._configurations:
            if configuration.zone_id != zone_id:
                continue
            state = self._states[configuration.actuator_id]
            assist_active = (
                configuration.mode is HeatDeliveryMode.SETPOINT_ASSIST
                and configuration.assist_policy is HeatDeliveryAssistPolicy.ALWAYS_ASSIST_WHILE_HEATING
                and confirmed_demand is BuildingHeatDemandStatus.HEAT_REQUIRED
            )
            state = replace(
                state,
                assist_active=assist_active,
                zone_target_temperature=zone_target_temperature,
                zone_measurement_temperature=valid_zone_measurement_temperature,
                normal_actuator_target=zone_target_temperature
                if configuration.mode in {HeatDeliveryMode.NATIVE, HeatDeliveryMode.SETPOINT_ASSIST}
                else None,
            )
            self._states[configuration.actuator_id] = state
            for command in self._policy.desired_commands(
                configuration,
                confirmed_demand=confirmed_demand,
                zone_target_temperature=zone_target_temperature,
                valid_zone_measurement_temperature=valid_zone_measurement_temperature,
                now=now,
            ):
                self._dispatch(command)
        return self.states_for_zone(zone_id)

    def _dispatch(self, command: HeatDeliveryCommand) -> None:
        state = self._states[command.actuator_id]
        key = (command.actuator_id, command.kind)
        if self._successful_values.get(key, object()) == command.value:
            self._states[command.actuator_id] = replace(
                state,
                last_requested_command=command,
                last_command_outcome=HeatDeliveryCommandOutcome.SUPPRESSED_DUPLICATE,
                last_command_timestamp=command.requested_at,
            )
            return
        try:
            self._ports[command.actuator_id].execute(command)
        except Exception as error:
            self._states[command.actuator_id] = replace(
                state,
                last_requested_command=command,
                last_command_outcome=HeatDeliveryCommandOutcome.FAILED,
                last_command_timestamp=command.requested_at,
                actuator_failure_active=True,
                actuator_failure_kind=HeatDeliveryFailureKind.RECOVERABLE_COMMAND_FAILURE,
                actuator_failure_reason=f"{type(error).__name__}: {error}",
            )
            return
        self._successful_values[key] = command.value
        state = replace(
            state,
            last_requested_command=command,
            last_successful_command=command,
            last_command_outcome=HeatDeliveryCommandOutcome.DISPATCHED,
            last_command_timestamp=command.requested_at,
            actuator_failure_active=False,
            actuator_failure_kind=None,
            actuator_failure_reason=None,
        )
        if command.kind is HeatDeliveryCommandKind.SET_TARGET_TEMPERATURE:
            state = replace(state, commanded_target_temperature=float(command.value))
        elif command.kind is HeatDeliveryCommandKind.SET_POSITION:
            state = replace(state, commanded_position=float(command.value))
        elif command.kind is HeatDeliveryCommandKind.SET_BINARY_OPEN:
            state = replace(state, commanded_binary_open=bool(command.value))
        else:
            state = replace(state, commanded_remote_temperature=float(command.value))
        self._states[command.actuator_id] = state

    def record_reported_state(
        self,
        actuator_id: HeatDeliveryActuatorId,
        *,
        target_temperature: float | None = None,
        position: float | None = None,
        binary_open: bool | None = None,
    ) -> HeatDeliveryState:
        current = self._states[actuator_id]
        mismatches = []
        if (
            target_temperature is not None
            and current.commanded_target_temperature is not None
            and target_temperature != current.commanded_target_temperature
        ):
            mismatches.append("reported target temperature disagrees with commanded target")
        if position is not None and current.commanded_position is not None and position != current.commanded_position:
            mismatches.append("reported position disagrees with commanded position")
        if (
            binary_open is not None
            and current.commanded_binary_open is not None
            and binary_open != current.commanded_binary_open
        ):
            mismatches.append("reported binary state disagrees with commanded state")
        state = replace(
            current,
            reported_target_temperature=target_temperature,
            reported_position=position,
            reported_binary_open=binary_open,
            actuator_failure_active=bool(mismatches),
            actuator_failure_kind=(HeatDeliveryFailureKind.RECOVERABLE_COMMAND_FAILURE if mismatches else None),
            actuator_failure_reason="; ".join(mismatches) or None,
        )
        self._states[actuator_id] = state
        return state

    @property
    def states(self) -> tuple[HeatDeliveryState, ...]:
        return tuple(self._states[item.actuator_id] for item in self._configurations)

    def states_for_zone(self, zone_id: ZoneId) -> tuple[HeatDeliveryState, ...]:
        return tuple(state for state in self.states if state.zone_id == zone_id)
