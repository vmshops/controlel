"""Explicit virtual evidence providers; no state is inferred from commands."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from controlel.application.sensors.sensor_provider import SensorProvider
from controlel.domain.measurements.measurement import Measurement
from controlel.domain.sensors.sensor import Sensor
from controlel.domain.source_control import ReportedSourceEvidence, ReportedSourceState
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature


class VirtualSensorAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class VirtualEvidenceUnavailable(RuntimeError):
    """Raised when a scenario asks an unavailable provider for evidence."""


class VirtualTemperatureSensor(SensorProvider):
    """Store only explicitly supplied temperature and availability evidence."""

    def __init__(self, sensor_id: SensorId) -> None:
        self.sensor_id = sensor_id
        self._availability = VirtualSensorAvailability.UNAVAILABLE
        self._value: float | None = None
        self._observed_at: datetime | None = None

    @property
    def availability(self) -> VirtualSensorAvailability:
        return self._availability

    @property
    def observed_at(self) -> datetime | None:
        return self._observed_at

    def observe(self, value: float, *, observed_at: datetime) -> Measurement:
        _aware(observed_at, "observed_at")
        measurement = Measurement(
            sensor_id=self.sensor_id,
            value=Temperature(value=value),
            timestamp=observed_at,
        )
        self._availability = VirtualSensorAvailability.AVAILABLE
        self._value = float(value)
        self._observed_at = observed_at
        return measurement

    def mark_unavailable(self, *, observed_at: datetime) -> None:
        _aware(observed_at, "observed_at")
        self._availability = VirtualSensorAvailability.UNAVAILABLE
        self._observed_at = observed_at

    def measure(self, sensor: Sensor) -> Measurement:
        if sensor.sensor_id != self.sensor_id:
            raise ValueError("sensor identity does not match virtual provider")
        if (
            self._availability is VirtualSensorAvailability.UNAVAILABLE
            or self._value is None
            or self._observed_at is None
        ):
            raise VirtualEvidenceUnavailable(f"sensor '{self.sensor_id.value}' is unavailable")
        return Measurement(
            sensor_id=self.sensor_id,
            value=Temperature(value=self._value),
            timestamp=self._observed_at,
        )


class VirtualSourceStateProvider:
    """Retain explicit controller-reported state, never physical burner state."""

    def __init__(self) -> None:
        self._evidence: ReportedSourceEvidence | None = None

    @property
    def evidence(self) -> ReportedSourceEvidence | None:
        return self._evidence

    def observe(
        self,
        state: ReportedSourceState,
        *,
        observed_at: datetime,
        transition_at: datetime | None = None,
    ) -> ReportedSourceEvidence:
        evidence = ReportedSourceEvidence(
            state=state,
            observed_at=observed_at,
            transition_at=transition_at,
        )
        self._evidence = evidence
        return evidence


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value
