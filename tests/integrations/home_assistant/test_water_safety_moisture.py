"""HA adapter tests for Water Safety moisture mapping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from controlel.application.setup import IdentityQuality, ProviderReference
from controlel.domain.water_safety import MoistureCondition
from custom_components.controlel.water_safety_moisture import (
    HomeAssistantMoistureMapper,
    MoistureMappingRejectionReason,
)

NOW = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)


@dataclass
class FakeState:
    entity_id: str = "binary_sensor.bathroom_moisture"
    state: str = "off"
    attributes: dict[str, object] | None = None
    last_updated: datetime | None = NOW


def _binding() -> ProviderReference:
    return ProviderReference(
        provider="home_assistant",
        provider_instance_id="home",
        object_kind="home_assistant.entity",
        native_id="entity-moisture",
        identity_quality=IdentityQuality.STABLE,
        current_locator="binary_sensor.bathroom_moisture",
    )


def _mapper() -> HomeAssistantMoistureMapper:
    return HomeAssistantMoistureMapper("utility-moisture", _binding())


@pytest.mark.parametrize(
    ("state_value", "expected"),
    [
        ("off", MoistureCondition.DRY),
        ("dry", MoistureCondition.DRY),
        ("false", MoistureCondition.DRY),
        ("on", MoistureCondition.WET),
        ("wet", MoistureCondition.WET),
        ("true", MoistureCondition.WET),
        ("unavailable", MoistureCondition.UNAVAILABLE),
        ("unknown", MoistureCondition.UNKNOWN),
        ("", MoistureCondition.UNKNOWN),
    ],
)
def test_moisture_mapper_never_treats_unknown_or_unavailable_as_dry(
    state_value: str,
    expected: MoistureCondition,
) -> None:
    result = _mapper().map_state(FakeState(state=state_value))

    assert result.rejection_reason is None
    assert result.observation is not None
    assert result.observation.condition is expected


def test_moisture_mapper_rejects_wrong_entity() -> None:
    result = _mapper().map_state(FakeState(entity_id="binary_sensor.other"))

    assert result.observation is None
    assert result.rejection_reason is MoistureMappingRejectionReason.WRONG_ENTITY
