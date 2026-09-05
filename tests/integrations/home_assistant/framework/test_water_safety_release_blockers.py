"""Release blockers: startup acquisition, missing state, stable identity and evidence."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers import entity_registry as er

from controlel.application.setup import ActiveReference
from controlel.domain.water_safety import MoistureCondition, WaterSafetyAssessmentStatus, WaterSafetyState
from controlel.infrastructure.home_assistant import ACTIVE_REFERENCE_KEY
from controlel.infrastructure.home_assistant.water_safety_discovery import async_snapshot_with_notify_services
from custom_components.controlel import water_safety_activation as activation
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.scheduler import HomeAssistantScheduler
from custom_components.controlel.water_safety_host import build_water_safety_host
from tests.integrations.home_assistant.test_water_safety_integration import (
    RecordingEvidence,
    RecordingState,
    _draft,
    _effective,
)

SENSOR = "binary_sensor.utility_moisture"


def _host(hass, effective=None):
    bridge = HomeAssistantEventLoopBridge(hass.loop)
    host = build_water_safety_host(
        hass,
        effective or _effective()[0],
        bridge=bridge,
        scheduler=HomeAssistantScheduler(
            hass=hass, bridge=bridge, submit_runtime_callback=lambda callback: host.submit_scheduled_callback(callback)
        ),
        state_store=RecordingState(),
        evidence_store=RecordingEvidence(),
        logger=logging.getLogger(__name__),
    )
    return host


@pytest.mark.parametrize("returns_dry", [False, True])
async def test_wet_transition_during_initialization_is_not_lost(hass, monkeypatch, returns_dry):
    hass.states.async_set(SENSOR, "off")
    await hass.async_block_till_done()
    host = _host(hass)
    entered = asyncio.Event()
    release = asyncio.Event()
    original_submit = host._async_submit_runtime
    first = True

    async def hold_start(operation, *args):
        nonlocal first
        if first:
            first = False
            entered.set()
            await release.wait()
        return await original_submit(operation, *args)

    monkeypatch.setattr(host, "_async_submit_runtime", hold_start)
    initializing = asyncio.create_task(host.async_initialize())
    try:
        await entered.wait()
        hass.states.async_set(SENSOR, "on")
        await hass.async_block_till_done()
        if returns_dry:
            hass.states.async_set(SENSOR, "off")
            await hass.async_block_till_done()
        release.set()
        await initializing
        await hass.async_block_till_done()
        if returns_dry:
            assert host.runtime.snapshot.last_incident is not None
            assert host.runtime.state is WaterSafetyState.OK
        else:
            assert host.runtime.state is WaterSafetyState.WET
            assert host.runtime.snapshot.active_incident is not None
    finally:
        release.set()
        await initializing
        await host.async_stop()


async def test_configured_state_disappearance_enters_unknown_grace(hass):
    hass.states.async_set(SENSOR, "off")
    await hass.async_block_till_done()
    host = _host(hass)
    try:
        await host.async_initialize()
        assert host.runtime.snapshot.latest_observation.condition is MoistureCondition.DRY
        hass.states.async_remove(SENSOR)
        await hass.async_block_till_done()
        snapshot = host.runtime.snapshot
        assert snapshot.latest_observation.condition is MoistureCondition.UNKNOWN
        assert snapshot.assessment_status is WaterSafetyAssessmentStatus.INDETERMINATE_GRACE
        assert snapshot.last_confirmed_observation.condition is MoistureCondition.DRY
        assert snapshot.fault_deadline == snapshot.unavailable_since + timedelta(seconds=30)
        assert host.runtime.next_deadline == snapshot.fault_deadline
        assert host._deadline_handle is not None
    finally:
        await host.async_stop()


async def _active_entry(hass, monkeypatch):
    registry = er.async_get(hass)
    for domain, unique_id, object_id in (
        ("binary_sensor", "moisture", "utility_moisture"),
        ("switch", "siren", "hall_siren"),
        ("valve", "main-valve", "utility_water_main"),
    ):
        registry.async_get_or_create(domain, "test", unique_id, suggested_object_id=object_id)
    hass.services.async_register("notify", "mobile_app_phone", lambda call: None)
    hass.states.async_set(SENSOR, "off")
    snapshot = await async_snapshot_with_notify_services(
        hass, snapshot_id="before-rename", captured_at=datetime.now(UTC)
    )
    by_locator = {ref.current_locator: ref for ref in snapshot.objects}
    draft = _draft(shutoff_valves=True)
    draft = draft.model_copy(
        update={
            "environment_id": snapshot.provider_instance_id,
            "bindings": tuple(
                binding.model_copy(update={"reference": by_locator[binding.reference.current_locator]})
                for binding in draft.bindings
            ),
        }
    )
    # Canonicalize with the real HA instance identity, as the setup backend does.
    from controlel.application.configuration.water_safety_setup_adapter import WaterSafetySetupAdapter

    adapter = WaterSafetySetupAdapter()
    report = adapter.validate(draft, report_id="report", evaluated_at=datetime.now(UTC))
    canonical = adapter.canonicalize(
        draft,
        report,
        configuration_id="water-config",
        revision_id="water-revision",
        revision=1,
        provider="home_assistant",
        provider_instance_id=snapshot.provider_instance_id,
        created_at=datetime.now(UTC),
        actor="test",
        source="test",
        change_kind="CREATE",
        reason="test",
        core_version="0.17.0",
    )
    active = ActiveReference(
        environment_id=canonical.environment_id,
        module_key=canonical.module_key,
        module_instance_id=canonical.module_instance_id,
        canonical_revision_id=canonical.revision_id,
        semantic_configuration_fingerprint=canonical.semantic_configuration_fingerprint,
        generation=1,
        committing_operation_id="activate",
    )
    entry = SimpleNamespace(entry_id="water-blockers", data={ACTIVE_REFERENCE_KEY: active.model_dump(mode="json")})
    backend = SimpleNamespace(repository=SimpleNamespace(get_canonical_revision=AsyncMock(return_value=canonical)))
    monkeypatch.setattr(activation, "async_get_setup_backend", AsyncMock(return_value=backend))
    return entry, canonical


async def test_restart_resolves_renamed_registry_identity_before_subscription(hass, monkeypatch):
    entry, canonical = await _active_entry(hass, monkeypatch)
    service = activation.WaterSafetyActivationService()
    bridge = HomeAssistantEventLoopBridge(hass.loop)
    host = await service.async_start_from_active_reference(hass, entry, bridge=bridge)
    await host.async_stop()
    renamed = "binary_sensor.renamed_moisture"
    old_id = er.async_get(hass).async_get(SENSOR).id
    er.async_get(hass).async_update_entity(SENSOR, new_entity_id=renamed)
    hass.states.async_remove(SENSOR)
    hass.states.async_set(renamed, "off")
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(renamed).id == old_id
    host = await service.async_start_from_active_reference(hass, entry, bridge=bridge)
    try:
        hass.states.async_set(renamed, "on")
        await hass.async_block_till_done()
        assert host.runtime.state is WaterSafetyState.WET
        assert host.runtime.snapshot.active_incident is not None
        assert host._mapper.entity_id == renamed
        assert any(binding.reference.current_locator == SENSOR for binding in canonical.bindings)
    finally:
        await host.async_stop()


@pytest.mark.parametrize("status", ["MISSING", "AMBIGUOUS"])
async def test_restart_with_unresolved_stable_identity_fails_explicitly(hass, monkeypatch, status):
    entry, canonical = await _active_entry(hass, monkeypatch)
    er.async_get(hass).async_remove(SENSOR)
    if status == "AMBIGUOUS":
        snapshot = await async_snapshot_with_notify_services(
            hass,
            snapshot_id="ambiguous",
            captured_at=datetime.now(UTC),
        )
        sensor = next(
            binding.reference for binding in canonical.bindings if binding.reference.current_locator == SENSOR
        )
        candidates = tuple(
            sensor.model_copy(
                update={
                    "native_id": f"replacement-{index}",
                    "current_locator": f"binary_sensor.replacement_{index}",
                }
            )
            for index in range(2)
        )
        snapshot = snapshot.model_copy(update={"objects": (*snapshot.objects, *candidates)})
        monkeypatch.setattr(activation, "async_snapshot_with_notify_services", AsyncMock(return_value=snapshot))
    service = activation.WaterSafetyActivationService()
    build = AsyncMock()
    monkeypatch.setattr(service, "_async_build_and_start_host", build)
    with pytest.raises(ValueError, match=f"water_safety.moisture_sensor.*{status}"):
        await service.async_start_from_active_reference(hass, entry, bridge=HomeAssistantEventLoopBridge(hass.loop))
    build.assert_not_awaited()


async def test_history_store_failure_during_wet_keeps_real_ha_outputs_isolated(hass, monkeypatch, caplog):
    from homeassistant.exceptions import HomeAssistantError

    from controlel.application.water_safety import WaterOutputOutcome

    entry, _ = await _active_entry(hass, monkeypatch)
    calls = []

    async def output(call):
        calls.append((call.domain, call.service))
        if call.domain == "valve":
            raise HomeAssistantError("valve request failed")

    for domain, service in (
        ("valve", "close_valve"),
        ("switch", "turn_on"),
        ("switch", "turn_off"),
        ("notify", "mobile_app_phone"),
    ):
        hass.services.async_register(domain, service, output)
    hass.states.async_set("valve.utility_water_main", "open")
    hass.states.async_set("switch.hall_siren", "off")
    host = await activation.WaterSafetyActivationService().async_start_from_active_reference(
        hass,
        entry,
        bridge=HomeAssistantEventLoopBridge(hass.loop),
    )
    evidence_store = host.runtime._evidence_port
    before = await evidence_store.async_load_events()
    save = AsyncMock(side_effect=OSError("history storage unavailable"))
    monkeypatch.setattr(evidence_store._store, "async_save", save)
    try:
        hass.states.async_set(SENSOR, "on")
        await hass.async_block_till_done()
        snapshot = host.runtime.snapshot
        assert snapshot.state is WaterSafetyState.WET
        assert snapshot.active_incident is not None
        assert await host.runtime._state_port.async_load_snapshot() == snapshot
        assert calls == [("valve", "close_valve"), ("switch", "turn_on"), ("notify", "mobile_app_phone")]
        assert any(item.last_command_outcome is WaterOutputOutcome.FAILED for item in host.runtime.owned_outputs())
        assert await evidence_store.async_load_events() == before
        assert save.await_count >= 5
        assert "Water Safety evidence persistence failed" in caplog.text
        assert "history storage unavailable" in caplog.text
        hass.states.async_set(SENSOR, "off")
        await hass.async_block_till_done()
        assert host.runtime.snapshot.active_incident is None
        calls.clear()
        hass.states.async_set(SENSOR, "on")
        await hass.async_block_till_done()
        assert host.runtime.snapshot.active_incident.incident_id != snapshot.active_incident.incident_id
        assert calls == [("valve", "close_valve"), ("switch", "turn_on"), ("notify", "mobile_app_phone")]
        assert hass.states.get("valve.utility_water_main").state == "open"
    finally:
        await host.async_stop()


@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_or_cancelled_start_removes_early_subscription(hass, monkeypatch, cancelled):
    hass.states.async_set(SENSOR, "off")
    await hass.async_block_till_done()
    host = _host(hass)
    original_subscribe = host._state_subscriber
    unsubscribed = []

    def subscribe(hass, entity_id, listener):
        unsubscribe = original_subscribe(hass, entity_id, listener)

        def stop():
            unsubscribed.append(entity_id)
            unsubscribe()

        return stop

    async def fail(operation, *args):
        if cancelled:
            raise asyncio.CancelledError
        raise RuntimeError("startup failure")

    monkeypatch.setattr(host, "_state_subscriber", subscribe)
    with monkeypatch.context() as startup:
        startup.setattr(host, "_async_submit_runtime", fail)
        with pytest.raises(asyncio.CancelledError if cancelled else RuntimeError):
            await host.async_initialize()
    assert unsubscribed == [SENSOR]
    assert host._unsubscribe is None
    hass.states.async_set(SENSOR, "on")
    await hass.async_block_till_done()
    assert not host._callback_tasks
    await host.async_stop()
