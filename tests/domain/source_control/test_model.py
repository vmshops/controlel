from datetime import UTC, datetime

import pytest

from controlel.domain.source_control import (
    ReportedSourceEvidence,
    ReportedSourceState,
    SourceCapabilities,
    SourceCapability,
    SourceOwnership,
    TransitionHistoryKnowledge,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_reported_source_evidence_keeps_report_and_transition_history_explicit() -> None:
    evidence = ReportedSourceEvidence(
        state=ReportedSourceState.ENABLED,
        observed_at=NOW,
    )

    assert evidence.state is ReportedSourceState.ENABLED
    assert evidence.transition_at is None
    assert evidence.transition_history is TransitionHistoryKnowledge.UNKNOWN
    assert SourceOwnership.CONTROLEL_OWNED.value == "controlel_owned"


def test_known_reported_transition_is_evidence_not_command_success() -> None:
    evidence = ReportedSourceEvidence(
        state=ReportedSourceState.DISABLED,
        observed_at=NOW,
        transition_at=NOW,
    )

    assert evidence.transition_history is TransitionHistoryKnowledge.KNOWN
    assert not hasattr(evidence, "successful_command")


def test_source_capabilities_are_immutable_and_explicit() -> None:
    capabilities = SourceCapabilities(frozenset({SourceCapability.ENABLE_DISABLE, SourceCapability.WATER_TARGET}))

    assert capabilities.supports(SourceCapability.WATER_TARGET)
    with pytest.raises(AttributeError):
        capabilities.values.add(SourceCapability.WATER_TARGET)  # type: ignore[attr-defined]


def test_source_capabilities_require_enable_disable_for_current_source_contract() -> None:
    with pytest.raises(ValueError, match="ENABLE_DISABLE"):
        SourceCapabilities(frozenset({SourceCapability.WATER_TARGET}))


@pytest.mark.parametrize("field", ["observed_at", "transition_at"])
def test_reported_source_evidence_rejects_naive_timestamps(field: str) -> None:
    values = {
        "state": ReportedSourceState.ENABLED,
        "observed_at": NOW,
        "transition_at": NOW,
    }
    values[field] = datetime(2026, 1, 1)

    with pytest.raises(ValueError, match="timezone-aware"):
        ReportedSourceEvidence(**values)
