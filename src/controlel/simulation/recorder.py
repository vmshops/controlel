"""Isolated Shadow trace recorder and semantic fingerprint projection."""

from __future__ import annotations

import hashlib
from datetime import datetime

from controlel.simulation.model import ProvenanceEnvelope, RuntimeOrigin, SimulationRun
from controlel.simulation.scenario import canonical_json


class SimulationRecorder:
    """Own one append-only Shadow trace; it cannot target a production sink."""

    def __init__(self, run: SimulationRun) -> None:
        if run.origin is not RuntimeOrigin.SHADOW_SIMULATION:
            raise ValueError("SimulationRecorder requires SHADOW_SIMULATION origin")
        self._run = run
        self._records: list[ProvenanceEnvelope] = []

    def record(
        self,
        kind: str,
        *,
        recorded_at: datetime,
        payload: dict[str, object] | None = None,
        scheduled_for: datetime | None = None,
        delivered_at: datetime | None = None,
        evidence_at: datetime | None = None,
    ) -> ProvenanceEnvelope:
        sequence = len(self._records) + 1
        envelope = ProvenanceEnvelope(
            record_id=f"shadow-record:{sequence:08d}",
            origin=self._run.origin,
            environment_id=self._run.environment_id,
            run_id=self._run.run_id,
            mode=self._run.mode,
            scenario_id=self._run.scenario_id,
            kind=kind,
            recorded_at=recorded_at,
            scheduled_for=scheduled_for,
            delivered_at=delivered_at,
            evidence_at=evidence_at,
            payload=payload or {},
        )
        self._records.append(envelope)
        return envelope

    @property
    def records(self) -> tuple[ProvenanceEnvelope, ...]:
        return tuple(self._records)

    def semantic_fingerprint(self) -> str:
        trace = [record.semantic_data() for record in self._records]
        return hashlib.sha256(canonical_json(trace).encode("utf-8")).hexdigest()
