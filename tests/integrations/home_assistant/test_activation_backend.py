"""Focused orchestration tests for safe Home Assistant activation handover."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from controlel.application.configuration import migrate_heating_v2_revision_to_v3
from controlel.application.configuration.heating_setup_adapter import HeatingSetupAdapter
from controlel.application.setup import (
    ActivationAttempt,
    ActivationState,
    ActiveReference,
    LoadedRuntimeConfiguration,
    SetupConflictError,
)
from controlel.infrastructure.home_assistant import ACTIVE_REFERENCE_KEY
from custom_components.controlel import activation_backend
from custom_components.controlel.canonical_runtime import RuntimeConfigurationSelection
from tests.application.setup.conftest import complete_draft

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
PREVIOUS_FINGERPRINT = "b" * 64


@pytest.fixture(params=("v2", "v3"))
def canonical_revision(request: pytest.FixtureRequest):
    draft = complete_draft()
    adapter = HeatingSetupAdapter()
    report = adapter.validate(draft, report_id="report-activation-backend", evaluated_at=NOW)
    v2 = adapter.canonicalize(
        draft,
        report,
        configuration_id="configuration-1",
        revision_id="canonical-candidate",
        revision=2,
        provider="home_assistant",
        provider_instance_id="ha-home",
        created_at=NOW,
        actor="test:admin",
        source="test",
        change_kind="UPDATE",
        reason="activation_backend_test",
        core_version="0.14.0",
        integration_version="0.14.0",
    )
    if request.param == "v2":
        return v2
    return migrate_heating_v2_revision_to_v3(
        v2,
        revision_id="canonical-candidate-v3",
        created_at=NOW,
        actor="test:admin",
        source="test",
        reason="activation_backend_v3_regression",
    )


def _stamp(revision_id: str, fingerprint: str) -> LoadedRuntimeConfiguration:
    return LoadedRuntimeConfiguration(
        canonical_revision_id=revision_id,
        semantic_configuration_fingerprint=fingerprint,
        environment_id="home",
        module_key="heating",
        module_instance_id="main-heating",
    )


def _active(revision_id: str, fingerprint: str, *, generation: int, operation_id: str) -> ActiveReference:
    return ActiveReference(
        environment_id="home",
        module_key="heating",
        module_instance_id="main-heating",
        canonical_revision_id=revision_id,
        semantic_configuration_fingerprint=fingerprint,
        generation=generation,
        committing_operation_id=operation_id,
    )


def _attempt(candidate: Any, *, attempt_id: str = "activate-candidate") -> ActivationAttempt:
    return ActivationAttempt(
        attempt_id=attempt_id,
        environment_id="home",
        module_key="heating",
        module_instance_id="main-heating",
        state=ActivationState.PREPARED,
        candidate_revision_id=candidate.revision_id,
        candidate_semantic_fingerprint=candidate.semantic_configuration_fingerprint,
        previous_revision_id="canonical-previous",
        previous_semantic_fingerprint=PREVIOUS_FINGERPRINT,
        last_known_good_revision_id="canonical-previous",
        last_known_good_semantic_fingerprint=PREVIOUS_FINGERPRINT,
        expected_active_generation=1,
        prepared_at=NOW,
    )


class _Repository:
    def __init__(self, candidate: Any, attempts: tuple[ActivationAttempt, ...] = ()) -> None:
        self.candidate = candidate
        self.attempts = attempts

    async def get_canonical_revision(self, revision_id: str) -> Any:
        assert revision_id == self.candidate.revision_id
        return self.candidate

    async def list_non_terminal_attempts(self) -> tuple[ActivationAttempt, ...]:
        return self.attempts


class _Activation:
    def __init__(self, prepared: ActivationAttempt, *, commit_error: Exception | None = None) -> None:
        self.prepared = prepared
        self.commit_error = commit_error
        self.failed_calls: list[dict[str, Any]] = []
        self.recovery_calls: list[dict[str, Any]] = []

    async def prepare(self, revision_id: str, **kwargs: Any) -> ActivationAttempt:
        assert revision_id == self.prepared.candidate_revision_id
        assert kwargs["attempt_id"] == self.prepared.attempt_id
        return self.prepared

    async def begin_applying(self, attempt_id: str, **kwargs: Any) -> ActivationAttempt:
        assert attempt_id == self.prepared.attempt_id
        return self.prepared

    async def record_candidate_runtime_ready(self, attempt_id: str, **kwargs: Any) -> ActivationAttempt:
        assert attempt_id == self.prepared.attempt_id
        assert kwargs["candidate_ready"].runtime.canonical_revision_id == self.prepared.candidate_revision_id
        return self.prepared

    async def commit(self, attempt_id: str, **kwargs: Any) -> ActivationAttempt:
        assert attempt_id == self.prepared.attempt_id
        if self.commit_error is not None:
            raise self.commit_error
        return self.prepared

    async def record_failed_application(self, attempt_id: str, **kwargs: Any) -> ActivationAttempt:
        assert attempt_id == self.prepared.attempt_id
        self.failed_calls.append(kwargs)
        return self.prepared

    async def recover_interrupted(self, attempt_id: str, **kwargs: Any) -> ActivationAttempt:
        assert attempt_id == self.prepared.attempt_id
        self.recovery_calls.append(kwargs)
        return self.prepared


@dataclass
class _Entry:
    data: dict[str, object]
    options: dict[str, object]
    runtime_data: Any
    entry_id: str = "entry-1"


class _Host:
    frontend_api_setup_ready = True

    def __init__(self) -> None:
        self.stopped = False

    async def async_stop(self) -> None:
        self.stopped = True


class _ConfigEntries:
    def __init__(self, reload_results: list[tuple[bool, LoadedRuntimeConfiguration | None]]) -> None:
        self.reload_results = reload_results
        self.entry: _Entry | None = None

    async def async_reload(self, entry_id: str) -> bool:
        assert self.entry is not None
        assert entry_id == self.entry.entry_id
        success, stamp = self.reload_results.pop(0)
        if success:
            self.entry.runtime_data = SimpleNamespace(
                loaded_configuration=stamp,
                host=_Host(),
            )
        return success


async def _activate(
    monkeypatch: pytest.MonkeyPatch,
    canonical_revision: Any,
    *,
    reload_results: list[tuple[bool, LoadedRuntimeConfiguration | None]],
    commit_error: Exception | None = None,
) -> tuple[_Entry, _Activation, dict[str, object]]:
    prepared = _attempt(canonical_revision)
    activation = _Activation(prepared, commit_error=commit_error)
    backend = SimpleNamespace(
        repository=_Repository(canonical_revision),
        activation=activation,
        activation_lock=asyncio.Lock(),
    )
    candidate_stamp = _stamp(
        canonical_revision.revision_id,
        canonical_revision.semantic_configuration_fingerprint,
    )
    selection = RuntimeConfigurationSelection(
        config=SimpleNamespace(),
        loaded_configuration=candidate_stamp,
        activation_attempt_id=prepared.attempt_id,
    )
    previous = _active(
        "canonical-previous",
        PREVIOUS_FINGERPRINT,
        generation=1,
        operation_id="activate-previous",
    )
    entry = _Entry(
        data={ACTIVE_REFERENCE_KEY: previous.model_dump(mode="json")},
        options={},
        runtime_data=SimpleNamespace(loaded_configuration=_stamp("canonical-previous", PREVIOUS_FINGERPRINT)),
    )
    config_entries = _ConfigEntries(reload_results)
    config_entries.entry = entry
    hass = SimpleNamespace(data={}, config_entries=config_entries)

    async def get_backend(unused_hass: Any, unused_entry: Any) -> Any:
        return backend

    async def compile_candidate(unused_hass: Any, unused_revision: Any, **kwargs: Any) -> Any:
        assert kwargs["activation_attempt_id"] == prepared.attempt_id
        return selection

    monkeypatch.setattr(activation_backend, "async_get_setup_backend", get_backend)
    monkeypatch.setattr(activation_backend, "async_compile_canonical_runtime", compile_candidate)

    with pytest.raises(SetupConflictError, match="prior authority was retained"):
        await activation_backend.async_activate_canonical_revision(
            hass,
            entry,
            revision_id=canonical_revision.revision_id,
            semantic_configuration_fingerprint=canonical_revision.semantic_configuration_fingerprint,
            expected_active_revision_id="canonical-previous",
            expected_active_generation=1,
            attempt_id=prepared.attempt_id,
        )
    return entry, activation, hass.data


def test_failed_handover_restores_previous_canonical_authority(monkeypatch, canonical_revision) -> None:
    previous_stamp = _stamp("canonical-previous", PREVIOUS_FINGERPRINT)

    entry, activation, hass_data = asyncio.run(
        _activate(
            monkeypatch,
            canonical_revision,
            reload_results=[(False, None), (True, previous_stamp)],
        )
    )

    restored = ActiveReference.model_validate(entry.data[ACTIVE_REFERENCE_KEY])
    assert restored.canonical_revision_id == "canonical-previous"
    assert entry.runtime_data.loaded_configuration == previous_stamp
    assert activation.failed_calls[0]["rollback_succeeded"] is True
    assert activation.failed_calls[0]["rollback_runtime_stamp"] == previous_stamp
    assert "controlel_staged_canonical_runtime" not in hass_data


def test_commit_cas_loss_stops_candidate_and_restores_previous_authority(monkeypatch, canonical_revision) -> None:
    candidate_stamp = _stamp(canonical_revision.revision_id, canonical_revision.semantic_configuration_fingerprint)
    previous_stamp = _stamp("canonical-previous", PREVIOUS_FINGERPRINT)

    entry, activation, hass_data = asyncio.run(
        _activate(
            monkeypatch,
            canonical_revision,
            reload_results=[(True, candidate_stamp), (True, previous_stamp)],
            commit_error=SetupConflictError("active reference changed before CAS"),
        )
    )

    restored = ActiveReference.model_validate(entry.data[ACTIVE_REFERENCE_KEY])
    assert restored.canonical_revision_id == "canonical-previous"
    assert entry.runtime_data.loaded_configuration == previous_stamp
    assert len(activation.failed_calls) == 1
    assert activation.recovery_calls == []
    assert "controlel_staged_canonical_runtime" not in hass_data


def test_failed_rollback_reload_quiesces_non_authoritative_candidate(monkeypatch, canonical_revision) -> None:
    candidate_stamp = _stamp(canonical_revision.revision_id, canonical_revision.semantic_configuration_fingerprint)

    entry, activation, hass_data = asyncio.run(
        _activate(
            monkeypatch,
            canonical_revision,
            reload_results=[(True, candidate_stamp), (False, None)],
            commit_error=SetupConflictError("active reference changed before CAS"),
        )
    )

    restored = ActiveReference.model_validate(entry.data[ACTIVE_REFERENCE_KEY])
    assert restored.canonical_revision_id == "canonical-previous"
    assert entry.runtime_data.loaded_configuration == candidate_stamp
    assert entry.runtime_data.host is None
    assert activation.failed_calls[0]["rollback_succeeded"] is False
    assert "controlel_staged_canonical_runtime" not in hass_data


@pytest.mark.parametrize("durable_commit", [False, True])
def test_restart_recovery_uses_loaded_authority_and_commit_marker(canonical_revision, durable_commit) -> None:
    prepared = _attempt(canonical_revision)
    applying = prepared.model_copy(
        update={
            "state": ActivationState.APPLYING,
            "version": 2,
            "applying_at": NOW,
        }
    )
    activation = _Activation(applying)
    backend = SimpleNamespace(
        repository=_Repository(canonical_revision, (applying,)),
        activation=activation,
        activation_lock=asyncio.Lock(),
    )
    if durable_commit:
        stamp = _stamp(canonical_revision.revision_id, canonical_revision.semantic_configuration_fingerprint)
        active = _active(
            canonical_revision.revision_id,
            canonical_revision.semantic_configuration_fingerprint,
            generation=2,
            operation_id=applying.attempt_id,
        )
    else:
        stamp = _stamp("canonical-previous", PREVIOUS_FINGERPRINT)
        active = _active(
            "canonical-previous",
            PREVIOUS_FINGERPRINT,
            generation=1,
            operation_id="activate-previous",
        )
    entry = _Entry(
        data={ACTIVE_REFERENCE_KEY: active.model_dump(mode="json")},
        options={},
        runtime_data=SimpleNamespace(loaded_configuration=stamp),
    )
    selection = RuntimeConfigurationSelection(SimpleNamespace(), stamp)

    recovered = asyncio.run(
        activation_backend.async_recover_interrupted_activation(SimpleNamespace(), entry, backend, selection)
    )

    assert recovered == (applying,)
    call = activation.recovery_calls[0]
    assert call["rollback_succeeded"] is (not durable_commit)
    assert call.get("rollback_runtime_stamp") == (None if durable_commit else stamp)
