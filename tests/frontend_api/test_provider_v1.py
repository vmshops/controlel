"""Contract tests for the passive Frontend API v1 provider."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from controlel.frontend_api.v1 import (
    AttentionEvidenceV1,
    BuildingEvidenceV1,
    DecisionEvidenceItemV1,
    DecisionEvidenceV1,
    EventStreamEvidenceV1,
    FrontendApiEvidenceV1,
    FrontendApiProviderV1,
    HeatSourceEvidenceV1,
    MissingConfigurationEvidenceV1,
    ModuleEvidenceV1,
    OperationalEventEvidenceV1,
    ScopeV1,
    SetupEvidenceV1,
    SystemEvidenceV1,
    ValidationMessageEvidenceV1,
    ZoneEvidenceV1,
    frontend_response_to_dict,
)

NOW = datetime(2026, 8, 22, 14, 3, 11, tzinfo=UTC)


@dataclass
class FakeSource:
    value: FrontendApiEvidenceV1

    def snapshot(self) -> FrontendApiEvidenceV1:
        return self.value


class FakeClock:
    def now(self) -> datetime:
        return NOW


def _decision() -> DecisionEvidenceV1:
    return DecisionEvidenceV1(
        decision_id="decision:31",
        zone_id="zone:living-room",
        sensor_id="sensor:living-room-temperature",
        action="enable_heating",
        observed_at=NOW - timedelta(seconds=13),
        reason_code="below_enable_threshold",
        evidence=(
            DecisionEvidenceItemV1("measurement", 21.4),
            DecisionEvidenceItemV1("target", 22.0),
        ),
    )


def _normal_evidence() -> FrontendApiEvidenceV1:
    decision = _decision()
    event = OperationalEventEvidenceV1(
        event_id="event:148",
        timestamp=NOW - timedelta(seconds=12),
        category="source_control",
        severity="info",
        event_code="source_command_dispatched",
        summary_code="source_permission_enabled",
        reason_code=None,
        scope=ScopeV1(type="source", source_id="source:shared"),
        previous_state="DISABLED",
        new_state="ENABLED",
        requested_command="enable",
        command_outcome="dispatched",
    )
    return FrontendApiEvidenceV1(
        system=SystemEvidenceV1(
            status="active",
            operating_mode="NORMAL",
            operating_mode_since=NOW - timedelta(hours=8),
        ),
        modules=(ModuleEvidenceV1(module_id="heating", status="active"),),
        attention=(
            AttentionEvidenceV1(
                attention_id="attention:1",
                severity="warning",
                code="source_report_drift",
                scope=ScopeV1(type="source", source_id="source:shared"),
                summary="Heat source report differs from requested permission",
                first_seen_at=NOW - timedelta(minutes=5),
            ),
        ),
        building=BuildingEvidenceV1(
            demand_status="heat_required",
            demand_reason_code="zone_demand_confirmed",
            heat_source=HeatSourceEvidenceV1(
                permission="enabled",
                requested_command="enable",
                command_outcome="dispatched",
                reported_state="ENABLED",
                last_decision=decision,
            ),
        ),
        zones=(
            ZoneEvidenceV1(
                zone_id="zone:living-room",
                name="Living room",
                target_temperature_c=22.0,
                measurement_temperature_c=21.4,
                measurement_observed_at=NOW - timedelta(seconds=42),
                measurement_max_age=timedelta(minutes=5),
                demand_requires_heat=True,
                demand_observed_at=NOW - timedelta(seconds=42),
                demand_reason_code="below_enable_threshold",
                last_decision=decision,
            ),
        ),
        event_stream=EventStreamEvidenceV1(events=(event,), total_emitted=148, dropped=147),
        latest_decision=decision,
        retained_decision_count=20,
        total_decisions=31,
        setup=SetupEvidenceV1(state="ready"),
    )


def _provider(evidence: FrontendApiEvidenceV1) -> FrontendApiProviderV1:
    return FrontendApiProviderV1(source=FakeSource(evidence), clock=FakeClock())


def test_normal_dto_generation_is_versioned_bounded_and_json_safe() -> None:
    provider = _provider(_normal_evidence())

    overview = frontend_response_to_dict(provider.overview())
    heating = frontend_response_to_dict(provider.heating())
    diagnostics = frontend_response_to_dict(provider.diagnostics())
    setup = frontend_response_to_dict(provider.setup())

    assert overview["frontend_api_version"] == 1
    assert overview["generated_at"] == NOW.isoformat()
    assert overview["modules"] == [{"module_id": "heating", "status": "active", "reason": None}]
    assert heating["zones"][0]["measurement_state"] == "fresh"
    assert heating["zones"][0]["measurement_age_seconds"] == 42.0
    assert heating["zones"][0]["demand_state"] == "heat_required"
    assert heating["building"]["heat_source"] == {
        "permission": "enabled",
        "requested_command": "enable",
        "command_outcome": "dispatched",
        "reported_state": "ENABLED",
        "physical_state": "unknown",
        "last_decision_summary": {
            "decision_id": "decision:31",
            "action": "enable_heating",
            "observed_at": (NOW - timedelta(seconds=13)).isoformat(),
            "reason_code": "below_enable_threshold",
        },
    }
    assert diagnostics["recent_events"][0]["command"] == {"action": "enable", "outcome": "dispatched"}
    assert diagnostics["decision_trace"]["evidence"][0] == {"code": "measurement", "value": 21.4}
    assert setup["readiness"] == {"state": "ready", "reason_code": None}
    for payload in (overview, heating, diagnostics, setup):
        assert json.loads(json.dumps(payload)) == payload


def test_incomplete_setup_preserves_missing_and_validation_codes() -> None:
    evidence = FrontendApiEvidenceV1(
        system=SystemEvidenceV1(status="stopped", operating_mode="NORMAL"),
        setup=SetupEvidenceV1(
            state="incomplete",
            reason_code="zone_primary_sensor_missing",
            missing_configuration=(
                MissingConfigurationEvidenceV1(
                    code="zone_primary_sensor_missing",
                    scope=ScopeV1(type="zone", zone_id="zone:bathroom"),
                    severity="error",
                ),
            ),
            validation_messages=(
                ValidationMessageEvidenceV1(
                    code="sensor_max_age_too_large",
                    severity="warning",
                    scope=ScopeV1(type="sensor", sensor_id="sensor:bathroom-temperature"),
                    summary="Primary measurement max age exceeds recommended bound",
                ),
            ),
        ),
    )

    payload = frontend_response_to_dict(_provider(evidence).setup())

    assert payload["readiness"]["state"] == "incomplete"
    assert payload["missing_configuration"][0]["scope"]["zone_id"] == "zone:bathroom"
    assert payload["validation_messages"][0]["code"] == "sensor_max_age_too_large"


def test_unavailable_stale_and_future_measurements_do_not_create_demand() -> None:
    evidence = FrontendApiEvidenceV1(
        system=SystemEvidenceV1(status="degraded", operating_mode="NORMAL"),
        zones=(
            ZoneEvidenceV1(zone_id="zone:unavailable", name="Unavailable", target_temperature_c=20.0),
            ZoneEvidenceV1(
                zone_id="zone:stale",
                name="Stale",
                target_temperature_c=20.0,
                measurement_temperature_c=18.0,
                measurement_observed_at=NOW - timedelta(minutes=10),
                measurement_max_age=timedelta(minutes=5),
                demand_requires_heat=False,
                demand_observed_at=NOW - timedelta(minutes=10),
            ),
            ZoneEvidenceV1(
                zone_id="zone:future",
                name="Future",
                target_temperature_c=20.0,
                measurement_temperature_c=18.0,
                measurement_observed_at=NOW + timedelta(seconds=1),
                measurement_max_age=timedelta(minutes=5),
                demand_requires_heat=True,
                demand_observed_at=NOW + timedelta(seconds=1),
            ),
        ),
    )

    zones = {item["zone_id"]: item for item in frontend_response_to_dict(_provider(evidence).heating())["zones"]}

    assert zones["zone:unavailable"]["measurement_state"] == "missing"
    assert zones["zone:unavailable"]["current_temperature_c"] is None
    assert zones["zone:stale"]["measurement_state"] == "expired"
    assert zones["zone:stale"]["demand_state"] == "indeterminate"
    assert zones["zone:future"]["measurement_state"] == "future_dated"
    assert zones["zone:future"]["demand_state"] == "indeterminate"


def test_unknown_values_remain_unknown_and_dispatch_is_not_physical_confirmation() -> None:
    evidence = FrontendApiEvidenceV1(
        system=SystemEvidenceV1(status="active", operating_mode="NORMAL"),
        building=BuildingEvidenceV1(
            heat_source=HeatSourceEvidenceV1(
                permission="unknown",
                requested_command="enable",
                command_outcome="dispatched",
                reported_state="UNAVAILABLE",
            )
        ),
    )

    source = frontend_response_to_dict(_provider(evidence).heating())["building"]["heat_source"]

    assert source["permission"] == "unknown"
    assert source["reported_state"] == "UNAVAILABLE"
    assert source["physical_state"] == "unknown"
    assert source["command_outcome"] == "dispatched"


def test_deferred_and_held_outcomes_remain_distinct_from_state_evidence() -> None:
    events = tuple(
        OperationalEventEvidenceV1(
            event_id=f"event:{index}",
            timestamp=NOW + timedelta(seconds=index),
            category="source_control",
            severity="info",
            event_code=f"source_command_{outcome}",
            summary_code=f"source_command_{outcome}",
            reason_code=None,
            scope=ScopeV1(type="source", source_id="source:shared"),
            requested_command="enable",
            command_outcome=outcome,
        )
        for index, outcome in enumerate(("deferred", "held"), start=1)
    )

    for outcome in ("deferred", "held"):
        evidence = FrontendApiEvidenceV1(
            system=SystemEvidenceV1(status="active", operating_mode="NORMAL"),
            building=BuildingEvidenceV1(
                heat_source=HeatSourceEvidenceV1(
                    permission="disabled",
                    requested_command="enable",
                    command_outcome=outcome,
                    reported_state="UNKNOWN",
                )
            ),
            event_stream=EventStreamEvidenceV1(events=events, total_emitted=2),
        )
        provider = _provider(evidence)
        source = frontend_response_to_dict(provider.heating())["building"]["heat_source"]
        recent_events = frontend_response_to_dict(provider.diagnostics())["recent_events"]
        event_outcomes = {item["command"]["outcome"] for item in recent_events}

        assert source == {
            "permission": "disabled",
            "requested_command": "enable",
            "command_outcome": outcome,
            "reported_state": "UNKNOWN",
            "physical_state": "unknown",
            "last_decision_summary": None,
        }
        assert event_outcomes == {"deferred", "held"}


def test_stable_ids_are_ordered_and_raw_entity_locator_cannot_leak_as_identity() -> None:
    evidence = _normal_evidence()
    provider = _provider(
        FrontendApiEvidenceV1(
            system=evidence.system,
            modules=(
                ModuleEvidenceV1(module_id="ventilation", status="inactive"),
                ModuleEvidenceV1(module_id="heating", status="active"),
            ),
            zones=(
                ZoneEvidenceV1(zone_id="zone:upstairs", name="Upstairs", target_temperature_c=19.0),
                evidence.zones[0],
            ),
            latest_decision=evidence.latest_decision,
            retained_decision_count=1,
            total_decisions=1,
        )
    )

    overview = frontend_response_to_dict(provider.overview())
    heating = frontend_response_to_dict(provider.heating())
    diagnostics = frontend_response_to_dict(provider.diagnostics())
    serialized = json.dumps((overview, heating, diagnostics))

    assert [item["module_id"] for item in overview["modules"]] == ["heating", "ventilation"]
    assert [item["zone_id"] for item in heating["zones"]] == ["zone:living-room", "zone:upstairs"]
    assert diagnostics["decision_trace"]["sensor_id"] == "sensor:living-room-temperature"
    assert "entity_id" not in serialized
    assert "sensor.living_room_temperature" not in serialized
