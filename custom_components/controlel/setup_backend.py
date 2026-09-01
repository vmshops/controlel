"""Shared Home Assistant composition for Setup storage and activation."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import partial
from importlib import import_module
from typing import Any, cast

from pydantic import BaseModel

from controlel.application.configuration.heating_setup_adapter import (
    HEATING_SETUP_SCHEMA_VERSION,
    HeatingSetupPayload,
)
from controlel.application.setup import (
    ActivationAttempt,
    ActivationCoordinator,
    ActivationState,
    ActiveReference,
    CandidateRuntimeReady,
    CanonicalConfigurationRevision,
    DiscoverySnapshot,
    LoadedRuntimeConfiguration,
)
from controlel.application.setup.repository import ScopeKey
from controlel.infrastructure.home_assistant import (
    ACTIVE_REFERENCE_KEY,
    SETUP_STORAGE_VERSION,
    ConfigEntryActiveReferenceStore,
    HeatingSetupHostService,
    HomeAssistantDiscoveryAdapter,
    HomeAssistantSetupRepository,
    LegacyConfigurationStatusDTO,
)

from .canonical_v3_service import HomeAssistantCanonicalConfigurationV3Service
from .const import (
    DEFAULT_HEAT_DEMAND_CONFIRMATION_DURATION,
    DEFAULT_HEATING_TURN_OFF_DIFFERENTIAL,
    DEFAULT_HEATING_TURN_ON_DIFFERENTIAL,
    DEFAULT_INDETERMINATE_GRACE_PERIOD,
    DEFAULT_INDETERMINATE_TIMEOUT_ACTION,
    DEFAULT_MAX_FUTURE_SKEW,
    DEFAULT_MINIMUM_HEATING_OFF_TIME,
    DEFAULT_MINIMUM_HEATING_ON_TIME,
    DEFAULT_PRIMARY_MEASUREMENT_MAX_AGE,
    DEFAULT_TARGET_TEMPERATURE,
    DOMAIN,
)
from .core_capabilities import water_safety_core_available

_SETUP_CACHE_KEY = f"{DOMAIN}_setup_backend"
_SETUP_SERVICES_CACHE_KEY = f"{DOMAIN}_setup_services"
_LIFECYCLE_DATA_KEYS = frozenset({ACTIVE_REFERENCE_KEY})
_HEATING_MODULE_KEY = "heating"
_WATER_SAFETY_MODULE_KEY = "water_safety"


def _json_default(value: object) -> object:
    """Convert a Core model default into its public JSON representation."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    return value


def canonical_heating_setup_defaults() -> dict[str, object]:
    """Return complete Core defaults plus the native HA recommendations."""

    defaults = {
        name: _json_default(field.get_default(call_default_factory=True))
        for name, field in HeatingSetupPayload.model_fields.items()
        if not field.is_required()
    }
    defaults.update(
        {
            "target_temperature_celsius": DEFAULT_TARGET_TEMPERATURE,
            "primary_measurement_max_age_seconds": DEFAULT_PRIMARY_MEASUREMENT_MAX_AGE,
            "maximum_future_skew_seconds": DEFAULT_MAX_FUTURE_SKEW,
            "indeterminate_grace_period_seconds": DEFAULT_INDETERMINATE_GRACE_PERIOD,
            "indeterminate_timeout_action": DEFAULT_INDETERMINATE_TIMEOUT_ACTION,
            "heating_turn_on_differential_celsius": DEFAULT_HEATING_TURN_ON_DIFFERENTIAL,
            "heating_turn_off_differential_celsius": DEFAULT_HEATING_TURN_OFF_DIFFERENTIAL,
            "heat_demand_confirmation_seconds": DEFAULT_HEAT_DEMAND_CONFIRMATION_DURATION,
            "minimum_heating_on_seconds": DEFAULT_MINIMUM_HEATING_ON_TIME,
            "minimum_heating_off_seconds": DEFAULT_MINIMUM_HEATING_OFF_TIME,
        }
    )
    return defaults


class _SynchronousRepositoryBridge:
    """Let the synchronous Core coordinator use the HA event-loop repository."""

    def __init__(self, loop: asyncio.AbstractEventLoop, repository: HomeAssistantSetupRepository) -> None:
        self._loop = loop
        self._repository = repository

    def _run[T](self, awaitable: Coroutine[Any, Any, T]) -> T:
        return asyncio.run_coroutine_threadsafe(awaitable, self._loop).result()

    def add_canonical_revision(self, revision: CanonicalConfigurationRevision) -> None:
        self._run(self._repository.add_canonical_revision(revision))

    def get_canonical_revision(self, revision_id: str) -> CanonicalConfigurationRevision:
        return cast(
            CanonicalConfigurationRevision,
            self._run(self._repository.get_canonical_revision(revision_id)),
        )

    def get_active_reference(self, scope: ScopeKey) -> ActiveReference | None:
        return self._run(self._repository.get_active_reference(scope))

    def compare_and_swap_active_reference(
        self,
        *,
        scope: ScopeKey,
        expected_revision_id: str | None,
        expected_generation: int,
        replacement: ActiveReference,
    ) -> None:
        self._run(
            self._repository.compare_and_swap_active_reference(
                scope=scope,
                expected_revision_id=expected_revision_id,
                expected_generation=expected_generation,
                replacement=replacement,
            )
        )

    def reserve_activation_attempt(self, attempt: ActivationAttempt) -> None:
        self._run(self._repository.reserve_activation_attempt(attempt))

    def transition_activation_attempt(
        self,
        attempt: ActivationAttempt,
        *,
        expected_state: ActivationState,
        expected_version: int,
    ) -> None:
        self._run(
            self._repository.transition_activation_attempt(
                attempt,
                expected_state=expected_state,
                expected_version=expected_version,
            )
        )

    def get_activation_attempt(self, attempt_id: str) -> ActivationAttempt:
        return self._run(self._repository.get_activation_attempt(attempt_id))

    def list_non_terminal_attempts(self) -> tuple[ActivationAttempt, ...]:
        return self._run(self._repository.list_non_terminal_attempts())


class HomeAssistantActivationCoordinator:
    """Async HA facade over the released synchronous Core coordinator."""

    def __init__(self, hass: Any, repository: HomeAssistantSetupRepository) -> None:
        bridge = _SynchronousRepositoryBridge(hass.loop, repository)
        self._hass = hass
        supported_module_schema_versions: dict[str, set[int]] = {"heating": {HEATING_SETUP_SCHEMA_VERSION, 3}}
        if water_safety_core_available():
            from controlel.application.configuration.water_safety_setup_adapter import (
                WATER_SAFETY_SETUP_SCHEMA_VERSION,
            )

            supported_module_schema_versions[_WATER_SAFETY_MODULE_KEY] = {WATER_SAFETY_SETUP_SCHEMA_VERSION}
        self._coordinator = ActivationCoordinator(
            bridge,
            bridge,
            supported_module_schema_versions=supported_module_schema_versions,
        )

    async def _call(self, operation: Any, *args: Any, **kwargs: Any) -> Any:
        return await self._hass.async_add_executor_job(partial(operation, *args, **kwargs))

    async def prepare(self, revision_id: str, *, attempt_id: str, prepared_at: datetime) -> ActivationAttempt:
        return cast(
            ActivationAttempt,
            await self._call(self._coordinator.prepare, revision_id, attempt_id=attempt_id, prepared_at=prepared_at),
        )

    async def begin_applying(self, attempt_id: str, *, applying_at: datetime) -> ActivationAttempt:
        return cast(
            ActivationAttempt,
            await self._call(self._coordinator.begin_applying, attempt_id, applying_at=applying_at),
        )

    async def record_candidate_runtime_ready(
        self,
        attempt_id: str,
        *,
        candidate_ready: CandidateRuntimeReady,
    ) -> ActivationAttempt:
        return cast(
            ActivationAttempt,
            await self._call(
                self._coordinator.record_candidate_runtime_ready,
                attempt_id,
                candidate_ready=candidate_ready,
            ),
        )

    async def commit(self, attempt_id: str, *, committed_at: datetime) -> ActivationAttempt:
        return cast(
            ActivationAttempt,
            await self._call(self._coordinator.commit, attempt_id, committed_at=committed_at),
        )

    async def record_failed_application(
        self,
        attempt_id: str,
        *,
        completed_at: datetime,
        failure_code: str,
        rollback_succeeded: bool,
        rollback_runtime_stamp: LoadedRuntimeConfiguration | None = None,
    ) -> ActivationAttempt:
        return cast(
            ActivationAttempt,
            await self._call(
                self._coordinator.record_failed_application,
                attempt_id,
                completed_at=completed_at,
                failure_code=failure_code,
                rollback_succeeded=rollback_succeeded,
                rollback_runtime_stamp=rollback_runtime_stamp,
            ),
        )

    async def recover_interrupted(
        self,
        attempt_id: str,
        *,
        recovered_at: datetime,
        rollback_succeeded: bool,
        rollback_runtime_stamp: LoadedRuntimeConfiguration | None = None,
    ) -> ActivationAttempt:
        return cast(
            ActivationAttempt,
            await self._call(
                self._coordinator.recover_interrupted,
                attempt_id,
                recovered_at=recovered_at,
                rollback_succeeded=rollback_succeeded,
                rollback_runtime_stamp=rollback_runtime_stamp,
            ),
        )


@dataclass(frozen=True)
class SetupBackend:
    service: HeatingSetupHostService
    configuration_v3: HomeAssistantCanonicalConfigurationV3Service
    repository: HomeAssistantSetupRepository
    activation: HomeAssistantActivationCoordinator
    activation_lock: asyncio.Lock


def _legacy_status(entry: Any) -> LegacyConfigurationStatusDTO:
    data_keys = set(entry.data)
    options = dict(entry.options)
    legacy_present = bool(data_keys - _LIFECYCLE_DATA_KEYS or options)
    return LegacyConfigurationStatusDTO(
        present=legacy_present,
        conversion_available=False,
        silently_merged=False,
        reason_code="setup.legacy_configuration_present" if legacy_present else None,
    )


async def _repository_for_entry(hass: Any, entry: Any) -> HomeAssistantSetupRepository:
    storage_module = import_module("homeassistant.helpers.storage")
    store_type = getattr(storage_module, "Store")
    store = cast(Any, store_type(hass, SETUP_STORAGE_VERSION, f"{DOMAIN}.setup.{entry.entry_id}"))

    def update_entry_data(data: Mapping[str, object]) -> None:
        hass.config_entries.async_update_entry(entry, data=dict(data), options={})

    active_references = ConfigEntryActiveReferenceStore(entry, update_entry_data)
    return HomeAssistantSetupRepository(store, active_references)


async def async_get_setup_backend(hass: Any, entry: Any) -> SetupBackend:
    """Return the one shared setup service/repository for this config entry."""

    cache = hass.data.setdefault(_SETUP_CACHE_KEY, {})
    existing = cache.get(entry.entry_id)
    if isinstance(existing, SetupBackend):
        return existing

    repository = await _repository_for_entry(hass, entry)

    async def snapshot_loader(snapshot_id: str, captured_at: datetime) -> DiscoverySnapshot:
        return await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
            hass,
            snapshot_id=snapshot_id,
            captured_at=captured_at,
        )

    service = HeatingSetupHostService(
        repository,
        snapshot_loader,
        legacy_configuration=_legacy_status(entry),
    )
    backend = SetupBackend(
        service=service,
        configuration_v3=HomeAssistantCanonicalConfigurationV3Service(hass, entry, repository),
        repository=repository,
        activation=HomeAssistantActivationCoordinator(hass, repository),
        activation_lock=asyncio.Lock(),
    )
    cache[entry.entry_id] = backend
    return backend


async def async_get_setup_service(
    hass: Any,
    entry: Any,
    *,
    module_key: str = _HEATING_MODULE_KEY,
) -> Any:
    """Return the shared setup service/repository for this config entry and module."""

    if module_key == _HEATING_MODULE_KEY:
        return (await async_get_setup_backend(hass, entry)).service

    service_cache = hass.data.setdefault(_SETUP_SERVICES_CACHE_KEY, {})
    entry_cache = service_cache.setdefault(entry.entry_id, {})
    existing = entry_cache.get(module_key)
    if existing is not None:
        return existing

    repository = (await async_get_setup_backend(hass, entry)).repository
    legacy_status = _legacy_status(entry)

    if module_key == _WATER_SAFETY_MODULE_KEY:
        if not water_safety_core_available():
            raise ValueError("Water Safety setup requires Controlel core with water_safety APIs")
        from controlel.infrastructure.home_assistant import WaterSafetySetupHostService
        from controlel.infrastructure.home_assistant.water_safety_discovery import async_snapshot_with_notify_services

        async def water_snapshot_loader(snapshot_id: str, captured_at: datetime) -> DiscoverySnapshot:
            return await async_snapshot_with_notify_services(
                hass,
                snapshot_id=snapshot_id,
                captured_at=captured_at,
            )

        service = WaterSafetySetupHostService(
            repository,
            water_snapshot_loader,
            legacy_configuration=legacy_status,
        )
    else:
        raise ValueError(f"unsupported setup module_key: {module_key}")

    entry_cache[module_key] = service
    return service
