from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from threading import Thread, get_ident
from unittest.mock import patch

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, EntityCategory, UnitOfTemperature
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import translation
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
from custom_components.controlel.const import (
    CONF_DIAGNOSTIC_PROFILE,
    CONF_HEAT_DEMAND_CONFIRMATION_DURATION,
    CONF_HEATING_TURN_OFF_DIFFERENTIAL,
    CONF_HEATING_TURN_ON_DIFFERENTIAL,
    CONF_INDETERMINATE_GRACE_PERIOD,
    CONF_MINIMUM_HEATING_OFF_TIME,
    CONF_MINIMUM_HEATING_ON_TIME,
    CONF_PRIMARY_MEASUREMENT_MAX_AGE,
    CONF_TARGET_TEMPERATURE,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_ZONE_NAME,
    DIAGNOSTIC_PROFILE_BASIC,
    DIAGNOSTIC_PROFILE_DEBUG,
    DIAGNOSTIC_PROFILE_DETAILED,
    DOMAIN,
)
from custom_components.controlel.diagnostics import async_get_config_entry_diagnostics
from custom_components.controlel.entity import ControlelSnapshotEntity
from custom_components.controlel.operational import SafetyState

EXPECTED_SENSOR_KEYS = {
    "active_demand_cause",
    "active_lockout_type",
    "active_lockout_deadline",
    "active_lockout_remaining",
    "core_version",
    "current_temperature",
    "debug_expiry_deadline",
    "debug_expiry_remaining",
    "debug_profile_duration",
    "decision_trace_capacity",
    "deferred_command",
    "deferred_deadline",
    "deferred_reason",
    "deferred_remaining",
    "deferred_since",
    "diagnostic_profile",
    "duplicate_commands_suppressed",
    "emergency_disable_outcome",
    "grace_deadline",
    "grace_remaining",
    "heat_demand",
    "heat_demand_confirmation_deadline",
    "heat_demand_confirmation_duration",
    "heat_demand_confirmation_remaining",
    "heat_demand_confirmation_state",
    "heating_performance_living_room",
    "heating_disable_threshold",
    "heating_enable_threshold",
    "heating_turn_off_differential",
    "heating_turn_on_differential",
    "hysteresis_demand",
    "confirmed_zone_heat_demand",
    "integration_version",
    "earliest_next_disable_time",
    "earliest_next_enable_time",
    "last_command_outcome",
    "last_command_time",
    "last_decision",
    "last_decision_reason",
    "last_meaningful_event",
    "last_requested_command",
    "last_successful_disable_dispatch",
    "last_successful_enable_dispatch",
    "measurement_age",
    "measurement_maximum_age",
    "measurement_stale_deadline",
    "measurement_stale_remaining",
    "measurement_status",
    "latest_input_status",
    "minimum_heating_off_time",
    "minimum_heating_on_time",
    "minimum_off_deadline",
    "minimum_on_deadline",
    "operational_summary",
    "raw_heat_demand",
    "lockout_remaining",
    "runtime_status",
    "safety_state",
    "sensor_failure_grace_period",
    "source_control_state",
    "source_control_summary",
    "shadow_pipeline_health",
    "target_temperature",
    "timeout_action",
}
EXPECTED_BINARY_SENSOR_KEYS = {
    "fatal_failure",
    "heat_required",
    "measurement_valid",
    "recoverable_failure",
    "runtime_active",
    "safety_bypassed_lockout",
    "emergency_disable_attempted",
}
PRIMARY_KEYS = {
    "current_temperature",
    "heat_demand",
    "heat_demand_confirmation_duration",
    "heat_demand_confirmation_state",
    "confirmed_zone_heat_demand",
    "heating_disable_threshold",
    "heating_enable_threshold",
    "heating_turn_off_differential",
    "heating_turn_on_differential",
    "hysteresis_demand",
    "operational_summary",
    "raw_heat_demand",
    "safety_state",
    "target_temperature",
}


def _key(entry_id: str, unique_id: str) -> str:
    return unique_id.removeprefix(f"{entry_id}_")


async def _setup_entry(hass, entry_data) -> MockConfigEntry:
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_core_version_metadata_lookup_runs_off_loop_and_reaches_publication(
    hass,
    entry_data,
    service_calls,
) -> None:
    loop_thread = get_ident()
    lookup_threads: list[int] = []
    executor_submissions: list[tuple[object, tuple[object, ...]]] = []

    def installed_version(distribution: str) -> str:
        assert distribution == "controlel"
        lookup_threads.append(get_ident())
        return "0.6.0-executor-test"

    async def run_in_executor(target, *args):
        executor_submissions.append((target, args))
        return await asyncio.to_thread(target, *args)

    with (
        patch.object(component.metadata, "version", side_effect=installed_version) as lookup_mock,
        patch.object(hass, "async_add_executor_job", side_effect=run_in_executor),
    ):
        entry = await _setup_entry(hass, entry_data)

    metadata_submissions = [args for target, args in executor_submissions if target is lookup_mock]
    assert metadata_submissions == [("controlel",)]
    assert len(lookup_threads) == 1
    assert lookup_threads[0] != loop_thread
    host = entry.runtime_data.host
    assert host is not None
    assert host.snapshot_source.current.core_version == "0.6.0-executor-test"
    registry = er.async_get(hass)
    core_version = next(
        item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.unique_id.endswith("_core_version")
    )
    assert hass.states.get(core_version.entity_id).state == "0.6.0-executor-test"
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["versions"]["core"] == "0.6.0-executor-test"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_snapshot_publication_is_loop_safe_coalesced_and_invalidated_on_unload(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry = await _setup_entry(hass, entry_data)
    host = entry.runtime_data.host
    assert host is not None
    loop_thread = get_ident()
    publication_threads: list[int] = []

    def record_publication(entity) -> None:
        publication_threads.append(get_ident())

    with patch.object(ControlelSnapshotEntity, "async_write_ha_state", record_publication):
        host.snapshot_source.refresh_elapsed(datetime.now(UTC))
        assert publication_threads
        assert set(publication_threads) == {loop_thread}

        publication_threads.clear()
        await asyncio.to_thread(host.snapshot_source.refresh_elapsed, datetime.now(UTC))
        await hass.async_block_till_done()
        single_refresh_count = len(publication_threads)
        assert single_refresh_count > 0
        assert set(publication_threads) == {loop_thread}

        publication_threads.clear()

        def burst() -> None:
            for _ in range(25):
                host.snapshot_source.refresh_elapsed(datetime.now(UTC))

        worker = Thread(target=burst)
        worker.start()
        worker.join()
        await hass.async_block_till_done()
        assert len(publication_threads) == single_refresh_count
        assert set(publication_threads) == {loop_thread}

        stale_callbacks = tuple(item[0] for item in host.snapshot_source._subscribers.values())
        assert await hass.config_entries.async_unload(entry.entry_id)
        publication_threads.clear()
        await asyncio.to_thread(lambda: [callback(host.snapshot_source.current) for callback in stale_callbacks])
        await hass.async_block_till_done()
        assert publication_threads == []


async def test_device_entities_states_unique_ids_and_unload(
    hass,
    entry_data,
    expected_framework_core_version,
    service_calls,
) -> None:
    entry = await _setup_entry(hass, entry_data)
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    by_key = {_key(entry.entry_id, item.unique_id): item for item in entries}

    assert set(by_key) == EXPECTED_SENSOR_KEYS | EXPECTED_BINARY_SENSOR_KEYS
    assert len(entries) == len(EXPECTED_SENSOR_KEYS | EXPECTED_BINARY_SENSOR_KEYS)
    assert {item.platform for item in entries} == {DOMAIN}
    assert {item.unique_id for item in entries} == {f"{entry.entry_id}_{key}" for key in by_key}
    assert {key for key, item in by_key.items() if item.entity_category is None} == PRIMARY_KEYS
    assert all(
        item.entity_category is EntityCategory.DIAGNOSTIC for key, item in by_key.items() if key not in PRIMARY_KEYS
    )
    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass),
        entry.entry_id,
    )
    assert len(devices) == 1
    assert devices[0].identifiers == {(DOMAIN, entry.entry_id)}
    assert devices[0].name == "Controlel — Living room"
    assert isinstance(devices[0].sw_version, str)

    assert hass.states.get(by_key["current_temperature"].entity_id).state == "20.0"
    assert hass.states.get(by_key["target_temperature"].entity_id).state == "21.0"
    assert hass.states.get(by_key["measurement_status"].entity_id).state == "valid"
    assert hass.states.get(by_key["heat_demand"].entity_id).state == "heat_required"
    assert hass.states.get(by_key["heat_required"].entity_id).state == "on"
    assert hass.states.get(by_key["runtime_active"].entity_id).state == "on"
    assert hass.states.get(by_key["integration_version"].entity_id).state == "0.10.1"
    assert hass.states.get(by_key["core_version"].entity_id).state == expected_framework_core_version
    assert hass.states.get(by_key["diagnostic_profile"].entity_id).state == (DIAGNOSTIC_PROFILE_DETAILED)
    assert hass.states.get(by_key["grace_remaining"].entity_id).state == "unavailable"
    assert hass.states.get(by_key["grace_deadline"].entity_id).state == "unavailable"
    assert hass.states.get(by_key["heating_performance_living_room"].entity_id).state in {
        "observing",
        "assessment_pending",
        "assessed",
    }
    assert hass.states.get(by_key["shadow_pipeline_health"].entity_id).state in {
        "healthy",
        "pending",
    }

    entity_ids = [item.entity_id for item in entries]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert all(hass.states.get(entity_id).state == "unavailable" for entity_id in entity_ids)
    assert not hasattr(entry, "runtime_data")


async def test_binary_entities_keep_raw_states_and_use_yes_no_entity_translations(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry = await _setup_entry(hass, entry_data)
    registry = er.async_get(hass)
    binary_entries = {
        _key(entry.entry_id, item.unique_id): item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == "binary_sensor"
    }
    expected_unique_ids = {f"{entry.entry_id}_{key}" for key in EXPECTED_BINARY_SENSOR_KEYS}
    assert set(binary_entries) == EXPECTED_BINARY_SENSOR_KEYS
    assert {item.unique_id for item in binary_entries.values()} == expected_unique_ids
    assert {hass.states.get(item.entity_id).state for item in binary_entries.values()} <= {"on", "off"}

    resources = await translation.async_get_translations(hass, "en", "entity", {DOMAIN})
    for key in EXPECTED_BINARY_SENSOR_KEYS:
        prefix = f"component.{DOMAIN}.entity.binary_sensor.{key}.state"
        assert resources[f"{prefix}.on"] == "Yes"
        assert resources[f"{prefix}.off"] == "No"
        assert (
            translation.async_translate_state(
                hass,
                "on",
                "binary_sensor",
                DOMAIN,
                key,
                None,
            )
            == "Yes"
        )
        assert (
            translation.async_translate_state(
                hass,
                "off",
                "binary_sensor",
                DOMAIN,
                key,
                None,
            )
            == "No"
        )

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reload_rename_and_target_change_keep_one_stable_entity_set(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry = await _setup_entry(hass, entry_data)
    registry = er.async_get(hass)
    original = {item.unique_id: item.entity_id for item in er.async_entries_for_config_entry(registry, entry.entry_id)}
    expected_unique_ids = {f"{entry.entry_id}_{key}" for key in EXPECTED_SENSOR_KEYS | EXPECTED_BINARY_SENSOR_KEYS}
    assert set(original) == expected_unique_ids
    performance_attributes = {}

    for profile in (
        DIAGNOSTIC_PROFILE_DETAILED,
        DIAGNOSTIC_PROFILE_DEBUG,
        DIAGNOSTIC_PROFILE_BASIC,
    ):
        hass.config_entries.async_update_entry(
            entry,
            options={
                CONF_DIAGNOSTIC_PROFILE: profile,
                CONF_ZONE_NAME: "Upstairs",
                CONF_TARGET_TEMPERATURE: 22.5,
            },
        )
        await hass.async_block_till_done()
        current_entries = er.async_entries_for_config_entry(registry, entry.entry_id)
        assert {item.unique_id: item.entity_id for item in current_entries} == original
        assert len(current_entries) == len(expected_unique_ids)
        performance = next(
            item for item in current_entries if item.unique_id.endswith("_heating_performance_living_room")
        )
        performance_attributes[profile] = dict(hass.states.get(performance.entity_id).attributes)

    assert "temperature_evidence" not in performance_attributes[DIAGNOSTIC_PROFILE_BASIC]
    assert "temperature_evidence" in performance_attributes[DIAGNOSTIC_PROFILE_DETAILED]
    assert performance_attributes[DIAGNOSTIC_PROFILE_DEBUG].keys() == (
        performance_attributes[DIAGNOSTIC_PROFILE_DETAILED].keys()
    )
    assert all(len(json.dumps(attributes)) < 65_536 for attributes in performance_attributes.values())

    current_entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    target = next(item for item in current_entries if item.unique_id.endswith("_target_temperature"))
    assert hass.states.get(target.entity_id).state == "22.5"
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    assert devices[0].name == "Controlel — Upstairs"
    assert service_calls == []
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_legacy_effective_profile_survives_unload_and_restart(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry = await _setup_entry(hass, entry_data)
    assert CONF_DIAGNOSTIC_PROFILE not in entry.data
    assert CONF_DIAGNOSTIC_PROFILE not in entry.options
    registry = er.async_get(hass)
    profile = next(
        item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.unique_id.endswith("_diagnostic_profile")
    )
    assert hass.states.get(profile.entity_id).state == DIAGNOSTIC_PROFILE_DETAILED
    before_reload = (await async_get_config_entry_diagnostics(hass, entry))["operational_events"]
    assert before_reload["events"][0]["event_id"] == "event:00000001"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(profile.entity_id).state == DIAGNOSTIC_PROFILE_DETAILED
    after_reload = (await async_get_config_entry_diagnostics(hass, entry))["operational_events"]
    assert after_reload["events"][0]["event_id"] == "event:00000001"
    assert after_reload["total_emitted"] == len(after_reload["events"])
    assert CONF_DIAGNOSTIC_PROFILE not in entry.data
    assert CONF_DIAGNOSTIC_PROFILE not in entry.options
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_debug_presentation_refresh_does_not_emit_operational_events(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry_data[CONF_DIAGNOSTIC_PROFILE] = DIAGNOSTIC_PROFILE_DEBUG
    entry = await _setup_entry(hass, entry_data)
    host = entry.runtime_data.host
    assert host is not None
    before = host.operational_event_diagnostics()

    host.snapshot_source.refresh_elapsed(datetime.now(UTC) + timedelta(seconds=1))

    assert host.operational_event_diagnostics() == before
    assert service_calls == []
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unknown_measurement_and_valid_recovery_update_entities(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry = await _setup_entry(hass, entry_data)
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    by_key = {_key(entry.entry_id, item.unique_id): item.entity_id for item in entries}

    hass.states.async_set(entry_data[CONF_TEMPERATURE_ENTITY_ID], "unknown")
    await hass.async_block_till_done()
    assert hass.states.get(by_key["measurement_status"]).state == "unknown"
    assert hass.states.get(by_key["measurement_valid"]).state == "off"
    assert hass.states.get(by_key["current_temperature"]).state == "unknown"

    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "22",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    await hass.async_block_till_done()
    assert hass.states.get(by_key["measurement_status"]).state == "valid"
    assert hass.states.get(by_key["measurement_valid"]).state == "on"
    assert hass.states.get(by_key["current_temperature"]).state == "22.0"
    assert hass.states.get(by_key["heat_demand"]).state == "no_heat_required"
    assert hass.states.get(by_key["heat_required"]).state == "off"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_hysteresis_hold_and_minimum_on_deferred_command_are_visible(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry_data.update(
        {
            CONF_TARGET_TEMPERATURE: 22.0,
            CONF_HEATING_TURN_ON_DIFFERENTIAL: 0.3,
            CONF_HEATING_TURN_OFF_DIFFERENTIAL: 0.1,
            CONF_MINIMUM_HEATING_ON_TIME: 120.0,
            CONF_MINIMUM_HEATING_OFF_TIME: 60.0,
        }
    )
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "21.5",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    hass.states.async_set("switch.boiler", "unavailable")
    clock = MutableClock(datetime.now(UTC) + timedelta(seconds=1))
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data=entry_data)
    entry.add_to_hass(hass)

    with patch.object(component, "SystemClock", return_value=clock):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        host = entry.runtime_data.host
        assert host is not None
        assert service_calls == []
        clock.current += timedelta(seconds=30)
        await host.async_reevaluate()
        await hass.async_block_till_done()
        assert [service for service, _ in service_calls] == ["turn_on"]

        clock.current += timedelta(seconds=60)
        hass.states.async_set(
            entry_data[CONF_TEMPERATURE_ENTITY_ID],
            "22.0",
            {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
        )
        await hass.async_block_till_done()
        held = host.snapshot_source.current
        assert held.raw_zone_heat_demand.value == "no_heat_required"
        assert held.hysteresis_demand.value == "heat_required"
        assert held.demand_reason.value == "preserved_previous_demand"
        assert held.confirmation_reason == "heat_demand_confirmation_bypassed_zero_duration"
        assert [service for service, _ in service_calls] == ["turn_on"]

        clock.current += timedelta(seconds=10)
        hass.states.async_set(
            entry_data[CONF_TEMPERATURE_ENTITY_ID],
            "22.1",
            {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
        )
        await hass.async_block_till_done()
        deferred = host.snapshot_source.current
        assert deferred.hysteresis_demand.value == "no_heat_required"
        assert deferred.source_control_state.value == "heating_not_requested_waiting_minimum_on"
        assert deferred.active_lockout_type.value == "minimum_on"
        assert deferred.deferred_command == "disable_heating"
        assert deferred.active_lockout_deadline == deferred.deferred_deadline
        assert deferred.deferred_since is not None
        assert deferred.active_lockout_remaining_seconds == deferred.deferred_remaining_seconds
        assert deferred.lockout_remaining_seconds is not None
        assert deferred.active_lockout_deadline is not None
        assert 0 < (deferred.active_lockout_deadline - clock.current).total_seconds() <= 121

        clock.current = deferred.active_lockout_deadline
        await host.async_reevaluate()
        await hass.async_block_till_done()
        assert [service for service, _ in service_calls] == ["turn_on", "turn_off"]
        assert host.snapshot_source.current.deferred_command is None
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_stale_timeout_duplicate_suppression_and_recovery_are_truthful(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry_data[CONF_PRIMARY_MEASUREMENT_MAX_AGE] = 0.5
    entry_data[CONF_INDETERMINATE_GRACE_PERIOD] = 0.0
    entry = await _setup_entry(hass, entry_data)
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    by_key = {_key(entry.entry_id, item.unique_id): item.entity_id for item in entries}
    host = entry.runtime_data.host
    assert host is not None
    initial_suppressions = host.snapshot_source.current.duplicate_commands_suppressed

    async with asyncio.timeout(2):
        while host.snapshot_source.current.safety_state is not SafetyState.TIMEOUT_ACTION_APPLIED:
            await asyncio.sleep(0.01)
    await host.async_reevaluate()
    await hass.async_block_till_done()

    assert hass.states.get(by_key["measurement_status"]).state == "stale"
    assert hass.states.get(by_key["heat_demand"]).state == "indeterminate"
    assert hass.states.get(by_key["safety_state"]).state == "timeout_action_applied"
    assert hass.states.get(by_key["last_requested_command"]).state == "disable_heating"
    assert hass.states.get(by_key["last_command_outcome"]).state == "suppressed"
    assert int(hass.states.get(by_key["duplicate_commands_suppressed"]).state) == (initial_suppressions + 1)

    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "19",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    await hass.async_block_till_done()

    assert host.snapshot_source.current.safety_state is SafetyState.NORMAL
    assert host.snapshot_source.current.grace_deadline is None
    assert hass.states.get(by_key["measurement_status"]).state == "valid"
    assert hass.states.get(by_key["heat_demand"]).state == "heat_required"
    assert hass.states.get(by_key["safety_state"]).state == "normal"
    assert hass.states.get(by_key["last_command_outcome"]).state == "held"
    assert host.snapshot_source.current.deferred_command is None
    assert service_calls == []
    assert await hass.config_entries.async_unload(entry.entry_id)


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


async def test_exact_sixty_second_safety_sequence_is_visible_in_diagnostics(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry_data[CONF_TARGET_TEMPERATURE] = 23.0
    entry_data[CONF_PRIMARY_MEASUREMENT_MAX_AGE] = 60.0
    entry_data[CONF_INDETERMINATE_GRACE_PERIOD] = 60.0
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "24",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    clock = MutableClock(datetime.now(UTC) + timedelta(seconds=1))
    entry = MockConfigEntry(domain=DOMAIN, title="Living room", data=entry_data)
    entry.add_to_hass(hass)

    with patch.object(component, "SystemClock", return_value=clock):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        host = entry.runtime_data.host
        assert host is not None
        initial_suppressions = host.snapshot_source.current.duplicate_commands_suppressed
        measurement_timestamp = host.snapshot_source.current.measurement_timestamp
        assert measurement_timestamp is not None
        clock.current = measurement_timestamp + timedelta(seconds=60) + datetime.resolution

        await host.async_reevaluate()
        grace_snapshot = host.snapshot_source.snapshot_at(clock.current)
        assert grace_snapshot.measurement_status.value == "stale"
        assert grace_snapshot.safety_state is SafetyState.INDETERMINATE_GRACE
        assert grace_snapshot.grace_deadline == clock.current + timedelta(seconds=60)
        assert grace_snapshot.grace_remaining_seconds == 60.0

        clock.current = grace_snapshot.grace_deadline
        await host.async_reevaluate()
        await hass.async_block_till_done()
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)

        effective = diagnostics["configuration_provenance"]["effective_normalized_values"]
        snapshot = diagnostics["operational_snapshot"]
        assert effective["target_temperature"] == 23.0
        assert effective["primary_measurement_max_age_seconds"] == 60.0
        assert effective["indeterminate_grace_period_seconds"] == 60.0
        assert snapshot["measurement_status"] == "stale"
        assert snapshot["zone_heat_demand"] == "indeterminate"
        assert snapshot["safety_state"] == "timeout_action_applied"
        assert snapshot["last_requested_command"] == "disable_heating"
        assert snapshot["last_command_outcome"] == "suppressed"
        assert diagnostics["counters"]["duplicate_commands_suppressed"] == initial_suppressions
        assert service_calls == []
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_diagnostics_are_allowlisted_json_safe_and_redact_unknown_entry_data(
    hass,
    entry_data,
    expected_framework_core_version,
    service_calls,
) -> None:
    entry_data["password"] = "must-not-appear"
    entry_data["token"] = "must-not-appear"
    entry = await _setup_entry(hass, entry_data)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    serialized = json.dumps(diagnostics, sort_keys=True)

    assert diagnostics["versions"] == {
        "integration": "0.10.1",
        "core": expected_framework_core_version,
    }
    assert diagnostics["operational_snapshot"]["runtime_status"] == "active"
    assert diagnostics["operational_snapshot"]["safety_state"] == "normal"
    assert {
        "source_control_state",
        "source_control_summary",
        "earliest_next_enable_time",
        "earliest_next_disable_time",
        "active_lockout_type",
        "active_lockout_deadline",
        "active_lockout_remaining_seconds",
        "deferred_command",
        "deferred_reason",
        "deferred_since",
        "deferred_deadline",
        "deferred_remaining_seconds",
        "last_successful_enable_dispatch",
        "last_successful_disable_dispatch",
    } <= diagnostics["operational_snapshot"].keys()
    assert len(diagnostics["entity_ids"]) == len(EXPECTED_SENSOR_KEYS | EXPECTED_BINARY_SENSOR_KEYS)
    assert diagnostics["decision_trace"]
    assert "decision_code" in diagnostics["decision_trace"][0]
    assert diagnostics["heating_diagnostics"]["schema_version"] == 1
    assert len(diagnostics["heating_diagnostics"]["zones"]) == 1
    assert len(json.dumps(diagnostics["heating_diagnostics"])) < 65_536
    assert diagnostics["runtime_supervision"]["supervisor_state"] == "normal"
    assert diagnostics["runtime_supervision"]["command_authority"] == "normal"
    assert diagnostics["runtime_supervision"]["reported_source_state"] == "disabled"
    assert diagnostics["source_resilience"]["schema_version"] == 1
    assert diagnostics["source_resilience"]["source_ownership"] == "controlel_owned"
    assert diagnostics["source_resilience"]["reported_source_state"] == "disabled"
    operational_events = diagnostics["operational_events"]
    assert operational_events["schema_version"] == 1
    assert operational_events["capacity"] == 200
    assert operational_events["retained_count"] <= operational_events["capacity"]
    assert operational_events["total_emitted"] == (
        operational_events["retained_count"] + operational_events["dropped_count"]
    )
    assert operational_events["events"]
    assert "event_code" in operational_events["events"][0]
    assert "decision_code" not in operational_events["events"][0]
    assert diagnostics["counters"]["operational_event_records"] == operational_events["retained_count"]
    assert json.loads(json.dumps(operational_events, sort_keys=True)) == operational_events
    notification_policy = diagnostics["notification_policy"]
    assert notification_policy["schema_version"] == 1
    assert notification_policy["enabled"] is False
    assert notification_policy["configured_recipient_count"] == 0
    assert notification_policy["recipients"] == []
    assert notification_policy["source_total_observed"] >= 0
    assert notification_policy["source_last_processed_sequence"] >= 0
    assert notification_policy["source_events_missed"] == 0
    assert notification_policy["source_overflow_occurrences"] == 0
    assert notification_policy["total_intents_produced"] == 0
    assert json.loads(json.dumps(notification_policy, sort_keys=True)) == notification_policy
    assert diagnostics["active_issue_ids"] == []
    provenance = diagnostics["configuration_provenance"]
    assert diagnostics["configuration"]["diagnostic_profile"] == (DIAGNOSTIC_PROFILE_DETAILED)
    assert provenance["legacy_data_values"][CONF_TARGET_TEMPERATURE] == 21.0
    assert CONF_HEAT_DEMAND_CONFIRMATION_DURATION not in provenance["legacy_data_values"]
    assert provenance["effective_normalized_values"]["heat_demand_confirmation_duration_seconds"] == 0.0
    assert provenance["mutable_options_values"] == {}
    assert provenance["effective_normalized_values"] == diagnostics["configuration"]
    assert provenance["user_facing_timing_values"] == {
        "primary_measurement_max_age_minutes": {
            "value": 5.0,
            "unit": "minutes",
        },
        "max_future_skew_seconds": {
            "value": 5.0,
            "unit": "seconds",
        },
        "indeterminate_grace_period_minutes": {
            "value": 1.0,
            "unit": "minutes",
        },
        "minimum_heating_on_time_minutes": {
            "value": 0.0,
            "unit": "minutes",
        },
        "minimum_heating_off_time_minutes": {
            "value": 0.0,
            "unit": "minutes",
        },
        "heat_demand_confirmation_duration_minutes": {
            "value": 0.0,
            "unit": "minutes",
        },
        "debug_duration_minutes": {
            "value": 60.0,
            "unit": "minutes",
        },
    }
    assert set(provenance["precedence_source"].values()) == {
        "config_entry.data",
        "legacy_compatibility_default",
        "new_entry_default",
    }
    assert provenance["precedence_source"][CONF_DIAGNOSTIC_PROFILE] == ("legacy_compatibility_default")
    assert provenance["precedence_source"][CONF_HEAT_DEMAND_CONFIRMATION_DURATION] == "legacy_compatibility_default"
    assert "must-not-appear" not in serialized
    assert "password" not in serialized
    assert "token" not in serialized
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_diagnostics_report_mixed_data_options_precedence(
    hass,
    entry_data,
    service_calls,
) -> None:
    entry_data[CONF_HEAT_DEMAND_CONFIRMATION_DURATION] = 120.0
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Living room",
        data=entry_data,
        options={
            CONF_DIAGNOSTIC_PROFILE: DIAGNOSTIC_PROFILE_BASIC,
            CONF_TARGET_TEMPERATURE: 22.5,
            CONF_PRIMARY_MEASUREMENT_MAX_AGE: 90.0,
            CONF_HEAT_DEMAND_CONFIRMATION_DURATION: 45.0,
        },
    )
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "20",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    provenance = diagnostics["configuration_provenance"]

    assert provenance["legacy_data_values"][CONF_TARGET_TEMPERATURE] == 21.0
    assert provenance["legacy_data_values"][CONF_HEAT_DEMAND_CONFIRMATION_DURATION] == 120.0
    assert provenance["mutable_options_values"] == {
        CONF_DIAGNOSTIC_PROFILE: DIAGNOSTIC_PROFILE_BASIC,
        CONF_TARGET_TEMPERATURE: 22.5,
        CONF_PRIMARY_MEASUREMENT_MAX_AGE: 90.0,
        CONF_HEAT_DEMAND_CONFIRMATION_DURATION: 45.0,
    }
    assert provenance["effective_normalized_values"]["target_temperature"] == 22.5
    assert provenance["effective_normalized_values"]["primary_measurement_max_age_seconds"] == 90.0
    assert provenance["effective_normalized_values"]["diagnostic_profile"] == (DIAGNOSTIC_PROFILE_BASIC)
    assert provenance["effective_normalized_values"]["heat_demand_confirmation_duration_seconds"] == 45.0
    assert provenance["precedence_source"][CONF_TARGET_TEMPERATURE] == ("config_entry.options")
    assert provenance["precedence_source"][CONF_PRIMARY_MEASUREMENT_MAX_AGE] == ("config_entry.options")
    assert provenance["precedence_source"][CONF_DIAGNOSTIC_PROFILE] == ("config_entry.options")
    assert provenance["precedence_source"][CONF_HEAT_DEMAND_CONFIRMATION_DURATION] == ("config_entry.options")
    assert provenance["precedence_source"][CONF_INDETERMINATE_GRACE_PERIOD] == ("config_entry.data")
    assert await hass.config_entries.async_unload(entry.entry_id)
