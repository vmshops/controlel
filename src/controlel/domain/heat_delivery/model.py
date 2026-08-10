"""Truthful, capability-based zone heat-delivery domain models."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from controlel.domain.value_objects.zone_id import ZoneId


class HeatDeliveryMode(StrEnum):
    UNMANAGED = "unmanaged"
    NATIVE = "native"
    SETPOINT_ASSIST = "setpoint_assist"
    DIRECT_POSITION = "direct_position"
    BINARY = "binary"


class HeatDeliveryOwnership(StrEnum):
    DEVICE_OWNED = "device_owned"
    CONTROLEL_OWNED = "controlel_owned"


class HeatDeliveryAssistPolicy(StrEnum):
    NO_ASSIST = "no_assist"
    ALWAYS_ASSIST_WHILE_HEATING = "always_assist_while_heating"


class HeatDeliveryCommandKind(StrEnum):
    SET_TARGET_TEMPERATURE = "set_target_temperature"
    SET_POSITION = "set_position"
    SET_BINARY_OPEN = "set_binary_open"
    WRITE_REMOTE_TEMPERATURE = "write_remote_temperature"


class HeatDeliveryCommandOutcome(StrEnum):
    DISPATCHED = "dispatched"
    SUPPRESSED_DUPLICATE = "suppressed_duplicate"
    FAILED = "failed"


class HeatDeliveryFailureKind(StrEnum):
    RECOVERABLE_COMMAND_FAILURE = "recoverable_command_failure"
    CONFIGURATION_CAPABILITY_MISMATCH = "configuration_capability_mismatch"
    FATAL_ZONE_FAILURE = "fatal_zone_failure"


@dataclass(frozen=True, order=True)
class HeatDeliveryActuatorId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("heat-delivery actuator ID must be a non-empty string")


@dataclass(frozen=True)
class HeatDeliveryCapabilities:
    can_set_target_temperature: bool = False
    can_read_target_temperature: bool = False
    can_read_local_temperature: bool = False
    can_write_remote_temperature: bool = False
    can_read_valve_position: bool = False
    can_write_valve_position: bool = False
    can_open_close_binary: bool = False
    can_set_hvac_mode: bool = False
    can_read_hvac_action: bool = False


@dataclass(frozen=True)
class HeatDeliveryActuatorConfiguration:
    actuator_id: HeatDeliveryActuatorId
    zone_id: ZoneId
    capabilities: HeatDeliveryCapabilities
    mode: HeatDeliveryMode = HeatDeliveryMode.UNMANAGED
    ownership: HeatDeliveryOwnership = HeatDeliveryOwnership.DEVICE_OWNED
    assist_policy: HeatDeliveryAssistPolicy = HeatDeliveryAssistPolicy.NO_ASSIST
    assist_target_temperature: float | None = None
    heating_position: float | None = None
    idle_position: float | None = None
    forward_remote_temperature: bool = False

    def __post_init__(self) -> None:
        for value, label in (
            (self.assist_target_temperature, "assist target temperature"),
            (self.heating_position, "heating position"),
            (self.idle_position, "idle position"),
        ):
            if value is not None and (not isinstance(value, int | float) or not isfinite(value)):
                raise ValueError(f"{label} must be finite")
        for value, label in (
            (self.heating_position, "heating position"),
            (self.idle_position, "idle position"),
        ):
            if value is not None and not 0 <= value <= 100:
                raise ValueError(f"{label} must be between 0 and 100")
        if self.mode is HeatDeliveryMode.NATIVE and (
            self.ownership is HeatDeliveryOwnership.CONTROLEL_OWNED and not self.capabilities.can_set_target_temperature
        ):
            raise ValueError("Controlel-owned native mode requires target-temperature write capability")
        if self.mode is HeatDeliveryMode.SETPOINT_ASSIST:
            if self.ownership is not HeatDeliveryOwnership.CONTROLEL_OWNED:
                raise ValueError("setpoint assist requires Controlel-owned actuator state")
            if not self.capabilities.can_set_target_temperature:
                raise ValueError("setpoint assist requires target-temperature write capability")
            if self.assist_policy is HeatDeliveryAssistPolicy.ALWAYS_ASSIST_WHILE_HEATING and (
                self.assist_target_temperature is None
            ):
                raise ValueError("always-assist policy requires an assist target temperature")
        if self.mode is HeatDeliveryMode.DIRECT_POSITION:
            if self.ownership is not HeatDeliveryOwnership.CONTROLEL_OWNED:
                raise ValueError("direct position requires Controlel-owned actuator state")
            if not self.capabilities.can_write_valve_position:
                raise ValueError("direct position requires valve-position write capability")
            if self.heating_position is None or self.idle_position is None:
                raise ValueError("direct position requires heating and idle positions")
        if self.mode is HeatDeliveryMode.BINARY:
            if self.ownership is not HeatDeliveryOwnership.CONTROLEL_OWNED:
                raise ValueError("binary mode requires Controlel-owned actuator state")
            if not self.capabilities.can_open_close_binary:
                raise ValueError("binary mode requires binary open/close capability")
        if self.forward_remote_temperature and not self.capabilities.can_write_remote_temperature:
            raise ValueError("remote-temperature forwarding requires its explicit capability")


@dataclass(frozen=True)
class HeatDeliveryCommand:
    actuator_id: HeatDeliveryActuatorId
    zone_id: ZoneId
    kind: HeatDeliveryCommandKind
    value: float | bool
    requested_at: datetime

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        if self.kind is HeatDeliveryCommandKind.SET_BINARY_OPEN:
            if not isinstance(self.value, bool):
                raise ValueError("binary heat-delivery command value must be boolean")
            return
        if isinstance(self.value, bool) or not isinstance(self.value, int | float) or not isfinite(self.value):
            raise ValueError("numeric heat-delivery command value must be finite")
        if self.kind is HeatDeliveryCommandKind.SET_POSITION and not 0 <= self.value <= 100:
            raise ValueError("commanded position must be between 0 and 100")


@dataclass(frozen=True)
class HeatDeliveryState:
    actuator_id: HeatDeliveryActuatorId
    zone_id: ZoneId
    mode: HeatDeliveryMode
    ownership: HeatDeliveryOwnership
    capabilities: HeatDeliveryCapabilities
    assist_policy: HeatDeliveryAssistPolicy
    assist_active: bool = False
    zone_target_temperature: float | None = None
    zone_measurement_temperature: float | None = None
    normal_actuator_target: float | None = None
    commanded_target_temperature: float | None = None
    reported_target_temperature: float | None = None
    commanded_position: float | None = None
    reported_position: float | None = None
    commanded_binary_open: bool | None = None
    reported_binary_open: bool | None = None
    commanded_remote_temperature: float | None = None
    last_requested_command: HeatDeliveryCommand | None = None
    last_successful_command: HeatDeliveryCommand | None = None
    last_command_outcome: HeatDeliveryCommandOutcome | None = None
    last_command_timestamp: datetime | None = None
    actuator_failure_active: bool = False
    actuator_failure_kind: HeatDeliveryFailureKind | None = None
    actuator_failure_reason: str | None = None
