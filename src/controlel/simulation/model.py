"""Immutable Shadow Simulation run, provenance, report, and replay models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from controlel.simulation.scenario import (
    CANONICALIZATION_POLICY_VERSION,
    FrozenJsonMapping,
    ImmutableJsonMapping,
    Scenario,
    canonical_json,
    freeze_json,
    normalize_json,
)

TRACE_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1
REPLAY_SCHEMA_VERSION = 1
SIMULATION_CONTRACT_VERSION = "0.1"
SCHEDULER_POLICY_VERSION = 1
TIMELINE_ORDERING_POLICY_VERSION = 1
SEMANTIC_FINGERPRINT_POLICY_VERSION = 1
ASSERTION_CONTRACT_VERSION = 1


class RuntimeOrigin(StrEnum):
    REAL = "REAL"
    SHADOW_SIMULATION = "SHADOW_SIMULATION"


class SimulationMode(StrEnum):
    REAL = "real"
    SCENARIO = "scenario"


class SimulationOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class AssertionStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class SimulationRun(BaseModel):
    """Identity and immutable provenance for one isolated Shadow execution."""

    run_id: str = Field(min_length=1)
    environment_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    started_at: datetime
    origin: Literal[RuntimeOrigin.SHADOW_SIMULATION] = RuntimeOrigin.SHADOW_SIMULATION
    mode: Literal[SimulationMode.SCENARIO] = SimulationMode.SCENARIO

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("started_at")
    @classmethod
    def started_at_must_be_aware(cls, value: datetime) -> datetime:
        return _aware(value, "started_at")


class ProvenanceEnvelope(BaseModel):
    """One captured record with mandatory, presentation-safe environment origin."""

    schema_version: int = TRACE_SCHEMA_VERSION
    record_id: str = Field(min_length=1)
    origin: RuntimeOrigin
    environment_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    mode: SimulationMode
    scenario_id: str | None = None
    kind: str = Field(min_length=1)
    recorded_at: datetime
    scheduled_for: datetime | None = None
    delivered_at: datetime | None = None
    evidence_at: datetime | None = None
    payload: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("schema_version")
    @classmethod
    def schema_version_must_be_supported(cls, value: int) -> int:
        if value != TRACE_SCHEMA_VERSION:
            raise ValueError(f"unsupported trace schema version: {value}")
        return value

    @field_validator("recorded_at", "scheduled_for", "delivered_at", "evidence_at")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime | None, info: object) -> datetime | None:
        if value is None:
            return None
        return _aware(value, str(getattr(info, "field_name", "timestamp")))

    @field_validator("payload", mode="after")
    @classmethod
    def payload_must_be_json_data(cls, value: object) -> FrozenJsonMapping:
        normalized = normalize_json(value)
        if not isinstance(normalized, dict):
            raise TypeError("payload must be a mapping")
        frozen = freeze_json(normalized)
        if not isinstance(frozen, FrozenJsonMapping):
            raise TypeError("payload must be a mapping")
        return frozen

    @model_validator(mode="after")
    def provenance_combination_must_be_unambiguous(self) -> ProvenanceEnvelope:
        if self.origin is RuntimeOrigin.REAL:
            if self.mode is not SimulationMode.REAL or self.scenario_id is not None:
                raise ValueError("REAL records require real mode and no scenario_id")
        elif self.mode is not SimulationMode.SCENARIO or not self.scenario_id:
            raise ValueError("SHADOW_SIMULATION records require scenario mode and scenario_id")
        return self

    def semantic_data(self) -> dict[str, object]:
        """Return behavior-bearing fields, excluding run/storage identity."""

        return {
            "origin": self.origin.value,
            "mode": self.mode.value,
            "scenario_id": self.scenario_id,
            "kind": self.kind,
            "recorded_at": self.recorded_at,
            "scheduled_for": self.scheduled_for,
            "delivered_at": self.delivered_at,
            "evidence_at": self.evidence_at,
            "payload": self.payload,
        }


class AssertionResult(BaseModel):
    expectation_index: int = Field(ge=0)
    expectation_type: str
    status: AssertionStatus
    reason_code: str
    evidence_record_ids: tuple[str, ...] = ()

    model_config = ConfigDict(frozen=True, extra="forbid")


class SimulationReport(BaseModel):
    """Immutable result over one isolated, deterministic execution trace."""

    schema_version: int = REPORT_SCHEMA_VERSION
    run: SimulationRun
    scenario_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    core_version: str
    simulation_contract_version: str = SIMULATION_CONTRACT_VERSION
    module_adapter_version: str
    ended_at: datetime
    outcome: SimulationOutcome
    records: tuple[ProvenanceEnvelope, ...]
    assertions: tuple[AssertionResult, ...]
    errors: tuple[str, ...] = ()
    semantic_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_fingerprint_policy_version: int = SEMANTIC_FINGERPRINT_POLICY_VERSION

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("ended_at")
    @classmethod
    def ended_at_must_be_aware(cls, value: datetime) -> datetime:
        return _aware(value, "ended_at")


class ReplayArtifact(BaseModel):
    """Self-contained canonical input plus expected semantic execution fingerprint."""

    schema_version: int = REPLAY_SCHEMA_VERSION
    scenario_schema_version: int
    trace_schema_version: int = TRACE_SCHEMA_VERSION
    report_schema_version: int = REPORT_SCHEMA_VERSION
    simulation_contract_version: str = SIMULATION_CONTRACT_VERSION
    canonicalization_policy_version: int
    scheduler_policy_version: int = SCHEDULER_POLICY_VERSION
    timeline_ordering_policy_version: int = TIMELINE_ORDERING_POLICY_VERSION
    semantic_fingerprint_policy_version: int = SEMANTIC_FINGERPRINT_POLICY_VERSION
    assertion_contract_version: int = ASSERTION_CONTRACT_VERSION
    source_core_version: str
    module_adapter_version: str
    module: str
    module_contract_version: int
    scenario_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_scenario: ImmutableJsonMapping
    expected_semantic_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("canonical_scenario", mode="after")
    @classmethod
    def canonical_scenario_must_be_immutable_json(cls, value: object) -> FrozenJsonMapping:
        frozen = freeze_json(value)
        if not isinstance(frozen, FrozenJsonMapping):
            raise TypeError("canonical_scenario must be a mapping")
        return frozen

    @model_validator(mode="after")
    def metadata_must_match_canonical_scenario(self) -> ReplayArtifact:
        scenario = Scenario.from_mapping(self.canonical_scenario)
        expected_metadata = {
            "scenario_schema_version": scenario.schema_version,
            "module": scenario.module,
            "module_contract_version": scenario.module_contract_version,
        }
        for field_name, expected_value in expected_metadata.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"replay {field_name} does not match canonical scenario")
        if self.scenario_hash != scenario.content_hash:
            raise ValueError("replay scenario hash does not match canonical scenario")
        return self

    @classmethod
    def from_execution(cls, scenario: Scenario, report: SimulationReport) -> ReplayArtifact:
        if scenario.content_hash != report.scenario_hash:
            raise ValueError("report does not belong to the supplied scenario")
        return cls(
            scenario_schema_version=scenario.schema_version,
            canonicalization_policy_version=CANONICALIZATION_POLICY_VERSION,
            source_core_version=report.core_version,
            module_adapter_version=report.module_adapter_version,
            module=scenario.module,
            module_contract_version=scenario.module_contract_version,
            scenario_hash=scenario.content_hash,
            canonical_scenario=scenario.canonical_data(),
            expected_semantic_fingerprint=report.semantic_fingerprint,
        )

    def canonical_json(self) -> str:
        return canonical_json(self.model_dump(mode="json"))


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value
