from collections.abc import Mapping
from pathlib import Path

import pytest

from controlel.simulation import (
    HeatingSimulationAdapter,
    ProvenanceEnvelope,
    ReplayArtifact,
    Scenario,
    ScenarioEvent,
    ScenarioRunner,
)

ROOT = Path(__file__).parents[2]
EXAMPLE = ROOT / "docs" / "examples" / "shadow" / "room_temperature_sensor_failure.yaml"


def test_yaml_scenario_has_stable_canonical_json_hash_and_round_trip() -> None:
    scenario = Scenario.from_yaml(EXAMPLE.read_text(encoding="utf-8"))

    replayed = Scenario.from_json(scenario.canonical_json())

    assert replayed == scenario
    assert replayed.content_hash == scenario.content_hash
    assert '"at":"2026-01-15T08:10:00Z"' in scenario.canonical_json()


def test_scenario_rejects_mutable_fixture_reference_in_v01() -> None:
    source = EXAMPLE.read_text(encoding="utf-8").replace(
        "  zone_id: living_room",
        "  fixture: mutable-name\n  zone_id: living_room",
    )

    with pytest.raises(ValueError, match="fixtures are not supported"):
        Scenario.from_yaml(source)


def test_yaml_scenario_rejects_duplicate_keys() -> None:
    source = EXAMPLE.read_text(encoding="utf-8").replace(
        "scenario_id: room_temperature_sensor_failure",
        "scenario_id: first\nscenario_id: second",
    )

    with pytest.raises(ValueError, match="duplicate YAML mapping key"):
        Scenario.from_yaml(source)


def test_validated_scenario_and_event_evidence_are_deeply_immutable() -> None:
    source_values = [1, 2]
    event_source = {"nested": {"values": source_values}}
    event = ScenarioEvent(type="sensor.example", payload=event_source)
    scenario = Scenario.from_yaml(EXAMPLE.read_text(encoding="utf-8"))
    original_hash = scenario.content_hash

    source_values.append(3)
    with pytest.raises(TypeError):
        event.payload["new"] = "value"  # type: ignore[index]
    nested = event.payload["nested"]
    assert isinstance(nested, Mapping)
    with pytest.raises(TypeError):
        nested["changed"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        scenario.configuration["target_temperature"] = 18.0  # type: ignore[index]

    assert event.payload["nested"]["values"] == (1, 2)  # type: ignore[index]
    assert scenario.content_hash == original_hash


def test_report_provenance_and_replay_evidence_are_deeply_immutable() -> None:
    scenario = Scenario.from_yaml(EXAMPLE.read_text(encoding="utf-8"))
    runner = ScenarioRunner(HeatingSimulationAdapter)
    report = runner.run(scenario)
    artifact = ReplayArtifact.from_execution(scenario, report)
    record: ProvenanceEnvelope = report.records[0]

    with pytest.raises(TypeError):
        record.payload["changed"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        artifact.canonical_scenario["name"] = "changed"  # type: ignore[index]

    assert artifact.scenario_hash == scenario.content_hash
