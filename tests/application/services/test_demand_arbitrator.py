from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from controlel.application.services.demand_arbitrator import (
    IdentityDemandArbitrator,
    MultiZoneDemandArbitrator,
)
from controlel.domain.demands.building_heat_demand import (
    BuildingHeatDemand,
    BuildingHeatDemandReason,
)
from controlel.domain.demands.building_heat_demand_status import (
    BuildingHeatDemandStatus,
)
from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.demands.zone_heat_demand_input import (
    ZoneHeatDemandInput,
    ZoneHeatDemandInputReason,
)
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.zone_id import ZoneId

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


def zone_input(
    zone_id: str,
    demand: BuildingHeatDemandStatus,
    *,
    preserves_confirmed_heat: bool = False,
) -> ZoneHeatDemandInput:
    identifier = ZoneId(value=zone_id)
    evidence = None
    reason = ZoneHeatDemandInputReason.MISSING
    if demand is not BuildingHeatDemandStatus.INDETERMINATE:
        evidence = ZoneDemand(
            zone_id=identifier,
            requires_heat=demand is BuildingHeatDemandStatus.HEAT_REQUIRED,
            source_sensor_id=SensorId(value=f"{zone_id}_temperature"),
            observed_at=NOW,
        )
        reason = ZoneHeatDemandInputReason.ELIGIBLE
    return ZoneHeatDemandInput(
        zone_id=identifier,
        demand=demand,
        reason=reason,
        evidence=evidence,
        preserves_confirmed_heat=preserves_confirmed_heat,
    )


def arbitrate(*inputs: ZoneHeatDemandInput) -> BuildingHeatDemand:
    source = aggregate_demand().model_copy(
        update={
            "zone_inputs": tuple(sorted(inputs, key=lambda item: item.zone_id.value)),
            "zone_count": len(inputs),
        }
    )
    return MultiZoneDemandArbitrator().resolve(source)


def test_one_zone_arbitrator_is_an_explicit_identity_mapping() -> None:
    demand = aggregate_demand()

    assert IdentityDemandArbitrator().resolve(demand) is demand


def test_identity_arbitrator_accepts_only_aggregate_building_demand() -> None:
    with pytest.raises(TypeError, match="BuildingHeatDemand"):
        IdentityDemandArbitrator().resolve(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("inputs", "status", "reason", "heat_ids", "no_heat_ids", "indeterminate_ids"),
    [
        ((), BuildingHeatDemandStatus.INDETERMINATE, BuildingHeatDemandReason.NO_ZONES_CONFIGURED, (), (), ()),
        (
            (zone_input("a", BuildingHeatDemandStatus.NO_HEAT_REQUIRED),),
            BuildingHeatDemandStatus.NO_HEAT_REQUIRED,
            BuildingHeatDemandReason.NO_ZONE_REQUIRES_HEAT,
            (),
            ("a",),
            (),
        ),
        (
            (zone_input("a", BuildingHeatDemandStatus.HEAT_REQUIRED),),
            BuildingHeatDemandStatus.HEAT_REQUIRED,
            BuildingHeatDemandReason.HEAT_REQUIRED_BY_ZONE,
            ("a",),
            (),
            (),
        ),
        (
            (
                zone_input("heat", BuildingHeatDemandStatus.HEAT_REQUIRED),
                zone_input("unknown", BuildingHeatDemandStatus.INDETERMINATE),
            ),
            BuildingHeatDemandStatus.HEAT_REQUIRED,
            BuildingHeatDemandReason.HEAT_REQUIRED_BY_ZONE,
            ("heat",),
            (),
            ("unknown",),
        ),
        (
            (
                zone_input("off", BuildingHeatDemandStatus.NO_HEAT_REQUIRED),
                zone_input("unknown", BuildingHeatDemandStatus.INDETERMINATE),
            ),
            BuildingHeatDemandStatus.NO_HEAT_REQUIRED,
            BuildingHeatDemandReason.NO_ZONE_REQUIRES_HEAT,
            (),
            ("off",),
            ("unknown",),
        ),
        (
            (
                zone_input("b", BuildingHeatDemandStatus.INDETERMINATE),
                zone_input("a", BuildingHeatDemandStatus.INDETERMINATE),
            ),
            BuildingHeatDemandStatus.INDETERMINATE,
            BuildingHeatDemandReason.ALL_ZONES_INDETERMINATE,
            (),
            (),
            ("a", "b"),
        ),
    ],
)
def test_multi_zone_truth_table_and_deterministic_diagnostics(
    inputs,
    status,
    reason,
    heat_ids,
    no_heat_ids,
    indeterminate_ids,
) -> None:
    result = arbitrate(*inputs)

    assert result.status is status
    assert result.reason is reason
    assert tuple(item.value for item in result.contributing_heat_zone_ids) == heat_ids
    assert tuple(item.value for item in result.no_heat_zone_ids) == no_heat_ids
    assert tuple(item.value for item in result.indeterminate_zone_ids) == indeterminate_ids
    assert result.zone_count == len(inputs)
    assert result.heat_requesting_zone_count == len(heat_ids)


def test_multiple_heat_zones_have_stable_order_and_multiple_reason() -> None:
    result = arbitrate(
        zone_input("zulu", BuildingHeatDemandStatus.HEAT_REQUIRED),
        zone_input("alpha", BuildingHeatDemandStatus.HEAT_REQUIRED),
        zone_input("middle", BuildingHeatDemandStatus.NO_HEAT_REQUIRED),
    )

    assert tuple(zone_id.value for zone_id in result.contributing_heat_zone_ids) == ("alpha", "zulu")
    assert result.reason is BuildingHeatDemandReason.HEAT_REQUIRED_BY_MULTIPLE_ZONES


def test_previously_confirmed_active_indeterminate_defers_to_existing_safety_layer() -> None:
    result = arbitrate(
        zone_input("off", BuildingHeatDemandStatus.NO_HEAT_REQUIRED),
        zone_input(
            "uncertain_active",
            BuildingHeatDemandStatus.INDETERMINATE,
            preserves_confirmed_heat=True,
        ),
    )

    assert result.status is BuildingHeatDemandStatus.INDETERMINATE
    assert result.reason is BuildingHeatDemandReason.INDETERMINATE_ACTIVE_DEMAND_PRESERVED


def test_single_zone_projection_matches_frozen_identity_result_and_is_idempotent() -> None:
    result = arbitrate(zone_input("only", BuildingHeatDemandStatus.HEAT_REQUIRED))
    repeated = MultiZoneDemandArbitrator().resolve(result)

    assert IdentityDemandArbitrator().resolve(result) == result
    assert repeated == result
    assert result.model_dump(mode="json") == {
        "status": "heat_required",
        "evaluated_at": "2026-08-02T12:00:00Z",
        "eligible_demands": [
            {
                "zone_id": {"value": "only"},
                "requires_heat": True,
                "source_sensor_id": {"value": "only_temperature"},
                "observed_at": "2026-08-02T12:00:00Z",
            }
        ],
        "missing_zone_ids": [],
        "expired_zone_ids": [],
        "future_dated_zone_ids": [],
        "zone_inputs": [
            {
                "zone_id": {"value": "only"},
                "demand": "heat_required",
                "reason": "eligible",
                "evidence": {
                    "zone_id": {"value": "only"},
                    "requires_heat": True,
                    "source_sensor_id": {"value": "only_temperature"},
                    "observed_at": "2026-08-02T12:00:00Z",
                },
                "preserves_confirmed_heat": False,
            }
        ],
        "contributing_heat_zone_ids": [{"value": "only"}],
        "no_heat_zone_ids": [],
        "indeterminate_zone_ids": [],
        "reason": "heat_required_by_zone",
        "zone_count": 1,
        "heat_requesting_zone_count": 1,
    }


def test_zone_input_is_immutable() -> None:
    value = zone_input("only", BuildingHeatDemandStatus.NO_HEAT_REQUIRED)
    with pytest.raises(ValidationError):
        value.demand = BuildingHeatDemandStatus.HEAT_REQUIRED
