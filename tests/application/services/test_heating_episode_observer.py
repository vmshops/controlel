from datetime import UTC, datetime, timedelta

from controlel.application.services.heating_episode_observer import (
    HeatingEpisodeObserver,
    heat_delivery_observation_from_state,
    heat_source_observation_from_state,
)
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.heat_delivery import (
    HeatDeliveryActuatorId,
    HeatDeliveryAssistPolicy,
    HeatDeliveryCapabilities,
    HeatDeliveryMode,
    HeatDeliveryOwnership,
    HeatDeliveryState,
    HeatingEpisodeTerminationReason,
    HeatSourceObservation,
    ObservationQuality,
    ObservedValue,
)
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ZONE = ZoneId("living_room")


def observe(
    observer: HeatingEpisodeObserver,
    demand: BuildingHeatDemandStatus,
    *,
    at: datetime = NOW,
    temperature: ObservedValue[float] | None = None,
) -> None:
    observer.observe(
        zone_id=ZONE,
        confirmed_demand=demand,
        target_temperature=22.0,
        zone_temperature=temperature or ObservedValue.valid(20.0, at),
        actuator_observations=(),
        source_observation=HeatSourceObservation(captured_at=at),
        captured_at=at,
    )


def test_episode_starts_updates_and_terminates_on_cleared_demand() -> None:
    observer = HeatingEpisodeObserver()
    observe(observer, BuildingHeatDemandStatus.HEAT_REQUIRED)
    observe(
        observer,
        BuildingHeatDemandStatus.HEAT_REQUIRED,
        at=NOW + timedelta(minutes=30),
        temperature=ObservedValue.valid(20.7, NOW + timedelta(minutes=30)),
    )
    observe(
        observer,
        BuildingHeatDemandStatus.NO_HEAT_REQUIRED,
        at=NOW + timedelta(hours=1),
        temperature=ObservedValue.valid(22.1, NOW + timedelta(hours=1)),
    )

    assert observer.active_episodes == ()
    episode = observer.completed_episodes[0]
    assert episode.started_at == NOW
    assert episode.ended_at == NOW + timedelta(hours=1)
    assert episode.initial_temperature == 20.0
    assert episode.current_temperature == 22.1
    assert episode.termination_reason is HeatingEpisodeTerminationReason.DEMAND_CLEARED
    assert [transition.demand for transition in episode.demand_transitions] == [
        BuildingHeatDemandStatus.HEAT_REQUIRED,
        BuildingHeatDemandStatus.NO_HEAT_REQUIRED,
    ]


def test_stale_measurement_is_retained_as_evidence_but_not_trusted_as_current_temperature() -> None:
    observer = HeatingEpisodeObserver()
    observe(observer, BuildingHeatDemandStatus.HEAT_REQUIRED)
    stale = ObservedValue(
        value=19.0,
        observed_at=NOW - timedelta(hours=1),
        quality=ObservationQuality.STALE,
        reason="measurement expired",
    )
    observe(
        observer,
        BuildingHeatDemandStatus.HEAT_REQUIRED,
        at=NOW + timedelta(minutes=10),
        temperature=stale,
    )

    episode = observer.active_episodes[0]
    assert episode.current_temperature == 20.0
    assert episode.samples[-1].zone_temperature is stale


def test_indeterminate_demand_terminates_episode_without_inventing_temperature() -> None:
    observer = HeatingEpisodeObserver()
    observe(observer, BuildingHeatDemandStatus.HEAT_REQUIRED)
    observe(
        observer,
        BuildingHeatDemandStatus.INDETERMINATE,
        at=NOW + timedelta(minutes=5),
        temperature=ObservedValue.unknown("measurement unavailable"),
    )

    episode = observer.completed_episodes[0]
    assert episode.current_temperature == 20.0
    assert episode.termination_reason is HeatingEpisodeTerminationReason.DEMAND_INDETERMINATE


def test_memory_is_bounded_for_samples_and_completed_episodes() -> None:
    observer = HeatingEpisodeObserver(max_completed_episodes=2, max_samples_per_episode=2)
    for index in range(3):
        started = NOW + timedelta(hours=index * 2)
        observe(observer, BuildingHeatDemandStatus.HEAT_REQUIRED, at=started)
        observe(observer, BuildingHeatDemandStatus.HEAT_REQUIRED, at=started + timedelta(minutes=1))
        observe(observer, BuildingHeatDemandStatus.HEAT_REQUIRED, at=started + timedelta(minutes=2))
        observe(observer, BuildingHeatDemandStatus.NO_HEAT_REQUIRED, at=started + timedelta(minutes=3))

    assert len(observer.completed_episodes) == 2
    assert all(len(episode.samples) == 2 for episode in observer.completed_episodes)
    assert observer.completed_episodes[0].started_at == NOW + timedelta(hours=2)


def test_new_observer_after_reload_has_no_shared_episode_state() -> None:
    before_reload = HeatingEpisodeObserver()
    observe(before_reload, BuildingHeatDemandStatus.HEAT_REQUIRED)

    after_reload = HeatingEpisodeObserver()

    assert len(before_reload.active_episodes) == 1
    assert after_reload.active_episodes == ()
    assert after_reload.completed_episodes == ()


def test_state_projection_marks_untimestamped_report_as_degraded() -> None:
    state = HeatDeliveryState(
        actuator_id=HeatDeliveryActuatorId("trv"),
        zone_id=ZONE,
        mode=HeatDeliveryMode.NATIVE,
        ownership=HeatDeliveryOwnership.DEVICE_OWNED,
        capabilities=HeatDeliveryCapabilities(can_read_target_temperature=True),
        assist_policy=HeatDeliveryAssistPolicy.NO_ASSIST,
        reported_target_temperature=21.5,
        last_command_timestamp=NOW - timedelta(seconds=10),
    )

    observation = heat_delivery_observation_from_state(state, captured_at=NOW)

    assert observation.reported_target_temperature.value == 21.5
    assert observation.reported_target_temperature.observed_at is None
    assert observation.reported_target_temperature.quality is ObservationQuality.DEGRADED
    assert observation.last_command_timestamp == NOW - timedelta(seconds=10)


def test_source_projection_keeps_physical_availability_unknown() -> None:
    observation = heat_source_observation_from_state(None, captured_at=NOW)

    assert observation.reported_heat_available.quality is ObservationQuality.UNKNOWN
    assert observation.reported_heat_available.value is None
