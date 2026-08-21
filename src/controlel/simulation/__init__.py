"""Outer-layer deterministic behavioral simulation for Controlel."""

from controlel.simulation.adapters.heating import (
    HEATING_MODULE_CONTRACT_VERSION,
    HeatingScenarioConfiguration,
    HeatingSimulationAdapter,
)
from controlel.simulation.adapters.heating_soak import (
    HEATING_SOAK_GENERATOR_VERSION,
    HEATING_SOAK_MAX_DURATION,
    HEATING_SOAK_MAX_TIMELINE_EVENTS,
    HeatingSoakConfiguration,
    HeatingSoakOutcome,
    HeatingSoakReport,
    HeatingSoakResult,
    HeatingSoakRunner,
    generate_heating_soak_scenario,
)
from controlel.simulation.model import (
    AssertionResult,
    AssertionStatus,
    ProvenanceEnvelope,
    ReplayArtifact,
    RuntimeOrigin,
    SimulationMode,
    SimulationOutcome,
    SimulationReport,
    SimulationRun,
)
from controlel.simulation.recorder import SimulationRecorder
from controlel.simulation.runner import ScenarioRunner, TrustedSimulationAdapter
from controlel.simulation.scenario import (
    CANONICALIZATION_POLICY_VERSION,
    SCENARIO_SCHEMA_VERSION,
    Scenario,
    ScenarioEvent,
    ScenarioExpectation,
    ScenarioTimelineItem,
    TimelinePhase,
)
from controlel.simulation.time import DeterministicScheduler, VirtualClock

__all__ = [
    "CANONICALIZATION_POLICY_VERSION",
    "HEATING_MODULE_CONTRACT_VERSION",
    "HEATING_SOAK_GENERATOR_VERSION",
    "HEATING_SOAK_MAX_DURATION",
    "HEATING_SOAK_MAX_TIMELINE_EVENTS",
    "SCENARIO_SCHEMA_VERSION",
    "AssertionResult",
    "AssertionStatus",
    "DeterministicScheduler",
    "HeatingScenarioConfiguration",
    "HeatingSimulationAdapter",
    "HeatingSoakConfiguration",
    "HeatingSoakOutcome",
    "HeatingSoakReport",
    "HeatingSoakResult",
    "HeatingSoakRunner",
    "ProvenanceEnvelope",
    "ReplayArtifact",
    "RuntimeOrigin",
    "Scenario",
    "ScenarioEvent",
    "ScenarioExpectation",
    "ScenarioRunner",
    "ScenarioTimelineItem",
    "SimulationMode",
    "SimulationOutcome",
    "SimulationRecorder",
    "SimulationReport",
    "SimulationRun",
    "TimelinePhase",
    "TrustedSimulationAdapter",
    "VirtualClock",
    "generate_heating_soak_scenario",
]
