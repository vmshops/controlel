from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from controlel.domain.demands.building_heat_demand import BuildingHeatDemand
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def create_demand(**fields) -> BuildingHeatDemand:
    values = {
        "status": BuildingHeatDemandStatus.INDETERMINATE,
        "evaluated_at": NOW,
        "eligible_demands": (),
        "missing_zone_ids": (),
        "expired_zone_ids": (),
        "future_dated_zone_ids": (),
    }
    values.update(fields)
    return BuildingHeatDemand(**values)


def test_building_heat_demand_status_has_stable_values():
    assert [status.value for status in BuildingHeatDemandStatus] == [
        "heat_required",
        "no_heat_required",
        "indeterminate",
    ]
    assert all(isinstance(status, str) for status in BuildingHeatDemandStatus)


def test_building_heat_demand_is_immutable_and_uses_tuples():
    demand = create_demand(missing_zone_ids=[ZoneId(value="living_room")])

    assert demand.missing_zone_ids == (ZoneId(value="living_room"),)
    assert isinstance(demand.eligible_demands, tuple)
    with pytest.raises(ValidationError, match="frozen"):
        demand.status = BuildingHeatDemandStatus.HEAT_REQUIRED


def test_building_heat_demand_rejects_naive_evaluated_at():
    with pytest.raises(ValidationError, match="evaluated_at must be timezone-aware"):
        create_demand(evaluated_at=datetime(2026, 1, 1, 12))


def test_uncertainty_categories_must_be_disjoint():
    zone_id = ZoneId(value="living_room")

    with pytest.raises(ValidationError, match="multiple uncertainty categories"):
        create_demand(
            missing_zone_ids=(zone_id,),
            expired_zone_ids=(zone_id,),
        )
