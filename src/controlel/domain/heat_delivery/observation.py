"""Immutable, truthful heat-delivery observation contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.value_objects.zone_id import ZoneId

from .model import (
    HeatDeliveryActuatorId,
    HeatDeliveryCapabilities,
    HeatDeliveryCommand,
    HeatDeliveryCommandOutcome,
    HeatDeliveryMode,
)


class ObservationQuality(StrEnum):
    UNKNOWN = "unknown"
    VALID = "valid"
    STALE = "stale"
    DEGRADED = "degraded"
    CONFLICTING = "conflicting"
    UNSUPPORTED = "unsupported"


class HeatDeliveryActivity(StrEnum):
    HEATING = "heating"
    IDLE = "idle"
    OFF = "off"


class HeatingEpisodeTerminationReason(StrEnum):
    DEMAND_CLEARED = "demand_cleared"
    DEMAND_INDETERMINATE = "demand_indeterminate"
    RUNTIME_STOPPED = "runtime_stopped"
    FATAL_SHUTDOWN = "fatal_shutdown"


@dataclass(frozen=True)
class ObservedValue[T]:
    """One reported value with explicit availability and quality."""

    value: T | None
    observed_at: datetime | None
    quality: ObservationQuality
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at is not None:
            _aware(self.observed_at, "observed_at")
        if self.quality in {ObservationQuality.VALID, ObservationQuality.STALE}:
            if self.value is None or self.observed_at is None:
                raise ValueError(f"{self.quality.value} observation requires a value and timestamp")
        if self.quality in {ObservationQuality.UNKNOWN, ObservationQuality.UNSUPPORTED}:
            if self.value is not None or self.observed_at is not None:
                raise ValueError(f"{self.quality.value} observation cannot contain a value or timestamp")
        if (
            self.quality
            in {
                ObservationQuality.STALE,
                ObservationQuality.DEGRADED,
                ObservationQuality.CONFLICTING,
            }
            and not self.reason
        ):
            raise ValueError(f"{self.quality.value} observation requires an explainable reason")

    @classmethod
    def unknown(cls, reason: str | None = None) -> "ObservedValue[T]":
        return cls(value=None, observed_at=None, quality=ObservationQuality.UNKNOWN, reason=reason)

    @classmethod
    def unsupported(cls, reason: str | None = None) -> "ObservedValue[T]":
        return cls(value=None, observed_at=None, quality=ObservationQuality.UNSUPPORTED, reason=reason)

    @classmethod
    def valid(cls, value: T, observed_at: datetime) -> "ObservedValue[T]":
        return cls(value=value, observed_at=observed_at, quality=ObservationQuality.VALID)


@dataclass(frozen=True)
class HeatDeliveryObservation:
    """Command evidence and separately reported actuator evidence."""

    zone_id: ZoneId
    actuator_id: HeatDeliveryActuatorId
    captured_at: datetime
    mode: HeatDeliveryMode
    capabilities: HeatDeliveryCapabilities
    commanded_target_temperature: float | None = None
    commanded_position: float | None = None
    commanded_binary_open: bool | None = None
    commanded_remote_temperature: float | None = None
    last_requested_command: HeatDeliveryCommand | None = None
    last_successful_command: HeatDeliveryCommand | None = None
    last_command_outcome: HeatDeliveryCommandOutcome | None = None
    last_command_timestamp: datetime | None = None
    reported_target_temperature: ObservedValue[float] = ObservedValue.unsupported()
    reported_local_temperature: ObservedValue[float] = ObservedValue.unsupported()
    reported_position: ObservedValue[float] = ObservedValue.unsupported()
    reported_binary_open: ObservedValue[bool] = ObservedValue.unknown()
    reported_activity: ObservedValue[HeatDeliveryActivity] = ObservedValue.unsupported()

    def __post_init__(self) -> None:
        _aware(self.captured_at, "captured_at")
        if self.last_command_timestamp is not None:
            _aware(self.last_command_timestamp, "last_command_timestamp")
        for command, label in (
            (self.last_requested_command, "last_requested_command"),
            (self.last_successful_command, "last_successful_command"),
        ):
            if command is not None and (command.zone_id != self.zone_id or command.actuator_id != self.actuator_id):
                raise ValueError(f"{label} must belong to the observed zone and actuator")
        for value, label in (
            (self.commanded_target_temperature, "commanded_target_temperature"),
            (self.commanded_position, "commanded_position"),
            (self.commanded_remote_temperature, "commanded_remote_temperature"),
        ):
            if value is not None and not isfinite(value):
                raise ValueError(f"{label} must be finite")
        if self.commanded_position is not None and not 0 <= self.commanded_position <= 100:
            raise ValueError("commanded_position must be between 0 and 100")
        _validate_capability_quality(
            self.capabilities.can_read_target_temperature,
            self.reported_target_temperature.quality,
            "reported target temperature",
        )
        _validate_capability_quality(
            self.capabilities.can_read_local_temperature,
            self.reported_local_temperature.quality,
            "reported local temperature",
        )
        _validate_capability_quality(
            self.capabilities.can_read_valve_position,
            self.reported_position.quality,
            "reported position",
        )
        _validate_capability_quality(
            self.capabilities.can_read_hvac_action,
            self.reported_activity.quality,
            "reported activity",
        )


@dataclass(frozen=True)
class HeatSourceObservation:
    """Source command evidence without inferred physical heat availability."""

    captured_at: datetime
    last_requested_action: HeatingAction | None = None
    last_successful_dispatch_action: HeatingAction | None = None
    last_successful_dispatch_at: datetime | None = None
    reported_heat_available: ObservedValue[bool] = ObservedValue.unknown("physical source availability is not reported")

    def __post_init__(self) -> None:
        _aware(self.captured_at, "captured_at")
        if self.last_successful_dispatch_at is not None:
            _aware(self.last_successful_dispatch_at, "last_successful_dispatch_at")
        if (self.last_successful_dispatch_action is None) != (self.last_successful_dispatch_at is None):
            raise ValueError("successful source dispatch action and timestamp must coexist")


@dataclass(frozen=True)
class HeatingDemandTransition:
    demand: BuildingHeatDemandStatus
    changed_at: datetime

    def __post_init__(self) -> None:
        _aware(self.changed_at, "changed_at")


@dataclass(frozen=True)
class HeatingEpisodeSample:
    captured_at: datetime
    zone_temperature: ObservedValue[float]
    target_temperature: float
    actuator_observations: tuple[HeatDeliveryObservation, ...]
    source_observation: HeatSourceObservation

    def __post_init__(self) -> None:
        _aware(self.captured_at, "captured_at")
        if not isfinite(self.target_temperature):
            raise ValueError("target_temperature must be finite")
        if self.source_observation.captured_at != self.captured_at:
            raise ValueError("source observation must use the sample capture time")
        for observation in self.actuator_observations:
            if observation.captured_at != self.captured_at:
                raise ValueError("actuator observations must use the sample capture time")


@dataclass(frozen=True)
class HeatingEpisode:
    zone_id: ZoneId
    started_at: datetime
    ended_at: datetime | None
    termination_reason: HeatingEpisodeTerminationReason | None
    initial_target_temperature: float
    current_target_temperature: float
    initial_temperature: float | None
    current_temperature: float | None
    demand_transitions: tuple[HeatingDemandTransition, ...]
    samples: tuple[HeatingEpisodeSample, ...]

    def __post_init__(self) -> None:
        _aware(self.started_at, "started_at")
        if self.ended_at is not None:
            _aware(self.ended_at, "ended_at")
            if self.ended_at < self.started_at:
                raise ValueError("episode cannot end before it starts")
        if (self.ended_at is None) != (self.termination_reason is None):
            raise ValueError("episode end time and termination reason must coexist")
        if not self.demand_transitions:
            raise ValueError("episode requires at least one demand transition")
        first_transition = self.demand_transitions[0]
        if first_transition.demand is not BuildingHeatDemandStatus.HEAT_REQUIRED:
            raise ValueError("episode must begin with confirmed heat demand")
        if first_transition.changed_at != self.started_at:
            raise ValueError("first demand transition must match episode start")
        for sample in self.samples:
            for observation in sample.actuator_observations:
                if observation.zone_id != self.zone_id:
                    raise ValueError("actuator observations must belong to the episode zone")


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _validate_capability_quality(
    supported: bool,
    quality: ObservationQuality,
    label: str,
) -> None:
    if supported and quality is ObservationQuality.UNSUPPORTED:
        raise ValueError(f"{label} cannot be unsupported when read capability exists")
    if not supported and quality is not ObservationQuality.UNSUPPORTED:
        raise ValueError(f"{label} must be unsupported without read capability")
