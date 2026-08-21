"""End-to-end Home Assistant Setup host and durable repository tests."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import wraps
from types import SimpleNamespace
from typing import Any

import pytest

from controlel.application.configuration.heating_setup_adapter import (
    PRIMARY_TEMPERATURE_ROLE,
    SOURCE_DISABLE_TARGET_ROLE,
    SOURCE_ENABLE_TARGET_ROLE,
)
from controlel.application.setup import (
    ActivationAttempt,
    ActivationState,
    ActiveReference,
    SetupConflictError,
    SetupNotFoundError,
)
from controlel.infrastructure.home_assistant import (
    ACTIVE_REFERENCE_KEY,
    ConfigEntryActiveReferenceStore,
    HeatingBindingSelectionRequest,
    HeatingSetupHostService,
    HomeAssistantDiscoveryAdapter,
    HomeAssistantSetupRepository,
    LegacyConfigurationStatusDTO,
    SetupValidationStatus,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def async_test(function):
    @wraps(function)
    def run(*args: Any, **kwargs: Any) -> None:
        asyncio.run(function(*args, **kwargs))

    return run


class MemoryHAStore:
    """JSON-roundtrip-like stand-in for Home Assistant Store."""

    def __init__(self) -> None:
        self.data: dict[str, object] | None = None

    async def async_load(self) -> dict[str, object] | None:
        return deepcopy(self.data)

    async def async_save(self, data: object) -> None:
        assert isinstance(data, dict)
        self.data = deepcopy(data)


class FakeConfigEntry:
    def __init__(self, data: dict[str, object] | None = None, options: dict[str, object] | None = None) -> None:
        self.entry_id = "controlel-entry-1"
        self.data = data or {}
        self.options = options or {}


@dataclass(frozen=True)
class Floor:
    floor_id: str


@dataclass(frozen=True)
class Area:
    id: str
    floor_id: str | None


@dataclass(frozen=True)
class Device:
    id: str
    area_id: str | None
    identifiers: frozenset[tuple[str, str]]
    connections: frozenset[tuple[str, str]] = frozenset()
    config_entries: frozenset[str] = frozenset({"provider-entry"})
    config_entries_subentries: dict[str, frozenset[str | None]] | None = None
    via_device_id: str | None = None

    def __post_init__(self) -> None:
        if self.config_entries_subentries is None:
            object.__setattr__(self, "config_entries_subentries", {"provider-entry": frozenset({None})})


@dataclass(frozen=True)
class Entity:
    id: str
    entity_id: str
    domain: str
    platform: str
    unique_id: str
    device_id: str | None
    area_id: str | None = None
    previous_unique_id: str | None = None
    config_entry_id: str | None = "provider-entry"
    config_subentry_id: str | None = None
    device_class: str | None = None
    original_device_class: str | None = None
    unit_of_measurement: str | None = None
    supported_features: int = 0


FLOOR = Floor("ground")
AREA = Area("living", FLOOR.floor_id)
ROOM_DEVICE = Device("room-device", AREA.id, frozenset({("mqtt", "room")}))
SOURCE_DEVICE = Device("source-device", AREA.id, frozenset({("mqtt", "source")}))
TEMPERATURE = Entity(
    "temperature-registry-id",
    "sensor.living_temperature",
    "sensor",
    "mqtt",
    "living-temperature",
    ROOM_DEVICE.id,
    device_class="temperature",
    original_device_class="temperature",
    unit_of_measurement="°C",
)
SOURCE = Entity(
    "source-registry-id",
    "switch.boiler",
    "switch",
    "mqtt",
    "boiler",
    SOURCE_DEVICE.id,
)


def complete_settings() -> dict[str, object]:
    return {
        "zone_id": "living",
        "zone_name": "Living room",
        "sensor_id": "living-temperature",
        "sensor_name": "Living temperature",
        "target_temperature_celsius": 21.0,
        "primary_measurement_max_age_seconds": 300.0,
        "maximum_future_skew_seconds": 5.0,
        "indeterminate_grace_period_seconds": 60.0,
        "source_control_mode": "custom",
        "source_enable": {
            "domain": "vendor_boiler",
            "service": "grant_permission",
            "target_binding_role": SOURCE_ENABLE_TARGET_ROLE,
        },
        "source_disable": {
            "domain": "vendor_boiler",
            "service": "revoke_permission",
            "target_binding_role": SOURCE_DISABLE_TARGET_ROLE,
        },
    }


def repository(
    store: MemoryHAStore,
    entry: FakeConfigEntry,
) -> HomeAssistantSetupRepository:
    def update(data: object) -> None:
        assert isinstance(data, dict)
        entry.data = data

    return HomeAssistantSetupRepository(store, ConfigEntryActiveReferenceStore(entry, update))


def active_reference_store(entry: FakeConfigEntry) -> ConfigEntryActiveReferenceStore:
    def update(data: object) -> None:
        assert isinstance(data, dict)
        entry.data = data

    return ConfigEntryActiveReferenceStore(entry, update)


def service(
    store: MemoryHAStore,
    entry: FakeConfigEntry,
    *,
    legacy: bool = False,
) -> HeatingSetupHostService:
    async def snapshot_loader(snapshot_id: str, captured_at: datetime):
        return HomeAssistantDiscoveryAdapter("ha-installation-id").snapshot(
            snapshot_id=snapshot_id,
            captured_at=captured_at,
            floors=(FLOOR,),
            areas=(AREA,),
            devices=(ROOM_DEVICE, SOURCE_DEVICE),
            entities=(TEMPERATURE, SOURCE),
        )

    return HeatingSetupHostService(
        repository(store, entry),
        snapshot_loader,
        legacy_configuration=LegacyConfigurationStatusDTO(
            present=legacy,
            reason_code="setup.legacy_configuration_present" if legacy else None,
        ),
    )


async def complete_selections(
    host: HeatingSetupHostService,
    at: datetime,
) -> tuple[HeatingBindingSelectionRequest, ...]:
    recommendations = await host.get_recommendations(snapshot_id="snapshot-1", captured_at=at)
    by_role = {item.role: item for item in recommendations}
    return tuple(
        HeatingBindingSelectionRequest(
            role=role,
            candidate_id=by_role[role].recommended.candidate_id,
            user_confirmed=True,
        )
        for role in (PRIMARY_TEMPERATURE_ROLE, SOURCE_ENABLE_TARGET_ROLE, SOURCE_DISABLE_TARGET_ROLE)
        if by_role[role].recommended is not None
    )


@async_test
async def test_incomplete_draft_persists_and_reopens_identically_after_host_restart() -> None:
    store = MemoryHAStore()
    entry = FakeConfigEntry()
    first_host = service(store, entry)

    created = await first_host.start_new_heating_setup(
        draft_id="draft-1",
        module_instance_id="main-heating",
        created_at=NOW,
        snapshot_id="snapshot-1",
        report_id="report-1",
    )
    restarted_host = service(store, entry)
    reopened = await restarted_host.reopen_heating_setup(
        "draft-1",
        snapshot_id="snapshot-1",
        captured_at=NOW,
    )

    assert created == reopened
    assert reopened.incomplete is True
    assert reopened.activation_ready is False
    assert reopened.validation_status is SetupValidationStatus.CURRENT
    assert reopened.blocking_issue_count > 0
    assert reopened.recommendations
    assert reopened.selections == ()


@async_test
async def test_stale_draft_update_is_rejected_and_current_validation_survives_restart() -> None:
    store = MemoryHAStore()
    entry = FakeConfigEntry()
    host = service(store, entry)
    await host.start_new_heating_setup(
        draft_id="draft-1",
        module_instance_id="main-heating",
        created_at=NOW,
        snapshot_id="snapshot-1",
        report_id="report-1",
    )
    selections = await complete_selections(host, NOW + timedelta(minutes=1))
    updated_at = NOW + timedelta(minutes=1)
    updated = await host.update_heating_draft(
        "draft-1",
        expected_revision=1,
        updated_at=updated_at,
        snapshot_id="snapshot-1",
        report_id="report-2",
        settings=complete_settings(),
        selections=selections,
    )

    with pytest.raises(SetupConflictError, match="draft changed before update"):
        await host.update_heating_draft(
            "draft-1",
            expected_revision=1,
            updated_at=updated_at + timedelta(seconds=1),
            snapshot_id="snapshot-2",
            report_id="report-stale",
            settings=complete_settings(),
            selections=selections,
        )

    reopened = await service(store, entry).reopen_heating_setup(
        "draft-1",
        snapshot_id="snapshot-1",
        captured_at=updated_at,
    )
    assert reopened == updated
    assert reopened.incomplete is False
    assert reopened.activation_ready is True
    assert reopened.validation_report_id == "report-2"
    assert all(selection.user_confirmed for selection in reopened.selections)


@async_test
async def test_durable_draft_delete_requires_current_revision() -> None:
    store = MemoryHAStore()
    entry = FakeConfigEntry()
    host = service(store, entry)
    await host.start_new_heating_setup(
        draft_id="draft-1",
        module_instance_id="main-heating",
        created_at=NOW,
        snapshot_id="snapshot-1",
        report_id="report-1",
    )
    repo = repository(store, entry)

    with pytest.raises(SetupConflictError, match="draft changed before deletion"):
        await repo.delete_draft("draft-1", expected_revision=0)
    await repo.delete_draft("draft-1", expected_revision=1)
    with pytest.raises(SetupNotFoundError, match="draft not found"):
        await repository(store, entry).get_draft("draft-1")


@async_test
async def test_canonicalization_is_durable_but_does_not_activate_or_write_settings_to_entry() -> None:
    store = MemoryHAStore()
    entry = FakeConfigEntry()
    host = service(store, entry)
    await host.start_new_heating_setup(
        draft_id="draft-1",
        module_instance_id="main-heating",
        created_at=NOW,
        snapshot_id="snapshot-1",
        report_id="report-1",
    )
    updated_at = NOW + timedelta(minutes=1)
    selections = await complete_selections(host, updated_at)
    await host.update_heating_draft(
        "draft-1",
        expected_revision=1,
        updated_at=updated_at,
        snapshot_id="snapshot-1",
        report_id="report-2",
        settings=complete_settings(),
        selections=selections,
    )

    canonicalized = await host.canonicalize_heating_draft(
        "draft-1",
        snapshot_id="snapshot-2",
        created_at=NOW + timedelta(minutes=2),
        validation_report_id="report-3",
        configuration_id="configuration-1",
        revision_id="canonical-1",
        revision=1,
        actor="user:owner",
        source="setup_host",
        change_kind="CREATE",
        reason="initial_setup",
        core_version="0.12.0",
        integration_version="0.12.0",
    )

    restarted_repository = repository(store, entry)
    persisted = await restarted_repository.get_canonical_revision("canonical-1")
    assert canonicalized.canonical_revision_id == persisted.revision_id
    assert canonicalized.active_revision_id is None
    assert await restarted_repository.get_active_reference(("ha-installation-id", "heating", "main-heating")) is None
    assert entry.data == {}


@async_test
async def test_config_entry_active_reference_is_cas_only_and_attempts_survive_restart() -> None:
    store = MemoryHAStore()
    entry = FakeConfigEntry()
    host = service(store, entry)
    await host.start_new_heating_setup(
        draft_id="draft-1",
        module_instance_id="main-heating",
        created_at=NOW,
        snapshot_id="snapshot-1",
        report_id="report-1",
    )
    selections = await complete_selections(host, NOW + timedelta(minutes=1))
    await host.update_heating_draft(
        "draft-1",
        expected_revision=1,
        updated_at=NOW + timedelta(minutes=1),
        snapshot_id="snapshot-1",
        report_id="report-2",
        settings=complete_settings(),
        selections=selections,
    )
    await host.canonicalize_heating_draft(
        "draft-1",
        snapshot_id="snapshot-2",
        created_at=NOW + timedelta(minutes=2),
        validation_report_id="report-3",
        configuration_id="configuration-1",
        revision_id="canonical-1",
        revision=1,
        actor="user:owner",
        source="setup_host",
        change_kind="CREATE",
        reason="initial_setup",
        core_version="0.12.0",
    )
    repo = repository(store, entry)
    canonical = await repo.get_canonical_revision("canonical-1")
    scope = ("ha-installation-id", "heating", "main-heating")
    replacement = ActiveReference(
        environment_id=scope[0],
        module_key=scope[1],
        module_instance_id=scope[2],
        canonical_revision_id=canonical.revision_id,
        semantic_configuration_fingerprint=canonical.semantic_configuration_fingerprint,
        generation=1,
        committing_operation_id="attempt-1",
    )
    await repo.compare_and_swap_active_reference(
        scope=scope,
        expected_revision_id=None,
        expected_generation=0,
        replacement=replacement,
    )
    with pytest.raises(SetupConflictError, match="active reference changed"):
        await repo.compare_and_swap_active_reference(
            scope=scope,
            expected_revision_id=None,
            expected_generation=0,
            replacement=replacement,
        )
    attempt = ActivationAttempt(
        attempt_id="attempt-1",
        environment_id=scope[0],
        module_key=scope[1],
        module_instance_id=scope[2],
        state=ActivationState.PREPARED,
        candidate_revision_id=canonical.revision_id,
        candidate_semantic_fingerprint=canonical.semantic_configuration_fingerprint,
        expected_active_generation=0,
        prepared_at=NOW,
    )
    await repo.reserve_activation_attempt(attempt)
    applying = ActivationAttempt.model_validate(
        {
            **attempt.model_dump(mode="json"),
            "version": 2,
            "state": "APPLYING",
            "applying_at": (NOW + timedelta(seconds=1)).isoformat(),
        }
    )
    await repo.transition_activation_attempt(
        applying,
        expected_state=ActivationState.PREPARED,
        expected_version=1,
    )
    with pytest.raises(SetupConflictError, match="changed before transition"):
        await repo.transition_activation_attempt(
            applying,
            expected_state=ActivationState.PREPARED,
            expected_version=1,
        )

    restarted = repository(store, entry)
    assert await restarted.get_active_reference(scope) == replacement
    assert await restarted.get_activation_attempt("attempt-1") == applying
    assert set(entry.data) == {ACTIVE_REFERENCE_KEY}
    assert "module_payload" not in entry.data


@async_test
async def test_legacy_configuration_is_reported_but_never_merged_into_new_draft() -> None:
    store = MemoryHAStore()
    entry = FakeConfigEntry(data={"sensor_id": "legacy-sensor"}, options={"target_temperature": 24.0})
    host = service(store, entry, legacy=True)

    session = await host.start_new_heating_setup(
        draft_id="draft-1",
        module_instance_id="main-heating",
        created_at=NOW,
        snapshot_id="snapshot-1",
        report_id="report-1",
    )

    assert session.legacy_configuration.present is True
    assert session.legacy_configuration.conversion_available is False
    assert session.legacy_configuration.silently_merged is False
    assert dict(session.settings) == {}
    assert entry.data == {"sensor_id": "legacy-sensor"}
    assert entry.options == {"target_temperature": 24.0}


def test_legacy_settings_must_be_converted_before_config_entry_can_select_canonical_authority() -> None:
    entry = FakeConfigEntry(data={"sensor_id": "legacy-sensor"})
    reference = ActiveReference(
        environment_id="ha-installation-id",
        module_key="heating",
        module_instance_id="main-heating",
        canonical_revision_id="canonical-1",
        semantic_configuration_fingerprint="a" * 64,
        generation=1,
        committing_operation_id="attempt-1",
    )

    with pytest.raises(SetupConflictError, match="explicitly converted"):
        active_reference_store(entry).set(reference)
    assert entry.data == {"sensor_id": "legacy-sensor"}


@async_test
async def test_lazy_ha_composition_reuses_store_backed_service_and_reports_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.controlel import setup_backend

    store = MemoryHAStore()
    entry = FakeConfigEntry(data={"sensor_id": "legacy-sensor"})

    class FakeConfigEntries:
        @staticmethod
        def async_update_entry(target: FakeConfigEntry, *, data: dict[str, object]) -> None:
            target.data = data

    hass = SimpleNamespace(data={}, config_entries=FakeConfigEntries())
    monkeypatch.setattr(
        setup_backend,
        "import_module",
        lambda name: SimpleNamespace(Store=lambda *args: store),
    )

    class FakeDiscoveryAdapter:
        @classmethod
        async def async_snapshot_from_hass(
            cls,
            hass_object: object,
            *,
            snapshot_id: str,
            captured_at: datetime,
        ):
            assert hass_object is hass
            return HomeAssistantDiscoveryAdapter("ha-installation-id").snapshot(
                snapshot_id=snapshot_id,
                captured_at=captured_at,
                floors=(FLOOR,),
                areas=(AREA,),
                devices=(ROOM_DEVICE, SOURCE_DEVICE),
                entities=(TEMPERATURE, SOURCE),
            )

    monkeypatch.setattr(setup_backend, "HomeAssistantDiscoveryAdapter", FakeDiscoveryAdapter)
    first = await setup_backend.async_get_setup_service(hass, entry)
    second = await setup_backend.async_get_setup_service(hass, entry)
    session = await first.start_new_heating_setup(
        draft_id="draft-1",
        module_instance_id="main-heating",
        created_at=NOW,
        snapshot_id="snapshot-1",
        report_id="report-1",
    )

    assert first is second
    assert session.legacy_configuration.present is True
    assert session.legacy_configuration.silently_merged is False
    assert dict(session.settings) == {}
    assert entry.data == {"sensor_id": "legacy-sensor"}


@async_test
async def test_frontend_dto_is_normalized_and_contains_resume_state_without_ha_classes() -> None:
    store = MemoryHAStore()
    session = await service(store, FakeConfigEntry()).start_new_heating_setup(
        draft_id="draft-1",
        module_instance_id="main-heating",
        created_at=NOW,
        snapshot_id="snapshot-1",
        report_id="report-1",
    )

    dumped = session.model_dump(mode="json")
    assert dumped["draft_id"] == "draft-1"
    assert dumped["validation_status"] == "CURRENT"
    assert dumped["blocking_issue_count"] == len(
        [issue for issue in dumped["validation_issues"] if issue["severity"] == "ERROR"]
    )
    assert dumped["discovery"]["object_counts"] == {
        "home_assistant.area": 1,
        "home_assistant.device": 2,
        "home_assistant.entity": 2,
        "home_assistant.floor": 1,
    }
    assert all(isinstance(item, dict) for item in dumped["discovery"]["objects"])
