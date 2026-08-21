"""Durable Home Assistant storage adapters for the Setup authority contracts."""

from __future__ import annotations

from asyncio import Lock
from collections.abc import Callable, Mapping
from typing import Any, Protocol, cast

from controlel.application.setup import (
    ActivationAttempt,
    ActivationState,
    ActiveReference,
    CanonicalConfigurationRevision,
    DraftRevision,
    SetupConflictError,
    SetupNotFoundError,
    ValidationReport,
)
from controlel.application.setup.repository import ScopeKey

SETUP_STORAGE_VERSION = 1
ACTIVE_REFERENCE_KEY = "setup_active_reference"


class HomeAssistantStorePort(Protocol):
    """Narrow subset of ``homeassistant.helpers.storage.Store`` used here."""

    async def async_load(self) -> Mapping[str, object] | None: ...

    async def async_save(self, data: Mapping[str, object]) -> None: ...


class ConfigEntryPort(Protocol):
    """Lifecycle handle boundary; no configuration fields are interpreted."""

    @property
    def data(self) -> Mapping[str, object]: ...


class ConfigEntryActiveReferenceStore:
    """Persist only the active authority pointer in a Home Assistant config entry."""

    def __init__(
        self,
        entry: ConfigEntryPort,
        update_data: Callable[[Mapping[str, object]], None],
    ) -> None:
        self._entry = entry
        self._update_data = update_data

    def get(self) -> ActiveReference | None:
        value = self._entry.data.get(ACTIVE_REFERENCE_KEY)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise SetupStorageIntegrityError("config-entry active reference is malformed")
        return ActiveReference.model_validate(value)

    def set(self, reference: ActiveReference) -> None:
        non_lifecycle_keys = set(self._entry.data) - {ACTIVE_REFERENCE_KEY}
        if non_lifecycle_keys:
            raise SetupConflictError(
                "legacy config-entry settings must be explicitly converted before canonical activation"
            )
        data = dict(self._entry.data)
        data[ACTIVE_REFERENCE_KEY] = reference.model_dump(mode="json")
        self._update_data(data)


class SetupStorageIntegrityError(RuntimeError):
    """Persisted Setup data cannot be safely reconstructed."""


class HomeAssistantSetupRepository:
    """Async, durable repository preserving Setup revision and CAS semantics.

    Home Assistant runs setup mutations on one event loop. Composition must share
    this repository (or at least its lock) for one config entry; the integration
    factory does so across reloads.
    """

    def __init__(
        self,
        store: HomeAssistantStorePort,
        active_references: ConfigEntryActiveReferenceStore,
        *,
        lock: Lock | None = None,
    ) -> None:
        self._store = store
        self._active_references = active_references
        self._lock = lock or Lock()

    async def save_draft(self, draft: DraftRevision) -> None:
        async with self._lock:
            document = await self._load()
            drafts = self._drafts(document)
            revisions = {item.revision: item for item in drafts if item.draft_id == draft.draft_id}
            current = revisions.get(draft.revision)
            if current is not None:
                if current == draft:
                    return
                raise SetupConflictError("draft revision already exists with different content")
            expected_revision = max(revisions, default=0) + 1
            if draft.revision != expected_revision:
                raise SetupConflictError(f"expected draft revision {expected_revision}, got {draft.revision}")
            if revisions:
                previous = revisions[expected_revision - 1]
                if _draft_identity(previous) != _draft_identity(draft):
                    raise SetupConflictError("draft identity cannot change between revisions")
            drafts.append(draft)
            document["drafts"] = _dump_models(drafts, key=lambda item: (item.draft_id, item.revision))
            await self._store.async_save(document)

    async def get_draft(self, draft_id: str, revision: int | None = None) -> DraftRevision:
        async with self._lock:
            drafts = [item for item in self._drafts(await self._load()) if item.draft_id == draft_id]
            if not drafts:
                raise SetupNotFoundError(f"draft not found: {draft_id}")
            selected = max(item.revision for item in drafts) if revision is None else revision
            try:
                return next(item for item in drafts if item.revision == selected)
            except StopIteration as error:
                raise SetupNotFoundError(f"draft revision not found: {draft_id}@{selected}") from error

    async def delete_draft(self, draft_id: str, *, expected_revision: int) -> None:
        async with self._lock:
            document = await self._load()
            drafts = self._drafts(document)
            matching = [item for item in drafts if item.draft_id == draft_id]
            if not matching:
                raise SetupNotFoundError(f"draft not found: {draft_id}")
            current_revision = max(item.revision for item in matching)
            if current_revision != expected_revision:
                raise SetupConflictError(
                    f"draft changed before deletion: expected {expected_revision}, found {current_revision}"
                )
            document["drafts"] = _dump_models(
                [item for item in drafts if item.draft_id != draft_id],
                key=lambda item: (item.draft_id, item.revision),
            )
            await self._store.async_save(document)

    async def add_canonical_revision(self, revision: CanonicalConfigurationRevision) -> None:
        async with self._lock:
            document = await self._load()
            revisions = self._canonical_revisions(document)
            current = next((item for item in revisions if item.revision_id == revision.revision_id), None)
            if current is not None:
                if current == revision:
                    return
                raise SetupConflictError("canonical revision IDs are immutable")
            revisions.append(revision)
            document["canonical_revisions"] = _dump_models(revisions, key=lambda item: item.revision_id)
            await self._store.async_save(document)

    async def get_canonical_revision(self, revision_id: str) -> CanonicalConfigurationRevision:
        async with self._lock:
            revision = next(
                (item for item in self._canonical_revisions(await self._load()) if item.revision_id == revision_id),
                None,
            )
            if revision is None:
                raise SetupNotFoundError(f"canonical revision not found: {revision_id}")
            return revision

    async def get_active_reference(self, scope: ScopeKey) -> ActiveReference | None:
        async with self._lock:
            current = self._active_references.get()
            if current is None or current.scope_key != scope:
                return None
            return current

    async def compare_and_swap_active_reference(
        self,
        *,
        scope: ScopeKey,
        expected_revision_id: str | None,
        expected_generation: int,
        replacement: ActiveReference,
    ) -> None:
        async with self._lock:
            document = await self._load()
            current = self._active_references.get()
            if current is not None and current.scope_key != scope:
                raise SetupConflictError("config entry active reference belongs to another scope")
            current_revision_id = None if current is None else current.canonical_revision_id
            current_generation = 0 if current is None else current.generation
            if current_revision_id != expected_revision_id or current_generation != expected_generation:
                raise SetupConflictError("active reference changed during activation")
            if replacement.scope_key != scope or replacement.generation != expected_generation + 1:
                raise SetupConflictError("replacement active reference has invalid scope or generation")
            candidate = next(
                (
                    item
                    for item in self._canonical_revisions(document)
                    if item.revision_id == replacement.canonical_revision_id
                ),
                None,
            )
            if candidate is None:
                raise SetupConflictError("active reference must select a persisted canonical revision")
            if (candidate.environment_id, candidate.module_key, candidate.module_instance_id) != scope:
                raise SetupConflictError("active reference canonical revision belongs to another scope")
            if candidate.semantic_configuration_fingerprint != replacement.semantic_configuration_fingerprint:
                raise SetupConflictError("active reference fingerprint does not match canonical revision")
            self._active_references.set(replacement)

    async def reserve_activation_attempt(self, attempt: ActivationAttempt) -> None:
        async with self._lock:
            document = await self._load()
            attempts = self._activation_attempts(document)
            if any(item.attempt_id == attempt.attempt_id for item in attempts):
                raise SetupConflictError(f"activation attempt already exists: {attempt.attempt_id}")
            if any(item.scope_key == attempt.scope_key and not _terminal(item.state) for item in attempts):
                raise SetupConflictError("activation already in progress for configuration scope")
            attempts.append(attempt)
            document["activation_attempts"] = _dump_models(attempts, key=lambda item: item.attempt_id)
            await self._store.async_save(document)

    async def transition_activation_attempt(
        self,
        attempt: ActivationAttempt,
        *,
        expected_state: ActivationState,
        expected_version: int,
    ) -> None:
        async with self._lock:
            document = await self._load()
            attempts = self._activation_attempts(document)
            current = next((item for item in attempts if item.attempt_id == attempt.attempt_id), None)
            if current is None:
                raise SetupNotFoundError(f"activation attempt not found: {attempt.attempt_id}")
            if current.state is not expected_state or current.version != expected_version:
                raise SetupConflictError("activation attempt changed before transition")
            if attempt.version != expected_version + 1:
                raise SetupConflictError("activation attempt version must increment exactly once")
            attempts = [attempt if item.attempt_id == attempt.attempt_id else item for item in attempts]
            document["activation_attempts"] = _dump_models(attempts, key=lambda item: item.attempt_id)
            await self._store.async_save(document)

    async def get_activation_attempt(self, attempt_id: str) -> ActivationAttempt:
        async with self._lock:
            attempt = next(
                (item for item in self._activation_attempts(await self._load()) if item.attempt_id == attempt_id),
                None,
            )
            if attempt is None:
                raise SetupNotFoundError(f"activation attempt not found: {attempt_id}")
            return attempt

    async def list_non_terminal_attempts(self) -> tuple[ActivationAttempt, ...]:
        async with self._lock:
            return tuple(
                sorted(
                    (item for item in self._activation_attempts(await self._load()) if not _terminal(item.state)),
                    key=lambda item: item.attempt_id,
                )
            )

    async def save_validation_report(self, report: ValidationReport) -> None:
        """Persist assessment evidence for deterministic wizard resume."""

        async with self._lock:
            document = await self._load()
            reports = self._validation_reports(document)
            current = next((item for item in reports if item.report_id == report.report_id), None)
            if current is not None:
                if current == report:
                    return
                raise SetupConflictError("validation report IDs are immutable")
            reports.append(report)
            document["validation_reports"] = _dump_models(
                reports,
                key=lambda item: (
                    item.subject_id,
                    item.subject_revision,
                    item.evaluated_at.isoformat(),
                    item.report_id,
                ),
            )
            await self._store.async_save(document)

    async def get_latest_validation_report(self, draft_id: str) -> ValidationReport | None:
        async with self._lock:
            reports = [item for item in self._validation_reports(await self._load()) if item.subject_id == draft_id]
            if not reports:
                return None
            return max(reports, key=lambda item: (item.subject_revision, item.evaluated_at, item.report_id))

    async def _load(self) -> dict[str, object]:
        loaded = await self._store.async_load()
        if loaded is None:
            return _empty_document()
        if not isinstance(loaded, Mapping):
            raise SetupStorageIntegrityError("Setup storage document must be a mapping")
        document = dict(loaded)
        if document.get("schema_version") != SETUP_STORAGE_VERSION:
            raise SetupStorageIntegrityError("unsupported Home Assistant Setup storage version")
        for field in _COLLECTION_FIELDS:
            value = document.get(field, [])
            if not isinstance(value, list):
                raise SetupStorageIntegrityError(f"Setup storage field {field} must be a list")
            document[field] = value
        return document

    @staticmethod
    def _drafts(document: Mapping[str, object]) -> list[DraftRevision]:
        return _parse_models(document, "drafts", DraftRevision)

    @staticmethod
    def _canonical_revisions(document: Mapping[str, object]) -> list[CanonicalConfigurationRevision]:
        return _parse_models(document, "canonical_revisions", CanonicalConfigurationRevision)

    @staticmethod
    def _activation_attempts(document: Mapping[str, object]) -> list[ActivationAttempt]:
        return _parse_models(document, "activation_attempts", ActivationAttempt)

    @staticmethod
    def _validation_reports(document: Mapping[str, object]) -> list[ValidationReport]:
        return _parse_models(document, "validation_reports", ValidationReport)


_COLLECTION_FIELDS = ("drafts", "canonical_revisions", "activation_attempts", "validation_reports")
_TERMINAL_STATES = frozenset({ActivationState.COMMITTED, ActivationState.ROLLED_BACK, ActivationState.FAILED})


def _empty_document() -> dict[str, object]:
    return {"schema_version": SETUP_STORAGE_VERSION, **{field: [] for field in _COLLECTION_FIELDS}}


def _parse_models[T](document: Mapping[str, object], field: str, model: type[T]) -> list[T]:
    values = document.get(field, [])
    if not isinstance(values, list):
        raise SetupStorageIntegrityError(f"Setup storage field {field} must be a list")
    validator = cast(object, model)
    try:
        return [cast(T, getattr(validator, "model_validate")(item)) for item in values]
    except (TypeError, ValueError) as error:
        raise SetupStorageIntegrityError(f"Setup storage field {field} contains invalid data") from error


def _dump_models[T](values: list[T], *, key: Callable[[T], Any]) -> list[object]:
    return [getattr(item, "model_dump")(mode="json") for item in sorted(values, key=key)]


def _draft_identity(draft: DraftRevision) -> tuple[object, ...]:
    return (
        draft.environment_id,
        draft.module_key,
        draft.module_instance_id,
        draft.created_at,
    )


def _terminal(state: ActivationState) -> bool:
    return state in _TERMINAL_STATES
