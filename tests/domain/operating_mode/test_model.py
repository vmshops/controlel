from datetime import UTC, datetime

import pytest

from controlel.domain.heat_delivery import ObservationQuality
from controlel.domain.operating_mode import (
    OperatingMode,
    SafeHeatingProfile,
    SafeHeatingTemperatureEvidence,
)
from controlel.domain.value_objects.sensor_id import SensorId

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_safe_heating_profile_is_immutable_and_configuration_driven() -> None:
    profile = SafeHeatingProfile(
        room_target_temperature=19.0,
        turn_on_differential=1.0,
        turn_off_differential=1.5,
        preferred_sensor_id=SensorId("living_room"),
        fallback_sensor_id=SensorId("hall"),
        water_target_temperature=45.0,
    )

    assert profile.water_target_temperature == 45.0
    assert OperatingMode.SAFE_HEATING.value == "safe_heating"
    with pytest.raises(AttributeError):
        profile.room_target_temperature = 20.0  # type: ignore[misc]


def test_unknown_safe_heating_evidence_does_not_invent_temperature() -> None:
    evidence = SafeHeatingTemperatureEvidence(
        sensor_id=SensorId("living_room"),
        value=None,
        quality=ObservationQuality.UNKNOWN,
        observed_at=NOW,
    )

    assert evidence.value is None
    assert evidence.quality is ObservationQuality.UNKNOWN


def test_valid_safe_heating_evidence_requires_a_value() -> None:
    with pytest.raises(ValueError, match="VALID evidence requires a value"):
        SafeHeatingTemperatureEvidence(
            sensor_id=SensorId("living_room"),
            value=None,
            quality=ObservationQuality.VALID,
            observed_at=NOW,
        )
