"""Water activation must couple loaded authority, rollback, and crash recovery."""

from datetime import UTC, datetime

import pytest
from homeassistant import data_entry_flow

from controlel.application.setup import ActivationState
from controlel.domain.water_safety import WaterSafetyState
from controlel.infrastructure.home_assistant import active_reference_for_module
from custom_components.controlel.setup_backend import async_get_setup_backend
from tests.integrations.home_assistant.framework.test_config_flow import (
    _choose,
    _empty_entry,
    _open_water_menu,
    _seed_configured_water,
    _water_drafts,
)

SENSOR = "binary_sensor.utility_moisture"


async def _configured(hass):
    entry = await _empty_entry(hass, title="Water activation transaction")
    draft, canonical, active = await _seed_configured_water(hass, entry)
    hass.states.async_set(SENSOR, "off")
    await hass.async_block_till_done()
    assert entry.runtime_data.loaded_water_safety_configuration.canonical_revision_id == active.canonical_revision_id
    return entry, draft, canonical, active


async def _confirmation(hass, entry):
    review = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_validation")
    return await hass.config_entries.options.async_configure(review["flow_id"], {})


@pytest.mark.parametrize("failure", ["false", "exception", "wrong_runtime", "after_unload", "after_setup"])
async def test_final_water_reload_failure_retains_authority_draft_and_retry(hass, monkeypatch, failure):
    entry, draft, _canonical, active = await _configured(hass)
    confirmation = await _confirmation(hass, entry)
    original_reload = hass.config_entries.async_reload
    calls = 0

    async def fail_once(entry_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure == "after_unload":
                assert await hass.config_entries.async_unload(entry_id)
                return False
            if failure == "after_setup":
                assert await original_reload(entry_id)
                assert active_reference_for_module(entry.data, "water_safety") == active
                assert (
                    entry.runtime_data.loaded_water_safety_configuration.canonical_revision_id
                    != active.canonical_revision_id
                )
                return False
            if failure == "exception":
                raise RuntimeError("final HA reload failed")
            return failure == "wrong_runtime"
        return await original_reload(entry_id)

    with monkeypatch.context() as patch:
        patch.setattr(hass.config_entries, "async_reload", fail_once)
        result = await hass.config_entries.options.async_configure(confirmation["flow_id"], {})
        await hass.async_block_till_done()
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "water_safety_activate"
    assert result["errors"] == {"base": "water_safety_activation_failed"}
    assert active_reference_for_module(entry.data, "water_safety") == active
    assert entry.runtime_data.loaded_water_safety_configuration.canonical_revision_id == active.canonical_revision_id
    assert entry.runtime_data.water_safety_host.runtime.snapshot.canonical_revision_id == active.canonical_revision_id
    assert not entry.runtime_data.reloading
    assert (await _water_drafts(hass, entry)) == (draft,)
    backend = await async_get_setup_backend(hass, entry)
    assert await backend.repository.list_non_terminal_attempts() == ()
    hass.states.async_set(SENSOR, "on")
    await hass.async_block_till_done()
    assert entry.runtime_data.water_safety_host.runtime.state is WaterSafetyState.WET
    retried = await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert retried["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    new_active = active_reference_for_module(entry.data, "water_safety")
    assert new_active.canonical_revision_id != active.canonical_revision_id
    assert (
        entry.runtime_data.water_safety_host.runtime.snapshot.canonical_revision_id == new_active.canonical_revision_id
    )
    assert await _water_drafts(hass, entry) == ()
    assert await hass.config_entries.async_reload(entry.entry_id)


async def test_interrupted_water_applying_recovers_previous_monitoring_and_allows_retry(hass):
    entry, draft, canonical, active = await _configured(hass)
    backend = await async_get_setup_backend(hass, entry)
    candidate_data = canonical.model_dump(mode="python")
    candidate_data.update(revision_id="interrupted-water-candidate", revision=2)
    candidate_data.pop("document_hash")
    candidate = type(canonical).model_validate(candidate_data)
    await backend.repository.add_canonical_revision(candidate)
    await backend.activation.prepare(
        candidate.revision_id, attempt_id="interrupted-water", prepared_at=datetime.now(UTC)
    )
    await backend.activation.begin_applying("interrupted-water", applying_at=datetime.now(UTC))
    assert (await backend.repository.get_activation_attempt("interrupted-water")).state is ActivationState.APPLYING
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.data.pop("controlel_setup_backend", None)
    hass.data.pop("controlel_setup_services", None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    restarted_backend = await async_get_setup_backend(hass, entry)
    assert restarted_backend is not backend
    assert active_reference_for_module(entry.data, "water_safety") == active
    assert entry.runtime_data.water_safety_host.runtime.snapshot.canonical_revision_id == active.canonical_revision_id
    hass.states.async_set(SENSOR, "on")
    await hass.async_block_till_done()
    assert entry.runtime_data.water_safety_host.runtime.state is WaterSafetyState.WET
    assert await restarted_backend.repository.list_non_terminal_attempts() == ()
    recovered = await restarted_backend.repository.get_activation_attempt("interrupted-water")
    assert recovered.state is ActivationState.ROLLED_BACK
    assert recovered.interruption_recovered_at is not None
    assert recovered.rollback_runtime_stamp.canonical_revision_id == active.canonical_revision_id
    assert await _water_drafts(hass, entry) == (draft,)
    confirmation = await _confirmation(hass, entry)
    retried = await hass.config_entries.options.async_configure(confirmation["flow_id"], {})
    await hass.async_block_till_done()
    assert retried["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert await restarted_backend.repository.list_non_terminal_attempts() == ()


async def test_failed_water_rollback_quiesces_candidate_and_entry_remains_reloadable(hass, monkeypatch):
    entry, draft, _canonical, active = await _configured(hass)
    confirmation = await _confirmation(hass, entry)
    original_reload = hass.config_entries.async_reload
    candidate_host = None
    calls = 0

    async def failed_handover_and_rollback(entry_id):
        nonlocal candidate_host, calls
        calls += 1
        if calls == 1:
            assert await original_reload(entry_id)
            candidate_host = entry.runtime_data.water_safety_host
        return False

    with monkeypatch.context() as patch:
        patch.setattr(hass.config_entries, "async_reload", failed_handover_and_rollback)
        result = await hass.config_entries.options.async_configure(confirmation["flow_id"], {})
    assert result["errors"] == {"base": "water_safety_activation_failed"}
    assert calls == 2
    assert active_reference_for_module(entry.data, "water_safety") == active
    assert candidate_host._stopped
    assert entry.runtime_data.water_safety_host is None
    assert not entry.runtime_data.reloading
    assert await _water_drafts(hass, entry) == (draft,)
    assert await original_reload(entry.entry_id)
    assert entry.runtime_data.water_safety_host.runtime.snapshot.canonical_revision_id == active.canonical_revision_id
    hass.states.async_set(SENSOR, "on")
    await hass.async_block_till_done()
    assert entry.runtime_data.water_safety_host.runtime.state is WaterSafetyState.WET


async def test_live_water_attempt_is_not_recovered_but_stale_attempt_is_cleared_on_retry(hass):
    from custom_components.controlel.water_safety_activation import async_recover_water_activation

    entry, _draft, canonical, _active = await _configured(hass)
    backend = await async_get_setup_backend(hass, entry)
    async with backend.activation_lock:
        await backend.activation.prepare(canonical.revision_id, attempt_id="live-water", prepared_at=datetime.now(UTC))
        await backend.activation.begin_applying("live-water", applying_at=datetime.now(UTC))
        await async_recover_water_activation(hass, entry)
        assert (await backend.repository.get_activation_attempt("live-water")).state is ActivationState.APPLYING
    # The process-local owner is gone, but persisted APPLYING remains until retry.
    confirmation = await _confirmation(hass, entry)
    result = await hass.config_entries.options.async_configure(confirmation["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    recovered = await backend.repository.get_activation_attempt("live-water")
    assert recovered.state is ActivationState.ROLLED_BACK
    assert recovered.interruption_recovered_at is not None
    assert await backend.repository.list_non_terminal_attempts() == ()


async def test_water_commit_evidence_failure_recovers_only_verified_durable_commit(hass, monkeypatch):
    entry, _draft, _canonical, _active = await _configured(hass)
    confirmation = await _confirmation(hass, entry)
    backend = await async_get_setup_backend(hass, entry)
    original_transition = backend.repository.transition_activation_attempt
    failed = False

    async def fail_terminal_once(attempt, **kwargs):
        nonlocal failed
        if attempt.state is ActivationState.COMMITTED and not failed:
            failed = True
            raise OSError("terminal evidence write failed")
        return await original_transition(attempt, **kwargs)

    monkeypatch.setattr(backend.repository, "transition_activation_attempt", fail_terminal_once)
    result = await hass.config_entries.options.async_configure(confirmation["flow_id"], {})
    await hass.async_block_till_done()
    assert failed
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    active = active_reference_for_module(entry.data, "water_safety")
    assert entry.runtime_data.water_safety_host.runtime.snapshot.canonical_revision_id == active.canonical_revision_id
    assert await backend.repository.list_non_terminal_attempts() == ()
    attempt = await backend.repository.get_activation_attempt(active.committing_operation_id)
    assert attempt.state is ActivationState.COMMITTED
    assert attempt.candidate_runtime_ready.readiness_evidence["serialized_entry_reload"] is True


async def test_interrupted_first_water_activation_does_not_promote_candidate(hass):
    from controlel.application.configuration.water_safety_setup_adapter import WaterSafetySetupAdapter
    from tests.integrations.home_assistant.framework.test_config_flow import _seed_water_draft

    entry = await _empty_entry(hass, title="Water first activation interruption")
    draft, report = await _seed_water_draft(hass, entry, complete=True)
    candidate = WaterSafetySetupAdapter().canonicalize(
        draft,
        report,
        configuration_id="water-initial",
        revision_id="water-unverified",
        revision=1,
        provider="home_assistant",
        provider_instance_id=draft.environment_id,
        created_at=datetime.now(UTC),
        actor="test",
        source="test",
        change_kind="CREATE",
        reason="test",
        core_version="0.17.0",
    )
    backend = await async_get_setup_backend(hass, entry)
    await backend.repository.add_canonical_revision(candidate)
    await backend.activation.prepare(
        candidate.revision_id, attempt_id="first-interrupted", prepared_at=datetime.now(UTC)
    )
    await backend.activation.begin_applying("first-interrupted", applying_at=datetime.now(UTC))
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.data.pop("controlel_setup_backend", None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    backend = await async_get_setup_backend(hass, entry)
    assert active_reference_for_module(entry.data, "water_safety") is None
    assert entry.runtime_data.water_safety_host is None
    assert await backend.repository.list_non_terminal_attempts() == ()
    assert await _water_drafts(hass, entry) == (draft,)


async def test_crash_after_water_candidate_reload_restores_previous_authority_on_restart(hass, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    entry, draft, _canonical, active = await _configured(hass)
    confirmation = await _confirmation(hass, entry)
    backend = await async_get_setup_backend(hass, entry)
    with monkeypatch.context() as patch:
        patch.setattr(
            backend.activation, "record_candidate_runtime_ready", AsyncMock(side_effect=asyncio.CancelledError)
        )
        with pytest.raises(asyncio.CancelledError):
            await hass.config_entries.options.async_configure(confirmation["flow_id"], {})
    assert active_reference_for_module(entry.data, "water_safety") == active
    assert entry.runtime_data.water_safety_host.runtime.snapshot.canonical_revision_id != active.canonical_revision_id
    (interrupted,) = await backend.repository.list_non_terminal_attempts()
    assert interrupted.state is ActivationState.APPLYING
    assert interrupted.candidate_runtime_ready is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.data.pop("controlel_setup_backend", None)
    hass.data.pop("controlel_staged_water_runtime", None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    backend = await async_get_setup_backend(hass, entry)
    assert await backend.repository.list_non_terminal_attempts() == ()
    assert active_reference_for_module(entry.data, "water_safety") == active
    assert entry.runtime_data.water_safety_host.runtime.snapshot.canonical_revision_id == active.canonical_revision_id
    assert await _water_drafts(hass, entry) == (draft,)
    hass.states.async_set(SENSOR, "on")
    await hass.async_block_till_done()
    assert entry.runtime_data.water_safety_host.runtime.state is WaterSafetyState.WET
