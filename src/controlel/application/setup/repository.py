"""Setup persistence ports and deterministic in-memory reference storage."""

from __future__ import annotations

from threading import RLock
from typing import Protocol

from controlel.application.setup.model import (
    ActivationAttempt,
    ActivationState,
    ActiveReference,
    CanonicalConfigurationRevision,
    DraftRevision,
)

type ScopeKey = tuple[str, str, str]


class SetupRepositoryError(RuntimeError):
    """Base failure for setup authority storage."""


class SetupNotFoundError(SetupRepositoryError):
    pass


class SetupConflictError(SetupRepositoryError):
    pass


class DraftRepository(Protocol):
    def save_draft(self, draft: DraftRevision) -> None: ...

    def get_draft(self, draft_id: str, revision: int | None = None) -> DraftRevision: ...

    def delete_draft(self, draft_id: str, *, expected_revision: int) -> None: ...


class ConfigurationAuthorityRepository(Protocol):
    def add_canonical_revision(self, revision: CanonicalConfigurationRevision) -> None: ...

    def get_canonical_revision(self, revision_id: str) -> CanonicalConfigurationRevision: ...

    def get_active_reference(self, scope: ScopeKey) -> ActiveReference | None: ...

    def compare_and_swap_active_reference(
        self,
        *,
        scope: ScopeKey,
        expected_revision_id: str | None,
        expected_generation: int,
        replacement: ActiveReference,
    ) -> None: ...


class ActivationAttemptRepository(Protocol):
    def reserve_activation_attempt(self, attempt: ActivationAttempt) -> None: ...

    def transition_activation_attempt(
        self,
        attempt: ActivationAttempt,
        *,
        expected_state: ActivationState,
        expected_version: int,
    ) -> None: ...

    def get_activation_attempt(self, attempt_id: str) -> ActivationAttempt: ...

    def list_non_terminal_attempts(self) -> tuple[ActivationAttempt, ...]: ...


class InMemorySetupRepository(DraftRepository, ConfigurationAuthorityRepository, ActivationAttemptRepository):
    """Small reference implementation with optimistic revision/CAS checks."""

    def __init__(self) -> None:
        self._drafts: dict[str, dict[int, DraftRevision]] = {}
        self._canonical_revisions: dict[str, CanonicalConfigurationRevision] = {}
        self._active_references: dict[ScopeKey, ActiveReference] = {}
        self._activation_attempts: dict[str, ActivationAttempt] = {}
        self._lock = RLock()

    def save_draft(self, draft: DraftRevision) -> None:
        with self._lock:
            revisions = self._drafts.get(draft.draft_id, {})
            if draft.revision in revisions:
                if revisions[draft.revision] == draft:
                    return
                raise SetupConflictError("draft revision already exists with different content")
            expected_revision = max(revisions, default=0) + 1
            if draft.revision != expected_revision:
                raise SetupConflictError(f"expected draft revision {expected_revision}, got {draft.revision}")
            if revisions:
                previous = revisions[expected_revision - 1]
                identity = (draft.environment_id, draft.module_key, draft.module_instance_id, draft.created_at)
                previous_identity = (
                    previous.environment_id,
                    previous.module_key,
                    previous.module_instance_id,
                    previous.created_at,
                )
                if identity != previous_identity:
                    raise SetupConflictError("draft identity cannot change between revisions")
            self._drafts.setdefault(draft.draft_id, {})[draft.revision] = draft

    def get_draft(self, draft_id: str, revision: int | None = None) -> DraftRevision:
        with self._lock:
            revisions = self._drafts.get(draft_id)
            if not revisions:
                raise SetupNotFoundError(f"draft not found: {draft_id}")
            selected_revision = max(revisions) if revision is None else revision
            try:
                return revisions[selected_revision]
            except KeyError as error:
                raise SetupNotFoundError(f"draft revision not found: {draft_id}@{selected_revision}") from error

    def delete_draft(self, draft_id: str, *, expected_revision: int) -> None:
        with self._lock:
            revisions = self._drafts.get(draft_id)
            if not revisions:
                raise SetupNotFoundError(f"draft not found: {draft_id}")
            current_revision = max(revisions)
            if current_revision != expected_revision:
                raise SetupConflictError(
                    f"draft changed before deletion: expected {expected_revision}, found {current_revision}"
                )
            del self._drafts[draft_id]

    def add_canonical_revision(self, revision: CanonicalConfigurationRevision) -> None:
        with self._lock:
            current = self._canonical_revisions.get(revision.revision_id)
            if current is not None:
                if current == revision:
                    return
                raise SetupConflictError("canonical revision IDs are immutable")
            self._canonical_revisions[revision.revision_id] = revision

    def get_canonical_revision(self, revision_id: str) -> CanonicalConfigurationRevision:
        with self._lock:
            try:
                return self._canonical_revisions[revision_id]
            except KeyError as error:
                raise SetupNotFoundError(f"canonical revision not found: {revision_id}") from error

    def get_active_reference(self, scope: ScopeKey) -> ActiveReference | None:
        with self._lock:
            return self._active_references.get(scope)

    def compare_and_swap_active_reference(
        self,
        *,
        scope: ScopeKey,
        expected_revision_id: str | None,
        expected_generation: int,
        replacement: ActiveReference,
    ) -> None:
        with self._lock:
            current = self._active_references.get(scope)
            current_revision_id = None if current is None else current.canonical_revision_id
            current_generation = 0 if current is None else current.generation
            if current_revision_id != expected_revision_id or current_generation != expected_generation:
                raise SetupConflictError("active reference changed during activation")
            if replacement.scope_key != scope:
                raise SetupConflictError("replacement active reference belongs to another scope")
            if replacement.generation != expected_generation + 1:
                raise SetupConflictError("replacement active generation must increment exactly once")
            candidate = self._canonical_revisions.get(replacement.canonical_revision_id)
            if candidate is None:
                raise SetupConflictError("active reference must select a persisted canonical revision")
            candidate_scope = (candidate.environment_id, candidate.module_key, candidate.module_instance_id)
            if candidate_scope != scope:
                raise SetupConflictError("active reference canonical revision belongs to another scope")
            if candidate.semantic_configuration_fingerprint != replacement.semantic_configuration_fingerprint:
                raise SetupConflictError("active reference fingerprint does not match canonical revision")
            self._active_references[scope] = replacement

    def reserve_activation_attempt(self, attempt: ActivationAttempt) -> None:
        with self._lock:
            if attempt.attempt_id in self._activation_attempts:
                raise SetupConflictError(f"activation attempt already exists: {attempt.attempt_id}")
            if any(
                current.scope_key == attempt.scope_key and current.state not in _TERMINAL_ACTIVATION_STATES
                for current in self._activation_attempts.values()
            ):
                raise SetupConflictError("activation already in progress for configuration scope")
            self._activation_attempts[attempt.attempt_id] = attempt

    def transition_activation_attempt(
        self,
        attempt: ActivationAttempt,
        *,
        expected_state: ActivationState,
        expected_version: int,
    ) -> None:
        with self._lock:
            current = self._activation_attempts.get(attempt.attempt_id)
            if current is None:
                raise SetupNotFoundError(f"activation attempt not found: {attempt.attempt_id}")
            if current.state is not expected_state or current.version != expected_version:
                raise SetupConflictError("activation attempt changed before transition")
            if attempt.version != expected_version + 1:
                raise SetupConflictError("activation attempt version must increment exactly once")
            self._activation_attempts[attempt.attempt_id] = attempt

    def get_activation_attempt(self, attempt_id: str) -> ActivationAttempt:
        with self._lock:
            try:
                return self._activation_attempts[attempt_id]
            except KeyError as error:
                raise SetupNotFoundError(f"activation attempt not found: {attempt_id}") from error

    def list_non_terminal_attempts(self) -> tuple[ActivationAttempt, ...]:
        with self._lock:
            return tuple(
                attempt
                for attempt in self._activation_attempts.values()
                if attempt.state not in _TERMINAL_ACTIVATION_STATES
            )


_TERMINAL_ACTIVATION_STATES = frozenset(
    {ActivationState.COMMITTED, ActivationState.ROLLED_BACK, ActivationState.FAILED}
)
