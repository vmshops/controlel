"""Tests for passive bounded M31C.1 heating-performance assessment."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.services.heating_performance_assessor import HeatingPerformanceAssessor
from controlel.application.services.heating_performance_monitor import (
    HeatingPerformanceMonitor,
    heating_performance_snapshot_to_dict,
)
from controlel.application.services.operational_event_recorder import OperationalEventRecorder
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.heat_delivery import (
    HeatingAnomalyLifecycle,
    HeatingDemandTransition,
    HeatingEpisode,
    HeatingEpisodeSample,
    HeatingEpisodeTerminationReason,
    HeatingPerformanceAssessmentCriteria,
    HeatingPerformanceAssessmentReason,
    HeatingPerformanceAssessmentType,
    HeatingPerformanceStatus,
    HeatSourceObservation,
    ObservationQuality,
    ObservedValue,
)
from controlel.domain.operational_events import OperationalEventCode
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _sample(
    minute: int,
    temperature: float | None,
    *,
    target: float = 22.0,
    observed_minute: int | None = None,
    quality: ObservationQuality = ObservationQuality.VALID,
    permission_enabled_at: datetime = NOW,
) -> HeatingEpisodeSample:
    captured_at = NOW + timedelta(minutes=minute)
    if quality is ObservationQuality.VALID:
        observed_at = NOW + timedelta(minutes=observed_minute if observed_minute is not None else minute)
        observed = ObservedValue.valid(temperature, observed_at)
    elif quality is ObservationQuality.STALE:
        observed = ObservedValue(
            value=temperature,
            observed_at=NOW + timedelta(minutes=observed_minute or 0),
            quality=quality,
            reason="measurement_stale",
        )
    else:
        observed = ObservedValue.unknown("measurement_unavailable")
    return HeatingEpisodeSample(
        captured_at=captured_at,
        zone_temperature=observed,
        target_temperature=target,
        actuator_observations=(),
        source_observation=HeatSourceObservation(
            captured_at=captured_at,
            last_requested_action=HeatingAction.ENABLE_HEATING,
            last_successful_dispatch_action=HeatingAction.ENABLE_HEATING,
            last_successful_dispatch_at=permission_enabled_at,
        ),
    )


def _episode(
    zone: str,
    *samples: HeatingEpisodeSample,
    started_at: datetime = NOW,
    truncated: bool = False,
) -> HeatingEpisode:
    valid = [sample.zone_temperature.value for sample in samples if sample.zone_temperature.value is not None]
    return HeatingEpisode(
        zone_id=ZoneId(zone),
        started_at=started_at,
        ended_at=None,
        termination_reason=None,
        initial_target_temperature=samples[0].target_temperature,
        current_target_temperature=samples[-1].target_temperature,
        initial_temperature=float(valid[0]) if valid else None,
        current_temperature=float(valid[-1]) if valid else None,
        demand_transitions=(
            HeatingDemandTransition(demand=BuildingHeatDemandStatus.HEAT_REQUIRED, changed_at=started_at),
        ),
        total_sample_count=len(samples) + int(truncated),
        samples_truncated=truncated,
        samples=samples,
    )


def _criteria(**changes: object) -> HeatingPerformanceAssessmentCriteria:
    return replace(
        HeatingPerformanceAssessmentCriteria(),
        minimum_observation_duration=timedelta(minutes=30),
        minimum_valid_sample_count=3,
        observation_window=timedelta(minutes=30),
        meaningful_temperature_change=0.2,
        near_target_tolerance=0.2,
        maximum_measurement_age=timedelta(minutes=10),
        recovery_confirmation_count=2,
        **changes,
    )


def _completed_episode(
    episode: HeatingEpisode,
    *,
    reason: HeatingEpisodeTerminationReason = HeatingEpisodeTerminationReason.DEMAND_CLEARED,
) -> HeatingEpisode:
    return replace(
        episode,
        ended_at=episode.samples[-1].captured_at,
        termination_reason=reason,
    )


class SelectivelyFailingProgressAssessor:
    def __init__(self) -> None:
        self.criteria = _criteria()
        self._delegate = HeatingPerformanceAssessor(self.criteria)

    def assess_progress(self, episode: HeatingEpisode):
        if episode.zone_id == ZoneId("failed"):
            raise RuntimeError("private adapter detail")
        return self._delegate.assess_progress(episode)


def test_progress_contract_is_immutable_deterministic_and_explicit() -> None:
    episode = _episode("living_room", _sample(0, 20.0), _sample(15, 20.15), _sample(30, 20.3))
    assessor = HeatingPerformanceAssessor(_criteria())

    first = assessor.assess_progress(episode)
    second = assessor.assess_progress(episode)

    assert first == second
    assert first.assessment_type is HeatingPerformanceAssessmentType.HEATING_PROGRESS
    assert first.status is HeatingPerformanceStatus.NORMAL
    assert first.heating_episode_id == "heating_episode:living_room:2026-01-01T00:00:00+00:00"
    assert first.assessment_id.endswith(":2026-01-01T00:30:00+00:00")
    assert first.evidence.temperature_delta == pytest.approx(0.3)
    assert first.evidence.sample_count == 3
    assert first.evidence.evidence_quality is ObservationQuality.VALID
    with pytest.raises(FrozenInstanceError):
        first.status = HeatingPerformanceStatus.DEGRADED  # type: ignore[misc]


def test_multiple_samples_and_minimum_duration_are_required() -> None:
    episode = _episode("living_room", _sample(0, 20.0), _sample(30, 20.4))

    assessment = HeatingPerformanceAssessor(_criteria()).assess_progress(episode)

    assert assessment.status is HeatingPerformanceStatus.INSUFFICIENT_EVIDENCE
    assert assessment.reason is HeatingPerformanceAssessmentReason.INSUFFICIENT_DISTINCT_MEASUREMENTS
    assert assessment.evidence.sample_count == 2


@pytest.mark.parametrize(
    ("temperatures", "expected_status", "expected_reason"),
    [
        ((20.0, 20.02, 20.05), HeatingPerformanceStatus.DEGRADED, "temperature_response_flat"),
        ((20.0, 19.85, 19.7), HeatingPerformanceStatus.ANOMALOUS, "temperature_falling"),
    ],
)
def test_flat_and_falling_temperature_require_a_sufficient_window(
    temperatures: tuple[float, float, float],
    expected_status: HeatingPerformanceStatus,
    expected_reason: str,
) -> None:
    episode = _episode(
        "living_room",
        _sample(0, temperatures[0]),
        _sample(15, temperatures[1]),
        _sample(30, temperatures[2]),
    )

    assessment = HeatingPerformanceAssessor(_criteria()).assess_progress(episode)

    assert assessment.status is expected_status
    assert assessment.reason.value == expected_reason


def test_near_target_tiny_rise_is_normal_not_poor_performance() -> None:
    episode = _episode(
        "living_room",
        _sample(0, 21.85, target=22.0),
        _sample(15, 21.88, target=22.0),
        _sample(30, 21.9, target=22.0),
    )

    assessment = HeatingPerformanceAssessor(_criteria()).assess_progress(episode)

    assert assessment.status is HeatingPerformanceStatus.NORMAL
    assert assessment.reason is HeatingPerformanceAssessmentReason.NEAR_TARGET
    assert assessment.evidence.distance_to_target_now == pytest.approx(0.1)


def test_target_change_rebases_and_requires_a_fresh_window() -> None:
    episode = _episode(
        "living_room",
        _sample(0, 20.0, target=21.0),
        _sample(15, 20.1, target=22.0),
        _sample(30, 20.3, target=22.0),
    )

    assessment = HeatingPerformanceAssessor(_criteria()).assess_progress(episode)

    assert assessment.status is HeatingPerformanceStatus.INSUFFICIENT_EVIDENCE
    assert assessment.reason is HeatingPerformanceAssessmentReason.TARGET_CHANGED
    assert assessment.evidence.observation_window_started_at == NOW + timedelta(minutes=15)


@pytest.mark.parametrize(
    "latest",
    [
        _sample(30, None, quality=ObservationQuality.UNKNOWN),
        _sample(30, 20.2, observed_minute=0, quality=ObservationQuality.STALE),
    ],
)
def test_missing_or_stale_latest_measurement_is_insufficient(latest: HeatingEpisodeSample) -> None:
    episode = _episode("living_room", _sample(0, 20.0), _sample(15, 20.1), latest)

    assessment = HeatingPerformanceAssessor(_criteria()).assess_progress(episode)

    assert assessment.status is HeatingPerformanceStatus.INSUFFICIENT_EVIDENCE
    assert assessment.evidence.evidence_quality in {ObservationQuality.UNKNOWN, ObservationQuality.STALE}


def test_indeterminate_assessment_does_not_create_an_anomaly() -> None:
    monitor = HeatingPerformanceMonitor(criteria=_criteria())
    monitor.submit(
        _episode(
            "living_room",
            _sample(0, 20.0),
            _sample(15, 19.8),
            _sample(30, None, quality=ObservationQuality.UNKNOWN),
        )
    )

    assessment = monitor.assess_pending()[0]
    snapshot = monitor.snapshot()

    assert assessment.status is HeatingPerformanceStatus.INSUFFICIENT_EVIDENCE
    assert snapshot.active_anomalies == ()
    assert snapshot.anomaly_transitions == ()


def test_performance_anomaly_start_active_clear_is_deduplicated_and_correlated() -> None:
    recorder = OperationalEventRecorder()
    monitor = HeatingPerformanceMonitor(criteria=_criteria(), anomaly_event_recorder=recorder)
    falling = _episode("living_room", _sample(0, 20.0), _sample(15, 19.85), _sample(30, 19.7))
    continuing = _episode(
        "living_room",
        *falling.samples,
        _sample(45, 19.5),
    )
    first_normal = _episode(
        "living_room",
        _sample(0, 20.0),
        _sample(15, 19.85),
        _sample(30, 19.7),
        _sample(45, 19.9),
        _sample(60, 20.1),
    )
    second_normal = replace(
        first_normal,
        total_sample_count=6,
        samples=(*first_normal.samples, _sample(75, 20.3)),
        current_temperature=20.3,
    )

    monitor.submit(falling)
    monitor.assess_pending()
    monitor.submit(falling)
    monitor.assess_pending()
    monitor.submit(continuing)
    monitor.assess_pending()

    active = monitor.snapshot().active_anomalies[0]
    assert active.lifecycle is HeatingAnomalyLifecycle.ACTIVE
    assert active.reason_code == "temperature_falling"
    assert active.zone_id == ZoneId("living_room")
    assert active.source_id is None
    assert active.heating_episode_id == "heating_episode:living_room:2026-01-01T00:00:00+00:00"
    assert active.last_observed_at == NOW + timedelta(minutes=45)
    assert len(active.evidence.source_observation_timestamps) == 3

    monitor.submit(first_normal)
    monitor.assess_pending()
    assert monitor.snapshot().active_anomalies[0].is_active is True
    monitor.submit(second_normal)
    monitor.assess_pending()

    snapshot = monitor.snapshot()
    assert snapshot.active_anomalies == ()
    assert [item.lifecycle for item in snapshot.anomaly_transitions] == [
        HeatingAnomalyLifecycle.STARTED,
        HeatingAnomalyLifecycle.CLEARED,
    ]
    assert snapshot.total_anomaly_transitions_emitted == 2
    assert snapshot.anomaly_transitions[-1].lifecycle_reason_code == "performance_recovered"
    assert snapshot.anomaly_transitions[-1].cleared_at == NOW + timedelta(minutes=75)
    events = recorder.stream.snapshot().events
    assert [event.event_code for event in events] == [
        OperationalEventCode.HEATING_ANOMALY_STARTED,
        OperationalEventCode.HEATING_ANOMALY_CLEARED,
    ]
    assert len({event.activity_id for event in events}) == 1
    assert {event.correlation_id for event in events} == {active.heating_episode_id}
    assert all(event.requested_command is None and event.command_outcome is None for event in events)
    assert all(event.event_code is not OperationalEventCode.HEATING_ANOMALY_OBSERVATION_ENDED for event in events)


def test_episode_closure_while_anomaly_remains_present_ends_observation_without_clear() -> None:
    recorder = OperationalEventRecorder()
    monitor = HeatingPerformanceMonitor(criteria=_criteria(), anomaly_event_recorder=recorder)
    falling = _episode("living_room", _sample(0, 20.0), _sample(15, 19.85), _sample(30, 19.7))
    terminal = _completed_episode(
        _episode(
            "living_room",
            *falling.samples,
            _sample(45, 19.5),
        )
    )

    monitor.submit(falling)
    monitor.assess_pending()
    monitor.submit(terminal)
    terminal_assessment = monitor.assess_pending()[0]

    assert terminal_assessment.status is HeatingPerformanceStatus.ANOMALOUS
    snapshot = monitor.snapshot()
    assert snapshot.active_anomalies == ()
    assert [item.lifecycle for item in snapshot.anomaly_transitions] == [
        HeatingAnomalyLifecycle.STARTED,
        HeatingAnomalyLifecycle.OBSERVATION_ENDED,
    ]
    ended = snapshot.anomaly_transitions[-1]
    assert ended.lifecycle_reason_code == "heating_episode_ended"
    assert ended.cleared_at is None
    assert ended.last_observed_at == terminal.ended_at
    assert [event.event_code for event in recorder.stream.snapshot().events] == [
        OperationalEventCode.HEATING_ANOMALY_STARTED,
        OperationalEventCode.HEATING_ANOMALY_OBSERVATION_ENDED,
    ]


def test_episode_closure_with_insufficient_evidence_does_not_claim_recovery() -> None:
    recorder = OperationalEventRecorder()
    monitor = HeatingPerformanceMonitor(criteria=_criteria(), anomaly_event_recorder=recorder)
    falling = _episode("living_room", _sample(0, 20.0), _sample(15, 19.85), _sample(30, 19.7))
    terminal = _completed_episode(
        _episode(
            "living_room",
            *falling.samples,
            _sample(45, None, quality=ObservationQuality.UNKNOWN),
        )
    )

    monitor.submit(falling)
    monitor.assess_pending()
    monitor.submit(terminal)
    terminal_assessment = monitor.assess_pending()[0]

    assert terminal_assessment.status is HeatingPerformanceStatus.INSUFFICIENT_EVIDENCE
    snapshot = monitor.snapshot()
    ended = snapshot.anomaly_transitions[-1]
    assert ended.lifecycle is HeatingAnomalyLifecycle.OBSERVATION_ENDED
    assert ended.cleared_at is None
    assert ended.last_observed_at == NOW + timedelta(minutes=30)
    assert ended.lifecycle_reason_code == "heating_episode_ended"
    assert all(
        event.event_code is not OperationalEventCode.HEATING_ANOMALY_CLEARED
        for event in recorder.stream.snapshot().events
    )


def test_episode_replacement_ends_previous_observation_without_clear() -> None:
    recorder = OperationalEventRecorder()
    monitor = HeatingPerformanceMonitor(criteria=_criteria(), anomaly_event_recorder=recorder)
    falling = _episode("living_room", _sample(0, 20.0), _sample(15, 19.85), _sample(30, 19.7))
    replacement_start = NOW + timedelta(hours=2)
    replacement = _episode(
        "living_room",
        _sample(120, 20.0, permission_enabled_at=replacement_start),
        started_at=replacement_start,
    )

    monitor.submit(falling)
    monitor.assess_pending()
    monitor.submit(replacement)
    monitor.assess_pending()

    ended = monitor.snapshot().anomaly_transitions[-1]
    assert ended.lifecycle is HeatingAnomalyLifecycle.OBSERVATION_ENDED
    assert ended.lifecycle_reason_code == "heating_episode_replaced"
    assert ended.cleared_at is None
    assert [event.event_code for event in recorder.stream.snapshot().events] == [
        OperationalEventCode.HEATING_ANOMALY_STARTED,
        OperationalEventCode.HEATING_ANOMALY_OBSERVATION_ENDED,
    ]


def test_disabled_source_permission_is_explicitly_insufficient() -> None:
    samples = (_sample(0, 20.0), _sample(15, 20.1), _sample(30, 20.3))
    latest = replace(
        samples[-1],
        source_observation=replace(
            samples[-1].source_observation,
            last_requested_action=HeatingAction.DISABLE_HEATING,
            last_successful_dispatch_action=HeatingAction.DISABLE_HEATING,
        ),
    )

    assessment = HeatingPerformanceAssessor(_criteria()).assess_progress(
        _episode("living_room", samples[0], samples[1], latest)
    )

    assert assessment.status is HeatingPerformanceStatus.INSUFFICIENT_EVIDENCE
    assert assessment.reason is HeatingPerformanceAssessmentReason.HEATING_PERMISSION_NOT_ENABLED


def test_duplicate_timestamp_is_deduplicated_but_conflict_and_order_are_rejected() -> None:
    assessor = HeatingPerformanceAssessor(_criteria())
    duplicate = _episode(
        "living_room",
        _sample(0, 20.0),
        _sample(15, 20.0, observed_minute=0),
        _sample(30, 20.3),
    )
    conflict = _episode(
        "living_room",
        _sample(0, 20.0),
        _sample(15, 20.1, observed_minute=0),
        _sample(30, 20.3),
    )
    out_of_order = _episode(
        "living_room",
        _sample(0, 20.0, observed_minute=0),
        _sample(15, 20.2, observed_minute=20),
        _sample(30, 20.3, observed_minute=15),
    )

    duplicate_assessment = assessor.assess_progress(duplicate)
    conflict_assessment = assessor.assess_progress(conflict)
    order_assessment = assessor.assess_progress(out_of_order)

    assert duplicate_assessment.evidence.duplicate_sample_count == 1
    assert duplicate_assessment.status is HeatingPerformanceStatus.INSUFFICIENT_EVIDENCE
    assert conflict_assessment.evidence.evidence_quality is ObservationQuality.CONFLICTING
    assert order_assessment.reason is HeatingPerformanceAssessmentReason.NON_MONOTONIC_TIMESTAMPS


def test_truncated_history_does_not_fabricate_continuity() -> None:
    episode = _episode(
        "living_room",
        _sample(0, 20.0),
        _sample(15, 20.1),
        _sample(30, 20.3),
        truncated=True,
    )

    assessment = HeatingPerformanceAssessor(_criteria()).assess_progress(episode)

    assert assessment.status is HeatingPerformanceStatus.INSUFFICIENT_EVIDENCE
    assert assessment.reason is HeatingPerformanceAssessmentReason.HISTORY_TRUNCATED


def test_recovery_requires_two_normal_assessment_windows() -> None:
    monitor = HeatingPerformanceMonitor(criteria=_criteria())
    falling = _episode("living_room", _sample(0, 20.0), _sample(15, 19.85), _sample(30, 19.7))
    first_normal = _episode(
        "living_room",
        _sample(0, 20.0),
        _sample(15, 19.85),
        _sample(30, 19.7),
        _sample(45, 19.9),
        _sample(60, 20.1),
    )
    second_normal = replace(
        first_normal,
        total_sample_count=6,
        samples=(*first_normal.samples, _sample(75, 20.3)),
        current_temperature=20.3,
    )

    monitor.submit(falling)
    anomalous = monitor.assess_pending()[0]
    monitor.submit(first_normal)
    pending = monitor.assess_pending()[0]
    monitor.submit(second_normal)
    recovered = monitor.assess_pending()[0]

    assert anomalous.status is HeatingPerformanceStatus.ANOMALOUS
    assert pending.status is HeatingPerformanceStatus.ANOMALOUS
    assert pending.reason is HeatingPerformanceAssessmentReason.RECOVERY_CONFIRMATION_PENDING
    assert recovered.status is HeatingPerformanceStatus.RECOVERED
    assert recovered.reason is HeatingPerformanceAssessmentReason.PERFORMANCE_RECOVERED


def test_repeated_identical_normal_window_does_not_confirm_recovery() -> None:
    monitor = HeatingPerformanceMonitor(criteria=_criteria())
    falling = _episode("living_room", _sample(0, 20.0), _sample(15, 19.85), _sample(30, 19.7))
    normal = _episode(
        "living_room",
        _sample(0, 20.0),
        _sample(15, 19.85),
        _sample(30, 19.7),
        _sample(45, 19.9),
        _sample(60, 20.1),
    )

    monitor.submit(falling)
    monitor.assess_pending()
    monitor.submit(normal)
    first = monitor.assess_pending()[0]
    monitor.submit(normal)
    repeated = monitor.assess_pending()[0]

    assert first.status is HeatingPerformanceStatus.ANOMALOUS
    assert repeated.status is HeatingPerformanceStatus.ANOMALOUS
    assert repeated.reason is HeatingPerformanceAssessmentReason.RECOVERY_CONFIRMATION_PENDING


def test_episode_change_resets_recovery_and_zones_are_independent() -> None:
    monitor = HeatingPerformanceMonitor(criteria=_criteria())
    failing = _episode("living_room", _sample(0, 20.0), _sample(15, 19.85), _sample(30, 19.7))
    normal_other = _episode("bedroom", _sample(0, 19.0), _sample(15, 19.2), _sample(30, 19.4))
    new_episode = _episode(
        "living_room",
        _sample(60, 19.7, permission_enabled_at=NOW + timedelta(hours=1)),
        _sample(75, 19.9, permission_enabled_at=NOW + timedelta(hours=1)),
        _sample(90, 20.1, permission_enabled_at=NOW + timedelta(hours=1)),
        started_at=NOW + timedelta(hours=1),
    )

    monitor.submit(failing)
    monitor.submit(normal_other)
    monitor.assess_pending()
    monitor.submit(new_episode)
    result = monitor.assess_pending()[0]
    snapshot = monitor.snapshot()

    assert result.status is HeatingPerformanceStatus.NORMAL
    assert {zone.zone_id.value: zone.current.status for zone in snapshot.zones} == {
        "bedroom": HeatingPerformanceStatus.NORMAL,
        "living_room": HeatingPerformanceStatus.NORMAL,
    }
    assert all(zone.active_heating_episode_id == zone.heating_episode_id for zone in snapshot.zones)


def test_one_zone_assessment_failure_isolated_and_exception_message_is_not_exposed() -> None:
    monitor = HeatingPerformanceMonitor(assessor=SelectivelyFailingProgressAssessor())
    for zone in ("failed", "healthy"):
        monitor.submit(_episode(zone, _sample(0, 20.0), _sample(15, 20.2), _sample(30, 20.4)))

    assessments = monitor.assess_pending()
    payload = heating_performance_snapshot_to_dict(monitor.snapshot())

    assert [assessment.zone_id.value for assessment in assessments] == ["healthy"]
    assert payload["errors"] == [
        {
            "zone_id": "failed",
            "heating_episode_id": "heating_episode:failed:2026-01-01T00:00:00+00:00",
            "evidence_at": "2026-01-01T00:30:00+00:00",
            "exception_type": "RuntimeError",
        }
    ]
    assert "private adapter detail" not in str(payload)


def test_monitor_state_and_pending_work_are_bounded() -> None:
    monitor = HeatingPerformanceMonitor(criteria=_criteria(), assessment_capacity=2, pending_zone_capacity=2)
    for zone in ("first", "second", "third"):
        monitor.submit(_episode(zone, _sample(0, 20.0), _sample(15, 20.2), _sample(30, 20.4)))

    assessments = monitor.assess_pending()
    snapshot = monitor.snapshot()

    assert [item.zone_id.value for item in assessments] == ["second", "third"]
    assert snapshot.pending_observations_dropped == 1
    assert snapshot.assessment_capacity == 2
    assert len(snapshot.assessments) == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("minimum_observation_duration", timedelta(0)),
        ("minimum_valid_sample_count", 1),
        ("observation_window", timedelta(days=2)),
        ("meaningful_temperature_change", -0.1),
        ("near_target_tolerance", -0.1),
        ("maximum_measurement_age", timedelta(0)),
        ("recovery_confirmation_count", 1),
    ],
)
def test_progress_configuration_is_bounded_and_validated(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(HeatingPerformanceAssessmentCriteria(), **{field: value})
