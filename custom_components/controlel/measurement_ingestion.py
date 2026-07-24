"""Home Assistant state to Controlel Measurement mapping."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Protocol

from controlel.domain.measurements.measurement import Measurement
from controlel.domain.value_objects.temperature import Temperature

from .config import HomeAssistantSensorBinding
from .const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UNIT_CELSIUS,
    UNIT_FAHRENHEIT,
)


class StateLike(Protocol):
    entity_id: str
    state: str
    attributes: Mapping[str, object]
    last_updated: datetime | None


class MeasurementRejectionReason(StrEnum):
    MISSING_STATE = "missing_state"
    WRONG_ENTITY = "wrong_entity"
    UNAVAILABLE = "unavailable"
    EMPTY = "empty"
    NON_NUMERIC = "non_numeric"
    NON_FINITE = "non_finite"
    MISSING_UNIT = "missing_unit"
    UNSUPPORTED_UNIT = "unsupported_unit"
    MISSING_TIMESTAMP = "missing_timestamp"
    NAIVE_TIMESTAMP = "naive_timestamp"


@dataclass(frozen=True)
class MeasurementMappingResult:
    measurement: Measurement | None
    rejection_reason: MeasurementRejectionReason | None

    def __post_init__(self) -> None:
        if (self.measurement is None) == (self.rejection_reason is None):
            raise ValueError("exactly one of measurement or rejection_reason is required")


StateVersion = tuple[str, datetime | None, str, object]


class HomeAssistantMeasurementMapper:
    def __init__(self, binding: HomeAssistantSensorBinding) -> None:
        self._binding = binding

    def map_state(
        self,
        state: StateLike | None,
    ) -> MeasurementMappingResult:
        if state is None:
            return _rejected(MeasurementRejectionReason.MISSING_STATE)
        if state.entity_id != self._binding.entity_id:
            return _rejected(MeasurementRejectionReason.WRONG_ENTITY)

        raw_value = state.state.strip()
        if not raw_value:
            return _rejected(MeasurementRejectionReason.EMPTY)
        if raw_value.casefold() in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            return _rejected(MeasurementRejectionReason.UNAVAILABLE)

        try:
            numeric_value = float(raw_value)
        except ValueError:
            return _rejected(MeasurementRejectionReason.NON_NUMERIC)
        if not isfinite(numeric_value):
            return _rejected(MeasurementRejectionReason.NON_FINITE)

        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit is None:
            return _rejected(MeasurementRejectionReason.MISSING_UNIT)
        if unit == UNIT_CELSIUS:
            celsius = numeric_value
        elif unit == UNIT_FAHRENHEIT:
            celsius = (numeric_value - 32.0) * 5.0 / 9.0
        else:
            return _rejected(MeasurementRejectionReason.UNSUPPORTED_UNIT)

        timestamp = state.last_updated
        if timestamp is None:
            return _rejected(MeasurementRejectionReason.MISSING_TIMESTAMP)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            return _rejected(MeasurementRejectionReason.NAIVE_TIMESTAMP)

        return MeasurementMappingResult(
            measurement=Measurement(
                sensor_id=self._binding.sensor_id,
                value=Temperature(celsius),
                timestamp=timestamp,
            ),
            rejection_reason=None,
        )

    def state_version(
        self,
        state: StateLike | None,
    ) -> StateVersion | None:
        if state is None:
            return None
        return (
            state.entity_id,
            state.last_updated,
            state.state,
            state.attributes.get(ATTR_UNIT_OF_MEASUREMENT),
        )


def _rejected(reason: MeasurementRejectionReason) -> MeasurementMappingResult:
    return MeasurementMappingResult(
        measurement=None,
        rejection_reason=reason,
    )
