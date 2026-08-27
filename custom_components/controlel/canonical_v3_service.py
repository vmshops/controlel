"""Home Assistant facade for the frontend-neutral canonical v3 lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from controlel.application.configuration import (
    ActiveCanonicalConfigurationV3,
    CanonicalConfigurationDraftV3,
    CanonicalConfigurationLifecycleV3,
    CanonicalConfigurationRevisionV3,
    CanonicalConfigurationValidationV3,
    CanonicalReferenceHealthV3,
    ConfigurationScopesV3,
    canonical_reference_bindings_v3,
)
from controlel.application.setup import ActiveReference, SetupConflictError, SetupNotFoundError
from controlel.infrastructure.home_assistant import (
    ACTIVE_REFERENCE_KEY,
    HomeAssistantDiscoveryAdapter,
    HomeAssistantReferenceResolver,
    HomeAssistantSetupRepository,
)


class HomeAssistantCanonicalConfigurationV3Service:
    """One backend contract consumable by HA Configure and external UI clients."""

    def __init__(self, hass: Any, entry: Any, repository: HomeAssistantSetupRepository) -> None:
        self._hass = hass
        self._entry = entry
        self._repository = repository
        self._lifecycle = CanonicalConfigurationLifecycleV3(repository)

    async def read_active(
        self,
        *,
        snapshot_id: str,
        captured_at: datetime,
    ) -> ActiveCanonicalConfigurationV3:
        active = self._canonical_active_reference()
        revision = await self._repository.get_canonical_revision_v3(active.canonical_revision_id)
        health = await self._reference_health(revision, snapshot_id=snapshot_id, captured_at=captured_at)
        return await self._lifecycle.read_active(
            active.scope_key,
            reference_health=health,
            runtime_evidence=await self._runtime_evidence(active),
        )

    async def edit_from_active(
        self,
        *,
        draft_id: str,
        created_at: datetime,
        expected_active_generation: int,
    ) -> CanonicalConfigurationDraftV3:
        active = self._canonical_active_reference()
        return await self._lifecycle.clone_active_to_draft(
            active.scope_key,
            draft_id=draft_id,
            created_at=created_at,
            expected_active_generation=expected_active_generation,
        )

    async def update_draft(
        self,
        draft_id: str,
        *,
        expected_revision: int,
        updated_at: datetime,
        configuration_scopes: Mapping[str, object] | ConfigurationScopesV3,
    ) -> CanonicalConfigurationDraftV3:
        scopes = (
            configuration_scopes
            if isinstance(configuration_scopes, ConfigurationScopesV3)
            else ConfigurationScopesV3.model_validate(configuration_scopes)
        )
        return await self._lifecycle.update_draft(
            draft_id,
            expected_revision=expected_revision,
            updated_at=updated_at,
            scopes=scopes,
        )

    async def validate_draft(
        self,
        draft_id: str,
        *,
        report_id: str,
        snapshot_id: str,
        evaluated_at: datetime,
    ) -> CanonicalConfigurationValidationV3:
        draft = await self._repository.get_canonical_draft_v3(draft_id)
        health = await self._reference_health(draft, snapshot_id=snapshot_id, captured_at=evaluated_at)
        return await self._lifecycle.validate_draft(
            draft_id,
            report_id=report_id,
            evaluated_at=evaluated_at,
            reference_health=health,
        )

    async def canonicalize_draft(
        self,
        draft_id: str,
        *,
        validation_report_id: str,
        revision_id: str,
        created_at: datetime,
        actor: str,
        source: str,
        change_kind: str,
        reason: str,
        core_version: str,
        integration_version: str | None = None,
    ) -> CanonicalConfigurationRevisionV3:
        return await self._lifecycle.canonicalize_draft(
            draft_id,
            validation_report_id=validation_report_id,
            revision_id=revision_id,
            created_at=created_at,
            actor=actor,
            source=source,
            change_kind=change_kind,
            reason=reason,
            core_version=core_version,
            integration_version=integration_version,
        )

    def _canonical_active_reference(self) -> ActiveReference:
        raw = self._entry.data.get(ACTIVE_REFERENCE_KEY)
        if raw is None:
            raise SetupConflictError("config entry has no active canonical configuration")
        if set(self._entry.data) != {ACTIVE_REFERENCE_KEY} or self._entry.options:
            raise SetupConflictError("canonical configuration cannot be mixed with legacy entry settings")
        try:
            return ActiveReference.model_validate(raw)
        except (TypeError, ValueError) as error:
            raise SetupConflictError("config entry active canonical reference is invalid") from error

    async def _reference_health(
        self,
        configuration: CanonicalConfigurationRevisionV3 | CanonicalConfigurationDraftV3,
        *,
        snapshot_id: str,
        captured_at: datetime,
    ) -> tuple[CanonicalReferenceHealthV3, ...]:
        snapshot = await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
            self._hass,
            snapshot_id=snapshot_id,
            captured_at=captured_at,
        )
        if (
            configuration.environment_id != snapshot.provider_instance_id
            or configuration.provider_instance_id != snapshot.provider_instance_id
        ):
            raise SetupConflictError("canonical v3 configuration belongs to another Home Assistant instance")
        resolver = HomeAssistantReferenceResolver()
        result = []
        for binding in canonical_reference_bindings_v3(configuration):
            resolution = resolver.resolve(binding.reference, snapshot)
            result.append(
                CanonicalReferenceHealthV3(
                    canonical_path=binding.canonical_path,
                    activation_required=binding.activation_required,
                    reference=binding.reference,
                    status=resolution.status,
                    reason_code=resolution.reason_code,
                    resolved_reference=resolution.resolved_reference,
                    evidence={
                        "recovery_candidates": [
                            candidate.model_dump(mode="json") for candidate in resolution.recovery_candidates
                        ],
                        "snapshot_id": snapshot.snapshot_id,
                        "snapshot_fingerprint": snapshot.content_fingerprint,
                    },
                )
            )
        return tuple(result)

    async def _runtime_evidence(self, active: ActiveReference) -> dict[str, object]:
        runtime_data = getattr(self._entry, "runtime_data", None)
        loaded = None if runtime_data is None else getattr(runtime_data, "loaded_configuration", None)
        host = None if runtime_data is None else getattr(runtime_data, "host", None)
        authority_loaded = bool(
            loaded is not None
            and loaded.canonical_revision_id == active.canonical_revision_id
            and loaded.semantic_configuration_fingerprint == active.semantic_configuration_fingerprint
            and (loaded.environment_id, loaded.module_key, loaded.module_instance_id) == active.scope_key
        )
        readiness = None
        try:
            attempt = await self._repository.get_activation_attempt(active.committing_operation_id)
        except SetupNotFoundError:
            attempt = None
        if attempt is not None and attempt.candidate_runtime_ready is not None:
            readiness = attempt.candidate_runtime_ready.model_dump(mode="json")
        return {
            "authority_loaded": authority_loaded,
            "host_ready": bool(host is not None and getattr(host, "frontend_api_setup_ready", False)),
            "loaded_configuration": None if loaded is None else loaded.model_dump(mode="json"),
            "activation_attempt_id": active.committing_operation_id,
            "candidate_runtime_ready": readiness,
        }
