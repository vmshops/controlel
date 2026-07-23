from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from controlel.application.state.heat_demand_safety_state import (
    HeatDemandSafetyState,
)
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def test_state_is_immutable_and_accepts_valid_diagnostic_context():
    state = HeatDemandSafetyState(
        indeterminate_since=NOW,
        last_determinate_status=BuildingHeatDemandStatus.HEAT_REQUIRED,
        last_evaluated_at=NOW + timedelta(seconds=1),
    )

    assert state.indeterminate_since is NOW
    assert state.last_determinate_status is BuildingHeatDemandStatus.HEAT_REQUIRED
    with pytest.raises(ValidationError):
        state.last_evaluated_at = NOW


@pytest.mark.parametrize(
    "fields",
    [
        {"last_evaluated_at": datetime(2026, 1, 1, 12)},
        {
            "indeterminate_since": datetime(2026, 1, 1, 12),
            "last_evaluated_at": NOW,
        },
        {
            "indeterminate_since": NOW + timedelta(microseconds=1),
            "last_evaluated_at": NOW,
        },
        {
            "last_determinate_status": BuildingHeatDemandStatus.INDETERMINATE,
            "last_evaluated_at": NOW,
        },
    ],
)
def test_invalid_state_is_rejected(fields):
    with pytest.raises(ValidationError):
        HeatDemandSafetyState(**fields)
