"""Validation tests for observational heating-anomaly contracts."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from controlel.domain.heat_delivery import (
    HeatingAnomalyCategory,
    HeatingAnomalyConfidence,
    HeatingAnomalyEvidence,
    HeatingAnomalyEvidenceItem,
    HeatingAnomalyLifecycle,
    HeatingAnomalyObservation,
    HeatingAnomalySeverity,
    heating_anomaly_id,
)
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def anomaly() -> HeatingAnomalyObservation:
    episode_id = "heating_episode:living_room:2026-01-01T00:00:00+00:00"
    return HeatingAnomalyObservation(
        anomaly_id=heating_anomaly_id(
            category=HeatingAnomalyCategory.PERFORMANCE,
            reason_code="temperature_falling",
            zone_id=ZoneId("living_room"),
            heating_episode_id=episode_id,
        ),
        category=HeatingAnomalyCategory.PERFORMANCE,
        severity=HeatingAnomalySeverity.WARNING,
        confidence=HeatingAnomalyConfidence.HIGH,
        reason_code="temperature_falling",
        lifecycle=HeatingAnomalyLifecycle.STARTED,
        first_observed_at=NOW,
        last_observed_at=NOW,
        updated_at=NOW,
        cleared_at=None,
        zone_id=ZoneId("living_room"),
        source_id=None,
        heating_episode_id=episode_id,
        assessment_id="assessment:1",
        lifecycle_reason_code="condition_detected",
        evidence=HeatingAnomalyEvidence(
            items=(
                HeatingAnomalyEvidenceItem("sample_count", 3),
                HeatingAnomalyEvidenceItem("temperature_delta", -0.4),
            ),
            source_observation_timestamps=(NOW, NOW + timedelta(minutes=30)),
        ),
    )


def test_anomaly_is_immutable_and_retains_structured_evidence_and_scope() -> None:
    observation = anomaly()

    assert observation.is_active is True
    assert observation.zone_id == ZoneId("living_room")
    assert observation.source_id is None
    assert observation.heating_episode_id is not None
    assert {item.key: item.value for item in observation.evidence.items} == {
        "sample_count": 3,
        "temperature_delta": -0.4,
    }
    assert observation.evidence.source_observation_timestamps[-1] == NOW + timedelta(minutes=30)
    with pytest.raises(FrozenInstanceError):
        observation.lifecycle = HeatingAnomalyLifecycle.CLEARED  # type: ignore[misc]


def test_assessment_correlation_is_optional_and_observation_end_is_not_clear() -> None:
    observation = replace(
        anomaly(),
        lifecycle=HeatingAnomalyLifecycle.OBSERVATION_ENDED,
        updated_at=NOW + timedelta(hours=1),
        assessment_id=None,
    )

    assert observation.assessment_id is None
    assert observation.cleared_at is None
    assert observation.is_active is False


@pytest.mark.parametrize(
    "change",
    (
        {"reason_code": "not-a-code"},
        {"assessment_id": ""},
        {"zone_id": None, "heating_episode_id": None},
        {"lifecycle": HeatingAnomalyLifecycle.CLEARED, "cleared_at": None},
        {"lifecycle": HeatingAnomalyLifecycle.ACTIVE, "cleared_at": NOW},
        {"last_observed_at": NOW - timedelta(seconds=1)},
    ),
)
def test_anomaly_invariants_reject_invalid_identity_subject_and_lifecycle(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(anomaly(), **change)


def test_evidence_requires_sorted_unique_bounded_json_safe_values() -> None:
    with pytest.raises(ValueError, match="deterministic sorted order"):
        HeatingAnomalyEvidence(
            items=(
                HeatingAnomalyEvidenceItem("temperature_delta", -0.4),
                HeatingAnomalyEvidenceItem("sample_count", 3),
            )
        )
    with pytest.raises(TypeError, match="JSON-safe scalar"):
        HeatingAnomalyEvidenceItem("samples", object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique and sorted"):
        HeatingAnomalyEvidence(
            items=(),
            source_observation_timestamps=(NOW + timedelta(minutes=1), NOW),
        )
