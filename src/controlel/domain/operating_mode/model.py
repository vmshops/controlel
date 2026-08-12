"""Immutable operating-mode configuration and evidence."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from controlel.domain.heat_delivery import ObservationQuality
from controlel.domain.value_objects.sensor_id import SensorId


class OperatingMode(StrEnum):
    NORMAL = "normal"
    SAFE_HEATING = "safe_heating"
    EMERGENCY_OFF = "emergency_off"
    MANUAL_RECOVERY_HEAT = "manual_recovery_heat"


@dataclass(frozen=True)
class SafeHeatingProfile:
    """Configured deterministic fallback heating parameters."""

    room_target_temperature: float
    turn_on_differential: float
    turn_off_differential: float
    preferred_sensor_id: SensorId
    fallback_sensor_id: SensorId | None = None
    water_target_temperature: float | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("room_target_temperature", self.room_target_temperature),
            ("turn_on_differential", self.turn_on_differential),
            ("turn_off_differential", self.turn_off_differential),
        ):
            if isinstance(value, bool) or not isinstance(value, int | float) or not isfinite(value):
                raise ValueError(f"{label} must be finite")
        if self.turn_on_differential < 0 or self.turn_off_differential < 0:
            raise ValueError("safe-heating differentials must not be negative")
        if not isinstance(self.preferred_sensor_id, SensorId):
            raise TypeError("preferred_sensor_id must be a SensorId")
        if self.fallback_sensor_id is not None and not isinstance(self.fallback_sensor_id, SensorId):
            raise TypeError("fallback_sensor_id must be a SensorId or None")
        if self.water_target_temperature is not None and (
            isinstance(self.water_target_temperature, bool)
            or not isinstance(self.water_target_temperature, int | float)
            or not isfinite(self.water_target_temperature)
        ):
            raise ValueError("water_target_temperature must be finite or None")


@dataclass(frozen=True)
class SafeHeatingTemperatureEvidence:
    """Reported temperature evidence used only by safe-heating policy."""

    sensor_id: SensorId
    value: float | None
    quality: ObservationQuality
    observed_at: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.sensor_id, SensorId):
            raise TypeError("sensor_id must be a SensorId")
        if not isinstance(self.quality, ObservationQuality):
            raise TypeError("quality must be an ObservationQuality")
        if self.value is not None and (
            isinstance(self.value, bool) or not isinstance(self.value, int | float) or not isfinite(self.value)
        ):
            raise ValueError("value must be finite or None")
        if self.quality is ObservationQuality.VALID and self.value is None:
            raise ValueError("VALID evidence requires a value")
        if self.observed_at is not None and (self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None):
            raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True)
class WaterTargetIntent:
    """Capability-gated request intent; not proof of dispatch or application."""

    target_temperature: float
    requested_at: datetime

    def __post_init__(self) -> None:
        if (
            isinstance(self.target_temperature, bool)
            or not isinstance(self.target_temperature, int | float)
            or not isfinite(self.target_temperature)
        ):
            raise ValueError("target_temperature must be finite")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
