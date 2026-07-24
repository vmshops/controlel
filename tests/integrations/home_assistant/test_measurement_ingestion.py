from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from controlel.domain.value_objects.sensor_id import SensorId
from custom_components.controlel.config import HomeAssistantSensorBinding
from custom_components.controlel.measurement_ingestion import (
    HomeAssistantMeasurementMapper,
    MeasurementRejectionReason,
)

NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


@dataclass
class FakeState:
    entity_id: str = "sensor.room"
    state: str = "20"
    attributes: dict[str, object] | None = None
    last_updated: datetime | None = NOW

    def __post_init__(self):
        if self.attributes is None:
            self.attributes = {"unit_of_measurement": "°C"}


def mapper() -> HomeAssistantMeasurementMapper:
    return HomeAssistantMeasurementMapper(
        HomeAssistantSensorBinding(
            entity_id="sensor.room",
            sensor_id=SensorId("room_temperature"),
        )
    )


def test_maps_celsius_with_exact_identity_and_timestamp():
    result = mapper().map_state(FakeState())

    assert result.rejection_reason is None
    assert result.measurement is not None
    assert result.measurement.sensor_id == SensorId("room_temperature")
    assert result.measurement.value.value == 20
    assert result.measurement.timestamp is NOW


def test_converts_fahrenheit_to_celsius():
    result = mapper().map_state(
        FakeState(
            state="68",
            attributes={"unit_of_measurement": "°F"},
        )
    )

    assert result.measurement is not None
    assert result.measurement.value.value == pytest.approx(20)


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (None, MeasurementRejectionReason.MISSING_STATE),
        (FakeState(entity_id="sensor.other"), MeasurementRejectionReason.WRONG_ENTITY),
        (FakeState(state="unknown"), MeasurementRejectionReason.UNAVAILABLE),
        (FakeState(state="unavailable"), MeasurementRejectionReason.UNAVAILABLE),
        (FakeState(state=""), MeasurementRejectionReason.EMPTY),
        (FakeState(state="abc"), MeasurementRejectionReason.NON_NUMERIC),
        (FakeState(state="nan"), MeasurementRejectionReason.NON_FINITE),
        (FakeState(state="inf"), MeasurementRejectionReason.NON_FINITE),
        (FakeState(state="-inf"), MeasurementRejectionReason.NON_FINITE),
        (FakeState(attributes={}), MeasurementRejectionReason.MISSING_UNIT),
        (
            FakeState(attributes={"unit_of_measurement": "%"}),
            MeasurementRejectionReason.UNSUPPORTED_UNIT,
        ),
        (FakeState(last_updated=None), MeasurementRejectionReason.MISSING_TIMESTAMP),
        (
            FakeState(last_updated=datetime(2026, 7, 23, 10, 0)),
            MeasurementRejectionReason.NAIVE_TIMESTAMP,
        ),
    ],
)
def test_rejects_invalid_adapter_input(state: FakeState | None, reason: MeasurementRejectionReason):
    result = mapper().map_state(state)

    assert result.measurement is None
    assert result.rejection_reason is reason


def test_state_version_uses_all_deduplication_fields():
    configured_mapper = mapper()
    original = FakeState()

    assert configured_mapper.state_version(original) == (
        original.entity_id,
        NOW,
        "20",
        "°C",
    )
    assert configured_mapper.state_version(FakeState(state="21")) != configured_mapper.state_version(original)
    assert configured_mapper.state_version(
        FakeState(attributes={"unit_of_measurement": "°F"})
    ) != configured_mapper.state_version(original)
