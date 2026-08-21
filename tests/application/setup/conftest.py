from datetime import UTC, datetime

import pytest

from controlel.application.configuration.heating_setup_adapter import (
    PRIMARY_TEMPERATURE_ROLE,
    SOURCE_DISABLE_TARGET_ROLE,
    SOURCE_ENABLE_TARGET_ROLE,
    HeatingSetupAdapter,
)
from controlel.application.setup import (
    BindingSelection,
    CanonicalConfigurationRevision,
    DraftRevision,
    IdentityQuality,
    ProviderReference,
    SelectionOrigin,
)

NOW = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)


def provider_reference(native_id: str, locator: str) -> ProviderReference:
    return ProviderReference(
        provider="home_assistant",
        provider_instance_id="ha-home",
        object_kind="home_assistant.entity",
        native_id=native_id,
        identity_quality=IdentityQuality.STABLE,
        current_locator=locator,
        device_registry_id="device-boiler" if "source" in native_id else "device-room",
        area_id="living-room",
        floor_id="ground-floor",
        recovery_evidence={
            "platform": "test",
            "unique_id": f"unique-{native_id}",
            "config_entry_id": "entry-1",
        },
    )


def complete_draft(*, draft_id: str = "draft-1", revision: int = 1) -> DraftRevision:
    bindings = (
        BindingSelection(
            role=PRIMARY_TEMPERATURE_ROLE,
            reference=provider_reference("entity-temperature", "sensor.living_room"),
            selection_origin=SelectionOrigin.MANUAL,
            user_confirmed=True,
        ),
        BindingSelection(
            role=SOURCE_ENABLE_TARGET_ROLE,
            reference=provider_reference("entity-source", "switch.boiler"),
            selection_origin=SelectionOrigin.MANUAL,
            user_confirmed=True,
        ),
        BindingSelection(
            role=SOURCE_DISABLE_TARGET_ROLE,
            reference=provider_reference("entity-source", "switch.boiler"),
            selection_origin=SelectionOrigin.MANUAL,
            user_confirmed=True,
        ),
    )
    return DraftRevision(
        draft_id=draft_id,
        revision=revision,
        environment_id="home",
        module_key="heating",
        module_instance_id="main-heating",
        module_schema_version=1,
        created_at=NOW,
        updated_at=NOW,
        settings={
            "zone_id": "living_room",
            "zone_name": "Living room",
            "sensor_id": "living_room_temperature",
            "sensor_name": "Living room temperature",
            "target_temperature_celsius": 21.0,
            "primary_measurement_max_age_seconds": 300.0,
            "maximum_future_skew_seconds": 5.0,
            "indeterminate_grace_period_seconds": 60.0,
            "indeterminate_timeout_action": "disable_heating",
            "source_control_mode": "custom",
            "source_enable": {
                "domain": "vendor_boiler",
                "service": "grant_heat_permission",
                "target_binding_role": SOURCE_ENABLE_TARGET_ROLE,
            },
            "source_disable": {
                "domain": "script",
                "service": "revoke_heat_permission",
                "target_binding_role": SOURCE_DISABLE_TARGET_ROLE,
            },
        },
        bindings=bindings,
    )


@pytest.fixture
def canonical_revision() -> CanonicalConfigurationRevision:
    draft = complete_draft()
    adapter = HeatingSetupAdapter()
    report = adapter.validate(draft, report_id="report-1", evaluated_at=NOW)
    return adapter.canonicalize(
        draft,
        report,
        configuration_id="configuration-1",
        revision_id="canonical-1",
        revision=1,
        provider="home_assistant",
        provider_instance_id="ha-home",
        created_at=NOW,
        actor="user:owner",
        source="setup_api",
        change_kind="CREATE",
        reason="initial_setup",
        core_version="0.11.0",
        integration_version="0.11.0",
    )
