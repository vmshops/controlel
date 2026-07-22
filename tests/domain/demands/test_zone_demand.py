from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def create_demand() -> ZoneDemand:
    return ZoneDemand(
        zone_id=ZoneId(value="living_room"),
        requires_heat=True,
        source_sensor_id=SensorId(value="living_room_temperature"),
        observed_at=NOW,
    )


def test_zone_demand_preserves_typed_provenance():
    demand = create_demand()

    assert demand.zone_id == ZoneId(value="living_room")
    assert demand.requires_heat is True
    assert demand.source_sensor_id == SensorId(value="living_room_temperature")
    assert demand.observed_at is NOW


def test_zone_demand_is_immutable():
    demand = create_demand()

    with pytest.raises(ValidationError, match="frozen"):
        demand.requires_heat = False


def test_zone_demand_rejects_naive_observed_at():
    with pytest.raises(ValidationError, match="observed_at must be timezone-aware"):
        ZoneDemand(
            zone_id=ZoneId(value="living_room"),
            requires_heat=True,
            source_sensor_id=SensorId(value="living_room_temperature"),
            observed_at=datetime(2026, 1, 1, 12),
        )
