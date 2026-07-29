from datetime import UTC, datetime

import pytest

from controlel.application.services.demand_arbitrator import (
    IdentityDemandArbitrator,
)
from controlel.domain.demands.building_heat_demand import BuildingHeatDemand
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def aggregate_demand() -> BuildingHeatDemand:
    return BuildingHeatDemand(
        status=BuildingHeatDemandStatus.HEAT_REQUIRED,
        evaluated_at=NOW,
        eligible_demands=(),
        missing_zone_ids=(),
        expired_zone_ids=(),
        future_dated_zone_ids=(),
    )


def test_one_zone_arbitrator_is_an_explicit_identity_mapping() -> None:
    demand = aggregate_demand()

    assert IdentityDemandArbitrator().resolve(demand) is demand


def test_identity_arbitrator_accepts_only_aggregate_building_demand() -> None:
    with pytest.raises(TypeError, match="BuildingHeatDemand"):
        IdentityDemandArbitrator().resolve(object())  # type: ignore[arg-type]
