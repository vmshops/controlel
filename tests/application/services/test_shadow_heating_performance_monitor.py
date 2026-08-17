from datetime import UTC, datetime, timedelta
from threading import Event, Thread

import pytest

from controlel.application.services.heating_performance_assessor import HeatingPerformanceAssessor
from controlel.application.services.heating_performance_monitor import heating_performance_snapshot_to_dict
from controlel.application.services.shadow_heating_performance_monitor import (
    MAX_RETAINED_HEATING_PERFORMANCE_ASSESSMENTS,
    PendingAssessmentDropReason,
    ShadowHeatingPerformanceMonitor,
)
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.heat_delivery import (
    HeatingDemandTransition,
    HeatingEpisode,
    HeatingEpisodeSample,
    HeatingEpisodeTerminationReason,
    HeatSourceObservation,
    ObservedValue,
)
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def episode(zone: str, *, offset: int = 0) -> HeatingEpisode:
    started_at = NOW + timedelta(hours=offset)
    ended_at = started_at + timedelta(hours=1)
    samples = tuple(
        HeatingEpisodeSample(
            captured_at=captured_at,
            zone_temperature=ObservedValue.valid(temperature, captured_at),
            target_temperature=22.0,
            actuator_observations=(),
            source_observation=HeatSourceObservation(captured_at=captured_at),
        )
        for captured_at, temperature in ((started_at, 20.0), (ended_at, 21.0))
    )
    return HeatingEpisode(
        zone_id=ZoneId(zone),
        started_at=started_at,
        ended_at=ended_at,
        termination_reason=HeatingEpisodeTerminationReason.DEMAND_CLEARED,
        initial_target_temperature=22.0,
        current_target_temperature=22.0,
        initial_temperature=20.0,
        current_temperature=21.0,
        demand_transitions=(
            HeatingDemandTransition(demand=BuildingHeatDemandStatus.HEAT_REQUIRED, changed_at=started_at),
            HeatingDemandTransition(demand=BuildingHeatDemandStatus.NO_HEAT_REQUIRED, changed_at=ended_at),
        ),
        total_sample_count=len(samples),
        samples_truncated=False,
        samples=samples,
    )


class FailingAssessor:
    def assess(self, candidate: HeatingEpisode):
        raise RuntimeError(f"cannot assess {candidate.zone_id.value}")


class BlockingFirstAssessor:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.first_entered = Event()
        self.release_first = Event()
        self._delegate = HeatingPerformanceAssessor()

    def assess(self, candidate: HeatingEpisode):
        self.calls.append(candidate.zone_id.value)
        if candidate.zone_id == ZoneId("first"):
            self.first_entered.set()
            if not self.release_first.wait(timeout=5):
                raise TimeoutError("first assessment was not released")
        return self._delegate.assess(candidate)


def test_disabled_monitor_produces_no_assessment() -> None:
    monitor = ShadowHeatingPerformanceMonitor(enabled=False)

    monitor.submit_episode(episode("living_room"))

    assert monitor.assess_pending() == ()
    assert monitor.pending_episode_count == 0
    assert monitor.assessments == ()
    assert monitor.errors == {}


def test_live_observation_is_assessed_only_by_explicit_shadow_drain() -> None:
    monitor = ShadowHeatingPerformanceMonitor()
    candidate = episode("living_room")

    monitor.submit_observation(candidate)

    assert monitor.pending_episode_count == 1
    assert monitor.performance_snapshot.assessments == ()

    monitor.assess_pending()
    snapshot = monitor.performance_snapshot
    payload = heating_performance_snapshot_to_dict(snapshot)

    assert snapshot.pending_observation_count == 0
    assert len(snapshot.assessments) == 1
    assert snapshot.zones[0].active_heating_episode_id is None
    assert payload["assessments"][0]["zone_id"] == "living_room"


def test_assessor_failure_is_contained_as_zone_error_evidence() -> None:
    monitor = ShadowHeatingPerformanceMonitor(assessor=FailingAssessor())

    monitor.submit_episode(episode("living_room"))

    assert monitor.assess_pending() == ()
    assert monitor.assessments == ()
    assert monitor.errors == {ZoneId("living_room"): "RuntimeError: cannot assess living_room"}


def test_assessment_storage_is_bounded_in_completion_order() -> None:
    monitor = ShadowHeatingPerformanceMonitor(max_assessments=2)

    monitor.submit_episode(episode("first", offset=0))
    monitor.assess_pending()
    monitor.submit_episode(episode("second", offset=2))
    monitor.assess_pending()
    monitor.submit_episode(episode("third", offset=4))
    monitor.assess_pending()

    assert [assessment.zone_id.value for assessment in monitor.assessments] == ["second", "third"]


def test_assessment_retention_capacity_has_a_hard_production_maximum() -> None:
    default_monitor = ShadowHeatingPerformanceMonitor()
    lower_test_monitor = ShadowHeatingPerformanceMonitor(max_assessments=2)

    assert MAX_RETAINED_HEATING_PERFORMANCE_ASSESSMENTS == 20
    assert default_monitor.assessment_capacity == 20
    assert default_monitor.diagnostic_snapshot().assessment_capacity == 20
    assert lower_test_monitor.assessment_capacity == 2
    assert lower_test_monitor.diagnostic_snapshot().assessment_capacity == 2

    with pytest.raises(ValueError, match="must not exceed 20"):
        ShadowHeatingPerformanceMonitor(max_assessments=21)


def test_pending_capacity_drops_oldest_with_truthful_stable_evidence() -> None:
    monitor = ShadowHeatingPerformanceMonitor(max_pending_episodes=2)

    monitor.submit_episode(episode("first", offset=0))
    monitor.submit_episode(episode("second", offset=2))
    monitor.submit_episode(episode("third", offset=4))

    assert monitor.pending_episode_count == 2
    assert monitor.dropped_pending_assessment_count == 1
    assert monitor.last_dropped_pending_assessment is not None
    assert monitor.last_dropped_pending_assessment.zone_id == ZoneId("first")
    assert monitor.last_dropped_pending_assessment.reason is PendingAssessmentDropReason.CAPACITY_REACHED

    monitor.submit_episode(episode("fourth", offset=6))
    assessments = monitor.assess_pending()

    assert monitor.dropped_pending_assessment_count == 2
    assert monitor.last_dropped_pending_assessment is not None
    assert monitor.last_dropped_pending_assessment.zone_id == ZoneId("second")
    assert [assessment.zone_id.value for assessment in assessments] == ["third", "fourth"]


def test_concurrent_drains_preserve_pending_episode_order() -> None:
    assessor = BlockingFirstAssessor()
    monitor = ShadowHeatingPerformanceMonitor(assessor=assessor)
    monitor.submit_episode(episode("first", offset=0))
    monitor.submit_episode(episode("second", offset=2))
    drain_results: list[tuple[str, ...]] = []

    def drain() -> None:
        drain_results.append(tuple(item.zone_id.value for item in monitor.assess_pending()))

    first_drain = Thread(target=drain)
    second_drain = Thread(target=drain)
    first_drain.start()
    assert assessor.first_entered.wait(timeout=5)
    second_drain.start()
    assert assessor.calls == ["first"]

    assessor.release_first.set()
    first_drain.join(timeout=5)
    second_drain.join(timeout=5)

    assert not first_drain.is_alive()
    assert not second_drain.is_alive()
    assert assessor.calls == ["first", "second"]
    assert [assessment.zone_id.value for assessment in monitor.assessments] == ["first", "second"]
    assert sorted(drain_results) == [(), ("first", "second")]
