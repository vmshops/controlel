"""Home Assistant state to Controlel moisture observation mapping."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from controlel.application.setup import ProviderReference
from controlel.domain.water_safety import MoistureCondition, MoistureObservation

from .const import STATE_UNAVAILABLE, STATE_UNKNOWN


class StateLike(Protocol):
    entity_id: str
    state: str
    attributes: Mapping[str, object]
    last_updated: datetime | None


class MoistureMappingRejectionReason(StrEnum):
    MISSING_STATE = "missing_state"
    WRONG_ENTITY = "wrong_entity"
    MISSING_TIMESTAMP = "missing_timestamp"
    NAIVE_TIMESTAMP = "naive_timestamp"
    MISSING_LOCATOR = "missing_locator"


@dataclass(frozen=True)
class MoistureMappingResult:
    observation: MoistureObservation | None
    rejection_reason: MoistureMappingRejectionReason | None

    def __post_init__(self) -> None:
        if (self.observation is None) == (self.rejection_reason is None):
            raise ValueError("exactly one of observation or rejection_reason is required")


class HomeAssistantMoistureMapper:
    """Map one configured moisture entity state without inferring unavailable as dry."""

    def __init__(self, sensor_id: str, binding: ProviderReference) -> None:
        if not sensor_id:
            raise ValueError("sensor_id must not be empty")
        self._sensor_id = sensor_id
        self._entity_id = binding.current_locator
        if not self._entity_id:
            raise ValueError("moisture binding requires current_locator")

    @property
    def entity_id(self) -> str:
        return self._entity_id

    def map_state(self, state: StateLike | None) -> MoistureMappingResult:
        if state is None:
            return _rejected(MoistureMappingRejectionReason.MISSING_STATE)
        if state.entity_id != self._entity_id:
            return _rejected(MoistureMappingRejectionReason.WRONG_ENTITY)

        timestamp = state.last_updated
        if timestamp is None:
            return _rejected(MoistureMappingRejectionReason.MISSING_TIMESTAMP)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            return _rejected(MoistureMappingRejectionReason.NAIVE_TIMESTAMP)

        raw_value = state.state.strip()
        condition = _map_condition(raw_value)
        return MoistureMappingResult(
            observation=MoistureObservation(
                sensor_id=self._sensor_id,
                condition=condition,
                observed_at=timestamp,
                provider_state=raw_value or None,
            ),
            rejection_reason=None,
        )


def _map_condition(raw_value: str) -> MoistureCondition:
    normalized = raw_value.casefold()
    if normalized == STATE_UNAVAILABLE:
        return MoistureCondition.UNAVAILABLE
    if normalized == STATE_UNKNOWN or not normalized:
        return MoistureCondition.UNKNOWN
    if normalized in {"wet", "on", "true", "1"}:
        return MoistureCondition.WET
    if normalized in {"dry", "off", "false", "0"}:
        return MoistureCondition.DRY
    return MoistureCondition.UNKNOWN


def _rejected(reason: MoistureMappingRejectionReason) -> MoistureMappingResult:
    return MoistureMappingResult(observation=None, rejection_reason=reason)
