from datetime import UTC, datetime, timedelta

from controlel.application.state.heat_demand_safety_state import (
    HeatDemandSafetyState,
)
from controlel.application.state.heat_demand_safety_state_store import (
    HeatDemandSafetyStateStore,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def test_empty_lookup_and_exact_replacement():
    store = HeatDemandSafetyStateStore()
    first = HeatDemandSafetyState(last_evaluated_at=NOW)
    replacement = HeatDemandSafetyState(last_evaluated_at=NOW + timedelta(seconds=1))

    assert store.get() is None
    store.save(first)
    assert store.get() is first
    store.save(replacement)
    assert store.get() is replacement
