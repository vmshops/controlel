"""Home Assistant facade for the frontend-neutral canonical v3 lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Literal

from controlel.application.configuration import (
    ActiveCanonicalConfigurationV3,
    CanonicalConfigurationConversionReviewV3,
    CanonicalConfigurationDraftV3,
    CanonicalConfigurationLifecycleV3,
    CanonicalConfigurationRevisionV3,
    CanonicalConfigurationValidationV3,
    CanonicalReferenceHealthV3,
    ConfigurationScopesV3,
    GreenfieldHeatingBindingsV3,
    author_greenfield_heating_scopes_v3,
    canonical_reference_bindings_v3,
    conversion_configuration_id_v3,
    migrate_heating_v2_revision_to_v3,
    new_configuration_id_v3,
)
from controlel.application.configuration.heating_setup_adapter import (
    HEAT_DELIVERY_ACTUATOR_ROLE,
    PRIMARY_TEMPERATURE_ROLE,
    REPORTED_SOURCE_STATE_ROLE,
    SOURCE_DISABLE_TARGET_ROLE,
    SOURCE_ENABLE_TARGET_ROLE,
    HeatingSetupAdapter,
)
from controlel.application.setup import (
    ActiveReference,
    CanonicalConfigurationRevision,
    IdentityQuality,
    ProviderReference,
    ReferenceResolutionStatus,
    SetupConflictError,
    SetupNotFoundError,
)
from controlel.infrastructure.home_assistant import (
    ACTIVE_REFERENCE_KEY,
    ACTIVE_REFERENCES_KEY,
    HomeAssistantDiscoveryAdapter,
    HomeAssistantReferenceResolver,
    HomeAssistantSetupRepository,
    active_reference_for_module,
)

from .config import integration_config_from_entry
from .legacy_config_converter import convert_legacy_heating_config

_V2_BINDING_PATHS = {
    PRIMARY_TEMPERATURE_ROLE: "heating.zones[0].primary_temperature_sensor.provider_reference",
    SOURCE_ENABLE_TARGET_ROLE: ("heating.heat_sources[0].command_strategy.enable_permission.command_target_reference"),
    SOURCE_DISABLE_TARGET_ROLE: (
        "heating.heat_sources[0].command_strategy.disable_permission.command_target_reference"
    ),
    REPORTED_SOURCE_STATE_ROLE: "heating.heat_sources[0].observations.reported_actuator_state_reference",
    HEAT_DELIVERY_ACTUATOR_ROLE: "heating.heat_delivery[0].actuator_reference",
}


class HomeAssistantCanonicalConfigurationV3Service:
    """One backend contract consumable by HA Configure and external UI clients."""

    def __init__(
        self,
        hass: Any,
        entry: Any,
        repository: HomeAssistantSetupRepository,
        *,
        configuration_id_factory: Callable[[], str] = new_configuration_id_v3,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._repository = repository
        self._lifecycle = CanonicalConfigurationLifecycleV3(repository)
        self._configuration_id_factory = configuration_id_factory

    async def start_greenfield(
        self,
        *,
        draft_id: str,
        created_at: datetime,
        snapshot_id: str,
        bindings: Mapping[str, object] | GreenfieldHeatingBindingsV3,
    ) -> CanonicalConfigurationDraftV3:
        """Create, but never activate, the first canonical v3 draft."""

        try:
            existing = await self._repository.get_canonical_draft_v3(draft_id)
        except SetupNotFoundError:
            existing = None
        if existing is not None:
            if existing.lineage.get("authoring_origin") != "greenfield_v3":
                raise SetupConflictError("canonical v3 draft ID already belongs to another authoring operation")
            return existing
        if active_reference_for_module(self._entry.data, HeatingSetupAdapter.module_key) is not None:
            raise SetupConflictError("greenfield authoring requires an installation without canonical authority")
        if set(self._entry.data) - {ACTIVE_REFERENCE_KEY, ACTIVE_REFERENCES_KEY} or self._entry.options:
            raise SetupConflictError("legacy configuration must use the explicit legacy conversion operation")
        snapshot = await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
            self._hass,
            snapshot_id=snapshot_id,
            captured_at=created_at,
        )
        authoring = (
            bindings
            if isinstance(bindings, GreenfieldHeatingBindingsV3)
            else GreenfieldHeatingBindingsV3.model_validate(bindings)
        )
        scopes = author_greenfield_heating_scopes_v3(authoring)
        return await self._lifecycle.start_greenfield_draft(
            draft_id=draft_id,
            configuration_id=self._configuration_id_factory(),
            environment_id=snapshot.provider_instance_id,
            provider=snapshot.provider,
            provider_instance_id=snapshot.provider_instance_id,
            created_at=created_at,
            scopes=scopes,
        )

    async def convert_v2(
        self,
        *,
        source_revision_id: str,
        draft_id: str,
        projection_revision_id: str,
        created_at: datetime,
        snapshot_id: str,
        expected_active_revision_id: str | None,
        expected_active_generation: int,
        binding_overrides: Mapping[str, object] | None = None,
    ) -> CanonicalConfigurationConversionReviewV3:
        """Convert one v2 authority to a persisted, inactive v3 review candidate."""

        source = await self._repository.get_canonical_revision(source_revision_id)
        if not isinstance(source, CanonicalConfigurationRevision):
            raise SetupConflictError("canonical conversion source is not Heating schema v2")
        return await self._convert_v2_revision(
            source,
            draft_id=draft_id,
            projection_revision_id=projection_revision_id,
            created_at=created_at,
            snapshot_id=snapshot_id,
            expected_active_revision_id=expected_active_revision_id,
            expected_active_generation=expected_active_generation,
            source_kind="canonical_v2",
            binding_overrides=binding_overrides,
        )

    async def convert_legacy(
        self,
        *,
        draft_id: str,
        v2_revision_id: str,
        projection_revision_id: str,
        created_at: datetime,
        snapshot_id: str,
        core_version: str,
        integration_version: str | None,
        binding_overrides: Mapping[str, object] | None = None,
    ) -> CanonicalConfigurationConversionReviewV3:
        """Compose the existing legacy→v2 and v2→v3 adapters explicitly."""

        if active_reference_for_module(self._entry.data, HeatingSetupAdapter.module_key) is not None:
            raise SetupConflictError("legacy conversion cannot mix with canonical authority")
        if not (set(self._entry.data) - {ACTIVE_REFERENCE_KEY, ACTIVE_REFERENCES_KEY}) and not self._entry.options:
            raise SetupConflictError("config entry has no legacy configuration to convert")
        configuration_id = conversion_configuration_id_v3(f"home_assistant:{self._entry.entry_id}:{v2_revision_id}")
        provider_instance_id = await self._provider_instance_id(snapshot_id, created_at)
        v2_result = convert_legacy_heating_config(
            integration_config_from_entry(self._entry.data, self._entry.options),
            environment_id=provider_instance_id,
            provider_instance_id=provider_instance_id,
            module_instance_id=configuration_id,
            configuration_id=configuration_id,
            revision_id=v2_revision_id,
            created_at=created_at,
            core_version=core_version,
            integration_version=integration_version,
        )
        return await self._convert_v2_revision(
            v2_result.canonical_revision,
            draft_id=draft_id,
            projection_revision_id=projection_revision_id,
            created_at=created_at,
            snapshot_id=snapshot_id,
            expected_active_revision_id=None,
            expected_active_generation=0,
            source_kind="legacy_home_assistant",
            binding_overrides=binding_overrides,
        )

    async def _convert_v2_revision(
        self,
        source: CanonicalConfigurationRevision,
        *,
        draft_id: str,
        projection_revision_id: str,
        created_at: datetime,
        snapshot_id: str,
        expected_active_revision_id: str | None,
        expected_active_generation: int,
        source_kind: Literal["canonical_v2", "legacy_home_assistant"],
        binding_overrides: Mapping[str, object] | None,
    ) -> CanonicalConfigurationConversionReviewV3:
        try:
            existing = await self._repository.get_canonical_draft_v3(draft_id)
        except SetupNotFoundError:
            existing = None
        snapshot = await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
            self._hass,
            snapshot_id=snapshot_id,
            captured_at=created_at,
        )
        if source.environment_id != snapshot.provider_instance_id:
            raise SetupConflictError("canonical v2 conversion source belongs to another Home Assistant instance")
        requested_overrides = {
            role: (value if isinstance(value, ProviderReference) else ProviderReference.model_validate(value))
            for role, value in (binding_overrides or {}).items()
        }
        overrides, source_health = self._v2_binding_resolution(
            source,
            snapshot,
            requested_overrides=requested_overrides,
        )
        blocked_roles = {
            binding.role
            for binding in source.bindings
            if binding.reference.identity_quality is IdentityQuality.EPHEMERAL and binding.role not in overrides
        }
        projection = (
            None
            if blocked_roles
            else migrate_heating_v2_revision_to_v3(
                source,
                revision_id=projection_revision_id,
                created_at=created_at,
                binding_overrides=overrides,
            )
        )
        if existing is not None:
            if (
                existing.lineage.get("conversion_projection_revision_id") != projection_revision_id
                or existing.lineage.get("migrated_from_revision_id") != source.revision_id
                or existing.lineage.get("migrated_from_semantic_configuration_fingerprint")
                != source.semantic_configuration_fingerprint
                or (
                    projection is not None
                    and existing.content_fingerprint != projection.semantic_configuration_fingerprint
                )
            ):
                raise SetupConflictError("canonical v3 draft ID already belongs to another conversion")
            health = self._reference_health_from_snapshot(existing, snapshot)
            return CanonicalConfigurationConversionReviewV3(
                source_kind=source_kind,
                source_revision_id=source.revision_id,
                draft=existing,
                source_reference_health=source_health,
                reference_health=health,
                issue_codes=self._reference_issue_codes(health),
                conversion_ready=True,
            )
        blocked = tuple(item for item in source_health if item.evidence.get("source_binding_role") in blocked_roles)
        if blocked:
            return CanonicalConfigurationConversionReviewV3(
                source_kind=source_kind,
                source_revision_id=source.revision_id,
                draft=None,
                source_reference_health=source_health,
                reference_health=source_health,
                issue_codes=tuple(f"canonical_v3.conversion.{item.status.value.lower()}" for item in blocked),
                conversion_ready=False,
            )
        if projection is None:
            raise SetupConflictError("canonical v3 conversion has unresolved ephemeral bindings")
        draft = await self._lifecycle.start_conversion_draft(
            projection,
            draft_id=draft_id,
            created_at=created_at,
            expected_active_revision_id=expected_active_revision_id,
            expected_active_generation=expected_active_generation,
        )
        health = self._reference_health_from_snapshot(draft, snapshot)
        return CanonicalConfigurationConversionReviewV3(
            source_kind=source_kind,
            source_revision_id=source.revision_id,
            draft=draft,
            source_reference_health=source_health,
            reference_health=health,
            issue_codes=self._reference_issue_codes(health),
            conversion_ready=True,
        )

    async def _provider_instance_id(self, snapshot_id: str, captured_at: datetime) -> str:
        snapshot = await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
            self._hass,
            snapshot_id=snapshot_id,
            captured_at=captured_at,
        )
        return str(snapshot.provider_instance_id)

    def _v2_binding_resolution(
        self,
        source: CanonicalConfigurationRevision,
        snapshot: Any,
        *,
        requested_overrides: Mapping[str, ProviderReference],
    ) -> tuple[dict[str, ProviderReference], tuple[CanonicalReferenceHealthV3, ...]]:
        resolver = HomeAssistantReferenceResolver()
        overrides: dict[str, ProviderReference] = {}
        health = []
        source_roles = {binding.role for binding in source.bindings}
        unknown_roles = set(requested_overrides) - source_roles
        if unknown_roles:
            raise SetupConflictError(f"binding overrides contain unknown roles: {', '.join(sorted(unknown_roles))}")
        for binding in source.bindings:
            reference = binding.reference
            requested = requested_overrides.get(binding.role)
            if requested is not None:
                if requested.identity_quality is not IdentityQuality.STABLE:
                    raise SetupConflictError("canonical v3 binding overrides require stable provider identity")
                resolution = resolver.resolve(requested, snapshot)
                overrides[binding.role] = requested
                resolved_reference = resolution.resolved_reference
                status = resolution.status
                reason_code = resolution.reason_code
            elif reference.identity_quality is IdentityQuality.EPHEMERAL:
                resolution = resolver.resolve(reference, snapshot)
                exact = tuple(
                    item
                    for item in snapshot.objects
                    if item.identity_quality is IdentityQuality.STABLE
                    and item.current_locator == reference.current_locator
                )
                if len(exact) == 1:
                    resolved_reference = exact[0]
                    overrides[binding.role] = resolved_reference
                    status = ReferenceResolutionStatus.RESOLVED
                    reason_code = "home_assistant.legacy_locator_exact_registry_match"
                else:
                    resolved_reference = resolution.resolved_reference
                    status = resolution.status
                    reason_code = resolution.reason_code
            else:
                resolution = resolver.resolve(reference, snapshot)
                resolved_reference = resolution.resolved_reference
                status = resolution.status
                reason_code = resolution.reason_code
            health.append(
                CanonicalReferenceHealthV3(
                    canonical_path=_V2_BINDING_PATHS[binding.role],
                    activation_required=True,
                    reference=reference,
                    status=status,
                    reason_code=reason_code,
                    resolved_reference=resolved_reference,
                    evidence={
                        "source_binding_role": binding.role,
                        "snapshot_id": snapshot.snapshot_id,
                        "snapshot_fingerprint": snapshot.content_fingerprint,
                        **({"requested_override": requested.document_data()} if requested is not None else {}),
                    },
                )
            )
        return overrides, tuple(health)

    @staticmethod
    def _reference_issue_codes(health: tuple[CanonicalReferenceHealthV3, ...]) -> tuple[str, ...]:
        return tuple(
            f"canonical_v3.reference.{item.status.value.lower()}"
            for item in health
            if item.activation_required and not item.runtime_ready
        )

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

    async def reopen_draft(self, draft_id: str) -> CanonicalConfigurationDraftV3:
        """Resume the exact latest persisted draft revision after any client restart."""

        return await self._lifecycle.reopen_draft(draft_id)

    async def list_drafts(self) -> tuple[CanonicalConfigurationDraftV3, ...]:
        """List the latest persisted revision of every v3 draft for this entry."""

        return await self._lifecycle.list_drafts()

    async def abandon_draft(self, draft_id: str, *, expected_revision: int) -> None:
        """Abandon editable v3 state without changing canonical or active authority."""

        await self._lifecycle.abandon_draft(draft_id, expected_revision=expected_revision)

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
        snapshot_id: str,
        created_at: datetime,
        actor: str,
        source: str,
        change_kind: str,
        reason: str,
        core_version: str,
        integration_version: str | None = None,
    ) -> CanonicalConfigurationRevisionV3:
        draft = await self._repository.get_canonical_draft_v3(draft_id)
        fresh_reference_health = await self._reference_health(
            draft,
            snapshot_id=snapshot_id,
            captured_at=created_at,
        )
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
            fresh_reference_health=fresh_reference_health,
            integration_version=integration_version,
        )

    def _canonical_active_reference(self) -> ActiveReference:
        active = active_reference_for_module(self._entry.data, HeatingSetupAdapter.module_key)
        if active is None:
            raise SetupConflictError("config entry has no active canonical configuration")
        if set(self._entry.data) - {ACTIVE_REFERENCE_KEY, ACTIVE_REFERENCES_KEY} or self._entry.options:
            raise SetupConflictError("canonical configuration cannot be mixed with legacy entry settings")
        return active

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
        return self._reference_health_from_snapshot(configuration, snapshot)

    @staticmethod
    def _reference_health_from_snapshot(
        configuration: CanonicalConfigurationRevisionV3 | CanonicalConfigurationDraftV3,
        snapshot: Any,
    ) -> tuple[CanonicalReferenceHealthV3, ...]:
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
