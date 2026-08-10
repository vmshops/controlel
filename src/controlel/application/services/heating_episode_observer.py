"""Bounded, in-memory observation of confirmed zone-heating episodes."""

from collections import deque
from dataclasses import replace
from datetime import datetime
from math import isfinite

from controlel.application.state.source_control_state import SourceControlState
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.heat_delivery import (
    HeatDeliveryActivity,
    HeatDeliveryObservation,
    HeatDeliveryState,
    HeatingDemandTransition,
    HeatingEpisode,
    HeatingEpisodeSample,
    HeatingEpisodeTerminationReason,
    HeatSourceObservation,
    ObservationQuality,
    ObservedValue,
)
from controlel.domain.value_objects.zone_id import ZoneId


class HeatingEpisodeObserver:
    """Observe existing decisions without scheduling or issuing commands."""

    def __init__(
        self,
        *,
        max_completed_episodes: int = 20,
        max_samples_per_episode: int = 100,
    ) -> None:
        if max_completed_episodes <= 0:
            raise ValueError("max_completed_episodes must be positive")
        if max_samples_per_episode <= 0:
            raise ValueError("max_samples_per_episode must be positive")
        self._max_samples_per_episode = max_samples_per_episode
        self._active: dict[ZoneId, HeatingEpisode] = {}
        self._completed: deque[HeatingEpisode] = deque(maxlen=max_completed_episodes)

    def observe(
        self,
        *,
        zone_id: ZoneId,
        confirmed_demand: BuildingHeatDemandStatus,
        target_temperature: float,
        zone_temperature: ObservedValue[float],
        actuator_observations: tuple[HeatDeliveryObservation, ...],
        source_observation: HeatSourceObservation,
        captured_at: datetime,
    ) -> HeatingEpisode | None:
        if not isfinite(target_temperature):
            raise ValueError("target_temperature must be finite")
        _aware(captured_at, "captured_at")
        if source_observation.captured_at != captured_at:
            raise ValueError("source observation must use captured_at")
        ordered_actuators = tuple(sorted(actuator_observations, key=lambda item: item.actuator_id.value))
        for observation in ordered_actuators:
            if observation.zone_id != zone_id:
                raise ValueError("actuator observation must belong to zone_id")
            if observation.captured_at != captured_at:
                raise ValueError("actuator observation must use captured_at")

        active = self._active.get(zone_id)
        if active is None and confirmed_demand is not BuildingHeatDemandStatus.HEAT_REQUIRED:
            return None

        sample = HeatingEpisodeSample(
            captured_at=captured_at,
            zone_temperature=zone_temperature,
            target_temperature=target_temperature,
            actuator_observations=ordered_actuators,
            source_observation=source_observation,
        )
        trusted_temperature = (
            float(zone_temperature.value)
            if zone_temperature.quality is ObservationQuality.VALID and zone_temperature.value is not None
            else None
        )
        if active is None:
            active = HeatingEpisode(
                zone_id=zone_id,
                started_at=captured_at,
                ended_at=None,
                termination_reason=None,
                initial_target_temperature=target_temperature,
                current_target_temperature=target_temperature,
                initial_temperature=trusted_temperature,
                current_temperature=trusted_temperature,
                demand_transitions=(
                    HeatingDemandTransition(
                        demand=BuildingHeatDemandStatus.HEAT_REQUIRED,
                        changed_at=captured_at,
                    ),
                ),
                samples=(sample,),
            )
            self._active[zone_id] = active
            return active

        samples = (*active.samples, sample)[-self._max_samples_per_episode :]
        transitions = active.demand_transitions
        if confirmed_demand is not transitions[-1].demand:
            transitions = (
                *transitions,
                HeatingDemandTransition(demand=confirmed_demand, changed_at=captured_at),
            )
        updated = replace(
            active,
            current_target_temperature=target_temperature,
            current_temperature=(
                trusted_temperature if trusted_temperature is not None else active.current_temperature
            ),
            demand_transitions=transitions,
            samples=samples,
        )
        if confirmed_demand is BuildingHeatDemandStatus.HEAT_REQUIRED:
            self._active[zone_id] = updated
            return updated

        reason = (
            HeatingEpisodeTerminationReason.DEMAND_CLEARED
            if confirmed_demand is BuildingHeatDemandStatus.NO_HEAT_REQUIRED
            else HeatingEpisodeTerminationReason.DEMAND_INDETERMINATE
        )
        completed = replace(updated, ended_at=captured_at, termination_reason=reason)
        del self._active[zone_id]
        self._completed.append(completed)
        return completed

    def terminate_all(
        self,
        *,
        ended_at: datetime,
        reason: HeatingEpisodeTerminationReason,
    ) -> tuple[HeatingEpisode, ...]:
        _aware(ended_at, "ended_at")
        if reason not in {
            HeatingEpisodeTerminationReason.RUNTIME_STOPPED,
            HeatingEpisodeTerminationReason.FATAL_SHUTDOWN,
        }:
            raise ValueError("terminate_all requires a runtime termination reason")
        terminated = []
        for zone_id in sorted(self._active, key=lambda item: item.value):
            episode = replace(
                self._active[zone_id],
                ended_at=ended_at,
                termination_reason=reason,
            )
            terminated.append(episode)
            self._completed.append(episode)
        self._active.clear()
        return tuple(terminated)

    @property
    def active_episodes(self) -> tuple[HeatingEpisode, ...]:
        return tuple(self._active[zone_id] for zone_id in sorted(self._active, key=lambda item: item.value))

    @property
    def completed_episodes(self) -> tuple[HeatingEpisode, ...]:
        return tuple(self._completed)


def heat_delivery_observation_from_state(
    state: HeatDeliveryState,
    *,
    captured_at: datetime,
) -> HeatDeliveryObservation:
    """Project existing M30 evidence without inventing report timestamps."""

    return HeatDeliveryObservation(
        zone_id=state.zone_id,
        actuator_id=state.actuator_id,
        captured_at=captured_at,
        mode=state.mode,
        capabilities=state.capabilities,
        commanded_target_temperature=state.commanded_target_temperature,
        commanded_position=state.commanded_position,
        commanded_binary_open=state.commanded_binary_open,
        commanded_remote_temperature=state.commanded_remote_temperature,
        last_requested_command=state.last_requested_command,
        last_successful_command=state.last_successful_command,
        last_command_outcome=state.last_command_outcome,
        last_command_timestamp=state.last_command_timestamp,
        reported_target_temperature=_reported_float(
            value=state.reported_target_temperature,
            supported=state.capabilities.can_read_target_temperature,
            label="reported target temperature",
        ),
        reported_local_temperature=(
            ObservedValue.unknown("no actuator-local temperature has been reported")
            if state.capabilities.can_read_local_temperature
            else ObservedValue.unsupported("actuator cannot report local temperature")
        ),
        reported_position=_reported_float(
            value=state.reported_position,
            supported=state.capabilities.can_read_valve_position,
            label="reported position",
        ),
        reported_binary_open=(
            ObservedValue(
                value=state.reported_binary_open,
                observed_at=None,
                quality=ObservationQuality.DEGRADED,
                reason="reported binary state has no source timestamp",
            )
            if state.reported_binary_open is not None
            else ObservedValue.unknown("no binary state has been reported")
        ),
        reported_activity=(
            ObservedValue[HeatDeliveryActivity].unknown("no actuator activity has been reported")
            if state.capabilities.can_read_hvac_action
            else ObservedValue[HeatDeliveryActivity].unsupported("actuator cannot report activity")
        ),
    )


def heat_source_observation_from_state(
    state: SourceControlState | None,
    *,
    captured_at: datetime,
) -> HeatSourceObservation:
    """Project source command evidence while leaving physical availability unknown."""

    if state is None or state.last_dispatched_command is None:
        return HeatSourceObservation(
            captured_at=captured_at,
            last_requested_action=(state.last_requested_command if state is not None else None),
        )
    return HeatSourceObservation(
        captured_at=captured_at,
        last_requested_action=state.last_requested_command,
        last_successful_dispatch_action=state.last_dispatched_command,
        last_successful_dispatch_at=state.last_dispatch_timestamp,
    )


def _reported_float(
    *,
    value: float | None,
    supported: bool,
    label: str,
) -> ObservedValue[float]:
    if not supported:
        return ObservedValue.unsupported(f"actuator cannot provide {label}")
    if value is None:
        return ObservedValue.unknown(f"no {label} has been reported")
    return ObservedValue(
        value=value,
        observed_at=None,
        quality=ObservationQuality.DEGRADED,
        reason=f"{label} has no source timestamp",
    )


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
