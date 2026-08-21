from datetime import timedelta

from controlel.simulation import (
    HEATING_SOAK_MAX_TIMELINE_EVENTS,
    HeatingSimulationAdapter,
    HeatingSoakConfiguration,
    HeatingSoakOutcome,
    HeatingSoakRunner,
    RuntimeOrigin,
    ScenarioRunner,
    SimulationMode,
    SimulationOutcome,
)


def _configuration(seed: int, *, hours: int = 6, restarts: int = 3) -> HeatingSoakConfiguration:
    return HeatingSoakConfiguration(
        seed=seed,
        virtual_duration=timedelta(hours=hours),
        restart_count=restarts,
    )


def test_same_seed_repeats_the_normalized_scenario_and_semantic_result() -> None:
    runner = HeatingSoakRunner()
    configuration = _configuration(20260821)

    first = runner.run(configuration)
    second = runner.run(configuration)

    assert first.scenario.canonical_json() == second.scenario.canonical_json()
    assert first.scenario.content_hash == second.scenario.content_hash
    assert first.simulation_report.semantic_fingerprint == second.simulation_report.semantic_fingerprint
    assert first.report == second.report


def test_different_seed_changes_the_generated_sequence() -> None:
    first = HeatingSoakRunner().run(_configuration(101))
    second = HeatingSoakRunner().run(_configuration(102))

    assert first.scenario.canonical_data()["timeline"] != second.scenario.canonical_data()["timeline"]
    assert first.scenario.content_hash != second.scenario.content_hash


def test_long_bounded_soak_completes_without_livelock() -> None:
    result = HeatingSoakRunner().run(HeatingSoakConfiguration(seed=314159))

    assert result.report.outcome is HeatingSoakOutcome.PASS
    assert result.report.failed_invariants == ()
    assert result.report.event_count <= HEATING_SOAK_MAX_TIMELINE_EVENTS
    assert result.report.restart_count == 4
    assert result.report.command_count == 25
    assert result.report.virtual_duration_seconds == timedelta(hours=24).total_seconds()
    assert result.simulation_report.outcome is SimulationOutcome.PASSED
    assert not any("livelock" in error for error in result.simulation_report.errors)


def test_cold_restarts_remain_deterministic_and_preserve_recovery_holds() -> None:
    configuration = _configuration(81723, hours=4, restarts=2)

    first = HeatingSoakRunner().run(configuration)
    second = HeatingSoakRunner().run(configuration)

    first_semantics = tuple(record.semantic_data() for record in first.simulation_report.records)
    second_semantics = tuple(record.semantic_data() for record in second.simulation_report.records)
    held_events = tuple(
        record
        for record in first.simulation_report.records
        if record.kind == "operational_event" and record.payload.get("event_code") == "corrective_action_held"
    )

    assert first.report.restart_count == second.report.restart_count == 2
    assert first_semantics == second_semantics
    assert len(held_events) >= first.report.restart_count + 1
    assert not any(failure.startswith("recovery_hold_missing") for failure in first.report.failed_invariants)


def test_generated_failure_retains_replayable_evidence_and_reason() -> None:
    configuration = HeatingSoakConfiguration(
        seed=314159,
        virtual_duration=timedelta(hours=4),
        restart_count=2,
        inject_reproducible_source_failure=True,
    )
    result = HeatingSoakRunner().run(configuration)

    replayed = ScenarioRunner(HeatingSimulationAdapter).replay(
        result.replay_artifact,
        run_id="replayed-soak-failure",
    )

    assert result.report.outcome is HeatingSoakOutcome.FAIL
    assert result.report.failed_invariants == ("simulation_outcome_error",)
    assert result.simulation_report.errors == ("SimulatedDispatchError: soak_injected_source_dispatch_failure",)
    assert result.configuration.seed == 314159
    assert result.replay_artifact.canonical_scenario == result.scenario.canonical_data()
    assert result.report.semantic_fingerprint == result.replay_artifact.expected_semantic_fingerprint
    assert replayed.outcome is SimulationOutcome.ERROR
    assert replayed.semantic_fingerprint == result.report.semantic_fingerprint


def test_soak_outputs_remain_isolated_and_commands_do_not_create_source_evidence() -> None:
    result = HeatingSoakRunner().run(_configuration(777, hours=3, restarts=2))
    records = result.simulation_report.records
    commands = tuple(record for record in records if record.kind == "command.source")
    explicit_source_evidence_count = 1 + sum(
        item.event.type == "source.reported_state_changed" for item in result.scenario.timeline
    )
    recorded_source_evidence_count = sum(record.kind == "initial.source_reported_state" for record in records) + sum(
        record.kind == "timeline.event" and record.payload.get("event_type") == "source.reported_state_changed"
        for record in records
    )

    assert records
    assert commands
    assert all(record.origin is RuntimeOrigin.SHADOW_SIMULATION for record in records)
    assert all(record.mode is SimulationMode.SCENARIO for record in records)
    assert all(record.environment_id == "shadow-soak" for record in records)
    assert all(record.payload.get("dispatch_outcome") == "dispatched" for record in commands)
    assert recorded_source_evidence_count == explicit_source_evidence_count
    assert not any(
        {"reported_state", "physical_state", "observed_state"}.intersection(record.payload) for record in commands
    )
