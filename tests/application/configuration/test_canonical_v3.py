"""Canonical configuration v3 ownership, identity, and migration contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from runpy import run_path

import pytest
from pydantic import ValidationError

from controlel.application.configuration.canonical_defaults import (
    NEW_CONFIGURATION_DEBUG_DURATION_SECONDS,
    NEW_CONFIGURATION_HEAT_DEMAND_CONFIRMATION_SECONDS,
    NEW_CONFIGURATION_HEATING_TURN_OFF_DIFFERENTIAL_CELSIUS,
    NEW_CONFIGURATION_HEATING_TURN_ON_DIFFERENTIAL_CELSIUS,
    NEW_CONFIGURATION_INDETERMINATE_GRACE_PERIOD_SECONDS,
    NEW_CONFIGURATION_MAXIMUM_FUTURE_SKEW_SECONDS,
    NEW_CONFIGURATION_MINIMUM_HEATING_OFF_SECONDS,
    NEW_CONFIGURATION_MINIMUM_HEATING_ON_SECONDS,
    NEW_CONFIGURATION_PRIMARY_MEASUREMENT_MAX_AGE_SECONDS,
    NEW_CONFIGURATION_TARGET_TEMPERATURE_CELSIUS,
)
from controlel.application.configuration.canonical_v3 import (
    CANONICAL_CONFIGURATION_SCHEMA_VERSION_V3,
    CanonicalConfigurationRevisionV3,
    ConfigurationDefaultPolicyV3,
    ConfigurationEditabilityV3,
    ConfigurationOwnerV3,
    DiagnosticsConfigurationV3,
    HeatingGlobalConfigurationV3,
    HeatSourceCommandStrategyV3,
    HeatSourceObservationBindingsV3,
    HeatSourceProtectionPolicyV3,
    NotificationsConfigurationV3,
    PrimaryTemperatureSensorV3,
    ProviderServiceCallV3,
    ZoneDemandPolicyV3,
    ZoneHeatDeliveryConfigurationV3,
    canonical_field_registry_v3,
)
from controlel.application.configuration.canonical_v3_authoring import (
    GREENFIELD_HEAT_SOURCE_ID_V3,
    GREENFIELD_PRIMARY_SENSOR_ID_V3,
    GREENFIELD_ZONE_ID_V3,
    GreenfieldHeatingBindingsV3,
    author_greenfield_heating_scopes_v3,
    conversion_configuration_id_v3,
)
from controlel.application.configuration.canonical_v3_migration import (
    CanonicalV2ToV3MigrationError,
    migrate_heating_v2_revision_to_v3,
)
from controlel.application.configuration.heating_setup_adapter import (
    HEATING_SETUP_SCHEMA_VERSION,
    PRIMARY_TEMPERATURE_ROLE,
    REPORTED_SOURCE_STATE_ROLE,
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

NOW = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
MIGRATED_AT = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


def _reference(
    native_id: str,
    locator: str,
    *,
    area_id: str | None = "ha-living-area",
    floor_id: str | None = "ha-ground-floor",
    identity_quality: IdentityQuality = IdentityQuality.STABLE,
) -> ProviderReference:
    return ProviderReference(
        provider="home_assistant",
        provider_instance_id="ha-home",
        object_kind=(
            "home_assistant.entity" if identity_quality is IdentityQuality.STABLE else "home_assistant.endpoint"
        ),
        native_id=native_id if identity_quality is IdentityQuality.STABLE else None,
        identity_quality=identity_quality,
        current_locator=locator,
        area_id=area_id,
        floor_id=floor_id,
        recovery_evidence={
            "domain": locator.partition(".")[0],
            "platform": "test",
            "unique_id": f"unique-{native_id}",
        },
    )


def _binding(role: str, reference: ProviderReference) -> BindingSelection:
    return BindingSelection(
        role=role,
        reference=reference,
        selection_origin=SelectionOrigin.MANUAL,
        user_confirmed=True,
    )


def _v2_revision(
    *,
    zero_legacy_values: bool = False,
    diagnostic_profile: str = "detailed",
    diagnostic_profile_before_debug: str = "basic",
    assist_policy: str = "no_assist",
    primary_reference: ProviderReference | None = None,
    source_reference: ProviderReference | None = None,
    zone_id: str = "controlel_living_zone",
    sensor_id: str = "controlel_primary_sensor",
) -> CanonicalConfigurationRevision:
    sensor = primary_reference or _reference("registry-sensor-42", "sensor.living_temperature")
    source = source_reference or _reference("registry-source-7", "switch.boiler_relay")
    bindings = (
        _binding(PRIMARY_TEMPERATURE_ROLE, sensor),
        _binding(SOURCE_ENABLE_TARGET_ROLE, source),
        _binding(SOURCE_DISABLE_TARGET_ROLE, source),
        _binding(REPORTED_SOURCE_STATE_ROLE, source),
    )
    zero = 0.0 if zero_legacy_values else None
    settings = {
        "zone_id": zone_id,
        "zone_name": "Living room",
        "sensor_id": sensor_id,
        "sensor_name": "Room thermometer",
        "target_temperature_celsius": 19.5 if zero_legacy_values else 21.0,
        "primary_measurement_max_age_seconds": 333.0 if zero_legacy_values else 900.0,
        "maximum_future_skew_seconds": 7.0 if zero_legacy_values else 30.0,
        "indeterminate_grace_period_seconds": zero if zero is not None else 120.0,
        "indeterminate_timeout_action": "disable_heating",
        "heating_turn_on_differential_celsius": zero if zero is not None else 0.3,
        "heating_turn_off_differential_celsius": zero if zero is not None else 0.1,
        "heat_demand_confirmation_seconds": zero if zero is not None else 120.0,
        "minimum_heating_on_seconds": zero if zero is not None else 600.0,
        "minimum_heating_off_seconds": zero if zero is not None else 300.0,
        "source_control_mode": "simple",
        "source_enable": {
            "domain": "switch",
            "service": "turn_on",
            "target_binding_role": SOURCE_ENABLE_TARGET_ROLE,
        },
        "source_disable": {
            "domain": "switch",
            "service": "turn_off",
            "target_binding_role": SOURCE_DISABLE_TARGET_ROLE,
        },
        "reported_source_state_binding_role": REPORTED_SOURCE_STATE_ROLE,
        "heat_delivery_mode": "unmanaged",
        "heat_delivery_actuator_binding_role": None,
        "heat_delivery_ownership": "device_owned",
        "heat_delivery_assist_policy": assist_policy,
        "heat_delivery_assist_target_celsius": 30.0,
        "diagnostic_policy": {
            "diagnostic_profile": diagnostic_profile,
            "configured_debug_duration_seconds": 1_234.0,
            "debug_until_changed": True,
            "diagnostic_profile_before_debug": diagnostic_profile_before_debug,
        },
        "notification_policy": {
            "enabled": True,
            "recipients": [
                {
                    "recipient_id": "owner_phone",
                    "transport": "home_assistant_notify",
                    "target": "notify.owner_phone",
                    "enabled": True,
                    "minimum_level": "operational",
                    "categories": ["runtime", "safety"],
                }
            ],
            "maximum_per_window": 3,
            "rate_window_seconds": 91.0,
            "critical_maximum_per_window": 5,
            "critical_rate_window_seconds": 92.0,
            "history_capacity": 77,
        },
    }
    draft = DraftRevision(
        draft_id="v2-draft",
        revision=1,
        environment_id="ha-home",
        module_key="heating",
        module_instance_id="main-heating",
        module_schema_version=HEATING_SETUP_SCHEMA_VERSION,
        created_at=NOW,
        updated_at=NOW,
        settings=settings,
        bindings=bindings,
    )
    adapter = HeatingSetupAdapter()
    report = adapter.validate(draft, report_id="v2-report", evaluated_at=NOW)
    assert report.activation_ready
    return adapter.canonicalize(
        draft,
        report,
        configuration_id="configuration-1",
        revision_id="v2-revision-1",
        revision=4,
        provider="home_assistant",
        provider_instance_id="ha-home",
        created_at=NOW,
        actor="user:owner",
        source="setup_api",
        change_kind="UPDATE",
        reason="v2_fixture",
        core_version="0.16.0",
        integration_version="0.13.0",
    )


def _migrate(revision: CanonicalConfigurationRevision | None = None) -> CanonicalConfigurationRevisionV3:
    return migrate_heating_v2_revision_to_v3(
        revision or _v2_revision(),
        revision_id="v3-revision-5",
        created_at=MIGRATED_AT,
    )


def test_v3_has_separate_owned_scopes_and_one_current_zone_source() -> None:
    revision = _migrate()
    document = revision.model_dump(mode="json", by_alias=True)

    assert document["schema_version"] == CANONICAL_CONFIGURATION_SCHEMA_VERSION_V3
    assert set(document) >= {"heating", "diagnostics", "notifications"}
    assert set(document["heating"]) == {"global", "zones", "heat_sources", "heat_delivery"}
    assert "diagnostic_policy" not in document["heating"]
    assert "notification_policy" not in document["heating"]
    assert len(document["heating"]["zones"]) == 1
    assert len(document["heating"]["heat_sources"]) == 1
    assert document["heating"]["heat_sources"][0]["protection"]["minimum_heating_on_seconds"] == 600.0
    assert "minimum_heating_on_seconds" not in document["heating"]["zones"][0]


def test_v3_serialization_round_trip_is_canonical_and_hash_checked() -> None:
    revision = _migrate()

    restored = CanonicalConfigurationRevisionV3.model_validate_json(revision.canonical_json())

    assert restored == revision
    assert restored.canonical_json() == revision.canonical_json()
    tampered = revision.model_dump(mode="json", by_alias=True)
    tampered["heating"]["zones"][0]["display_name"] = "Tampered"
    with pytest.raises(ValidationError, match="fingerprint"):
        CanonicalConfigurationRevisionV3.model_validate(tampered)


def test_v2_to_v3_migration_is_deterministic_and_non_activating() -> None:
    source = _v2_revision()

    first = _migrate(source)
    second = _migrate(source)

    assert first == second
    assert first.canonical_json() == second.canonical_json()
    assert first.revision == source.revision + 1
    assert first.parent_revision_id == source.revision_id
    assert first.source == "canonical_v2_to_v3"
    assert "active" not in first.model_dump(mode="json", by_alias=True)
    assert first.module_instance_id == source.module_instance_id
    assert first.scope_key == (source.environment_id, source.module_key, source.module_instance_id)


def test_v2_migration_preserves_explicit_historical_values_and_ha_assist_drift() -> None:
    migrated = _migrate(
        _v2_revision(
            zero_legacy_values=True,
            diagnostic_profile="detailed",
            assist_policy="always_assist_while_heating",
        )
    )
    zone = migrated.heating.zones[0]
    source = migrated.heating.heat_sources[0]
    delivery = migrated.heating.heat_delivery[0]

    assert zone.demand_policy.target_temperature_celsius == 19.5
    assert zone.demand_policy.heating_turn_on_differential_celsius == 0.0
    assert zone.demand_policy.heating_turn_off_differential_celsius == 0.0
    assert zone.demand_policy.heat_demand_confirmation_seconds == 0.0
    assert zone.demand_policy.primary_measurement_max_age_seconds == 333.0
    assert migrated.heating.global_configuration.maximum_future_skew_seconds == 7.0
    assert source.protection.indeterminate_grace_period_seconds == 0.0
    assert source.protection.minimum_heating_on_seconds == 0.0
    assert source.protection.minimum_heating_off_seconds == 0.0
    assert migrated.diagnostics.steady_profile == "detailed"
    assert delivery.assist_policy == "always_assist_while_heating"
    provenance = migrated.migration_provenance["v2_to_v3"]
    assert isinstance(provenance, Mapping)
    assert provenance["historical_values_preserved"] is True
    assert provenance["ha_always_assist_default_drift_preserved"] is True


def test_active_v2_debug_becomes_steady_configuration_without_runtime_state() -> None:
    migrated = _migrate(
        _v2_revision(
            diagnostic_profile="debug",
            diagnostic_profile_before_debug="basic",
        )
    )
    diagnostics = migrated.model_dump(mode="json", by_alias=True)["diagnostics"]

    assert diagnostics == {
        "steady_profile": "basic",
        "debug_policy": {"configured_duration_seconds": 1_234.0, "until_changed": True},
    }
    assert "diagnostic_profile_before_debug" not in diagnostics
    assert "debug_expiry" not in diagnostics


def test_authoritative_new_configuration_defaults_are_consistent() -> None:
    zone = ZoneDemandPolicyV3()
    global_configuration = HeatingGlobalConfigurationV3()
    source = HeatSourceProtectionPolicyV3()
    delivery = ZoneHeatDeliveryConfigurationV3(zone_id="zone_1")
    diagnostics = DiagnosticsConfigurationV3()
    notifications = NotificationsConfigurationV3()

    assert zone.target_temperature_celsius == NEW_CONFIGURATION_TARGET_TEMPERATURE_CELSIUS == 21.0
    assert zone.heating_turn_on_differential_celsius == NEW_CONFIGURATION_HEATING_TURN_ON_DIFFERENTIAL_CELSIUS == 0.3
    assert zone.heating_turn_off_differential_celsius == NEW_CONFIGURATION_HEATING_TURN_OFF_DIFFERENTIAL_CELSIUS == 0.1
    assert zone.heat_demand_confirmation_seconds == NEW_CONFIGURATION_HEAT_DEMAND_CONFIRMATION_SECONDS == 120.0
    assert zone.primary_measurement_max_age_seconds == NEW_CONFIGURATION_PRIMARY_MEASUREMENT_MAX_AGE_SECONDS == 900.0
    assert global_configuration.maximum_future_skew_seconds == NEW_CONFIGURATION_MAXIMUM_FUTURE_SKEW_SECONDS == 30.0
    assert source.indeterminate_grace_period_seconds == NEW_CONFIGURATION_INDETERMINATE_GRACE_PERIOD_SECONDS == 120.0
    assert source.minimum_heating_on_seconds == NEW_CONFIGURATION_MINIMUM_HEATING_ON_SECONDS == 600.0
    assert source.minimum_heating_off_seconds == NEW_CONFIGURATION_MINIMUM_HEATING_OFF_SECONDS == 300.0
    assert delivery.assist_policy == "no_assist"
    assert diagnostics.steady_profile == "basic"
    assert diagnostics.debug_policy.configured_duration_seconds == NEW_CONFIGURATION_DEBUG_DURATION_SECONDS

    repository_root = Path(__file__).resolve().parents[3]
    ha_constants = run_path(str(repository_root / "custom_components" / "controlel" / "const.py"))
    assert ha_constants["DEFAULT_TARGET_TEMPERATURE"] == zone.target_temperature_celsius
    assert ha_constants["DEFAULT_HEATING_TURN_ON_DIFFERENTIAL"] == zone.heating_turn_on_differential_celsius
    assert ha_constants["DEFAULT_HEATING_TURN_OFF_DIFFERENTIAL"] == zone.heating_turn_off_differential_celsius
    assert ha_constants["DEFAULT_HEAT_DEMAND_CONFIRMATION_DURATION"] == zone.heat_demand_confirmation_seconds
    assert ha_constants["DEFAULT_PRIMARY_MEASUREMENT_MAX_AGE"] == zone.primary_measurement_max_age_seconds
    assert ha_constants["DEFAULT_MAX_FUTURE_SKEW"] == global_configuration.maximum_future_skew_seconds
    assert ha_constants["DEFAULT_INDETERMINATE_GRACE_PERIOD"] == source.indeterminate_grace_period_seconds
    assert ha_constants["DEFAULT_MINIMUM_HEATING_ON_TIME"] == source.minimum_heating_on_seconds
    assert ha_constants["DEFAULT_MINIMUM_HEATING_OFF_TIME"] == source.minimum_heating_off_seconds
    assert ha_constants["DEFAULT_DIAGNOSTIC_PROFILE"] == diagnostics.steady_profile
    assert ha_constants["DEFAULT_DEBUG_DURATION"] == diagnostics.debug_policy.configured_duration_seconds
    assert ha_constants["DEFAULT_DEBUG_UNTIL_CHANGED"] == diagnostics.debug_policy.until_changed
    assert ha_constants["DEFAULT_NOTIFICATION_MAXIMUM_PER_WINDOW"] == notifications.maximum_per_window
    assert ha_constants["DEFAULT_NOTIFICATION_RATE_WINDOW_SECONDS"] == notifications.rate_window_seconds
    assert ha_constants["DEFAULT_CRITICAL_NOTIFICATION_MAXIMUM_PER_WINDOW"] == notifications.critical_maximum_per_window
    assert (
        ha_constants["DEFAULT_CRITICAL_NOTIFICATION_RATE_WINDOW_SECONDS"] == notifications.critical_rate_window_seconds
    )
    assert ha_constants["DEFAULT_NOTIFICATION_HISTORY_CAPACITY"] == notifications.history_capacity


def test_greenfield_authoring_uses_canonical_defaults_and_provider_independent_identities() -> None:
    sensor = _reference("registry-sensor-42", "sensor.living_temperature")
    source = _reference("registry-source-7", "switch.boiler_relay")
    scopes = author_greenfield_heating_scopes_v3(
        GreenfieldHeatingBindingsV3(
            zone_display_name="Living room",
            primary_sensor_display_name="Room thermometer",
            topology={"area_reference": None, "floor_reference": None},
            primary_temperature_sensor_reference=sensor,
            heat_source_display_name="Boiler relay",
            heat_source_reference=source,
            command_strategy=HeatSourceCommandStrategyV3(
                mode="simple",
                enable_permission=ProviderServiceCallV3(
                    domain="switch",
                    service="turn_on",
                    command_target_reference=source,
                ),
                disable_permission=ProviderServiceCallV3(
                    domain="switch",
                    service="turn_off",
                    command_target_reference=source,
                ),
            ),
            observations=HeatSourceObservationBindingsV3(
                reported_actuator_state_reference=source,
            ),
        )
    )

    zone = scopes.heating.zones[0]
    heat_source = scopes.heating.heat_sources[0]
    assert zone.zone_id == GREENFIELD_ZONE_ID_V3
    assert zone.primary_temperature_sensor.sensor_id == GREENFIELD_PRIMARY_SENSOR_ID_V3
    assert heat_source.heat_source_id == GREENFIELD_HEAT_SOURCE_ID_V3
    assert zone.zone_id not in {sensor.native_id, sensor.current_locator}
    assert heat_source.heat_source_id not in {source.native_id, source.current_locator}
    assert zone.demand_policy == ZoneDemandPolicyV3()
    assert scopes.heating.global_configuration == HeatingGlobalConfigurationV3()
    assert heat_source.protection == HeatSourceProtectionPolicyV3()
    assert scopes.heating.heat_delivery == (ZoneHeatDeliveryConfigurationV3(zone_id=zone.zone_id),)
    assert scopes.diagnostics == DiagnosticsConfigurationV3()
    assert scopes.notifications == NotificationsConfigurationV3()


def test_conversion_configuration_identity_is_deterministic_and_operation_scoped() -> None:
    first = conversion_configuration_id_v3("home_assistant:entry-1:conversion-1")

    assert first == conversion_configuration_id_v3("home_assistant:entry-1:conversion-1")
    assert first != conversion_configuration_id_v3("home_assistant:entry-1:conversion-2")
    assert first.startswith("heating_")


def test_stable_logical_identity_is_separate_from_provider_topology_and_locator() -> None:
    migrated = _migrate()
    zone = migrated.heating.zones[0]
    sensor = zone.primary_temperature_sensor
    topology = zone.topology

    assert zone.zone_id == "controlel_living_zone"
    assert zone.display_name == "Living room"
    assert sensor.sensor_id == "controlel_primary_sensor"
    assert sensor.sensor_id != sensor.provider_reference.native_id
    assert sensor.sensor_id != sensor.provider_reference.current_locator
    assert sensor.display_name == "Room thermometer"
    assert topology.area_reference is not None
    assert zone.zone_id != topology.area_reference.native_id
    assert topology.area_reference.native_id == "ha-living-area"
    assert topology.floor_reference is not None
    assert topology.floor_reference.native_id == "ha-ground-floor"


def test_primary_sensor_must_be_resolved_before_v3_migration() -> None:
    ephemeral = _reference(
        "ignored",
        "sensor.legacy_temperature",
        identity_quality=IdentityQuality.EPHEMERAL,
    )
    source = _v2_revision(primary_reference=ephemeral)

    with pytest.raises(CanonicalV2ToV3MigrationError, match="stable provider identity"):
        _migrate(source)


def test_heat_source_command_targets_must_be_resolved_before_v3_migration() -> None:
    ephemeral = _reference(
        "ignored",
        "switch.legacy_boiler",
        identity_quality=IdentityQuality.EPHEMERAL,
    )
    source = _v2_revision(source_reference=ephemeral)

    with pytest.raises(CanonicalV2ToV3MigrationError, match="enable command target"):
        _migrate(source)


def test_migration_projects_overloaded_provider_values_to_separate_logical_ids() -> None:
    migrated = _migrate(
        _v2_revision(
            zone_id="ha-living-area",
            sensor_id="sensor.living_temperature",
        )
    )
    zone = migrated.heating.zones[0]
    provenance = migrated.migration_provenance["v2_to_v3"]

    assert zone.zone_id == "main_zone"
    assert zone.primary_temperature_sensor.sensor_id == "primary_temperature_sensor"
    assert isinstance(provenance, Mapping)
    projection = provenance["logical_identity_projection"]
    assert isinstance(projection, Mapping)
    assert projection["zone_id_remapped"] is True
    assert projection["sensor_id_remapped"] is True


def test_schema_rejects_a_sensor_logical_id_that_is_a_provider_native_id() -> None:
    provider_reference = _reference("primary_sensor", "sensor.living_temperature")

    with pytest.raises(ValidationError, match="Controlel identity"):
        PrimaryTemperatureSensorV3(
            sensor_id="primary_sensor",
            display_name="Living sensor",
            provider_reference=provider_reference,
        )


def test_reported_actuator_state_is_not_physical_heat_source_operation() -> None:
    migrated = _migrate()
    source = migrated.heating.heat_sources[0]
    observations = source.observations

    assert observations.reported_actuator_state_reference is not None
    assert observations.reported_actuator_state_reference.current_locator == "switch.boiler_relay"
    assert observations.physical_operation_reference is None
    dumped = observations.model_dump(mode="json")
    assert set(dumped) == {"reported_actuator_state_reference", "physical_operation_reference"}

    physical = _reference("registry-burner-sensor", "binary_sensor.burner_flame")
    explicit = HeatSourceObservationBindingsV3(
        reported_actuator_state_reference=observations.reported_actuator_state_reference,
        physical_operation_reference=physical,
    )
    assert explicit.reported_actuator_state_reference != explicit.physical_operation_reference

    with pytest.raises(ValidationError, match="distinct evidence"):
        HeatSourceObservationBindingsV3(
            reported_actuator_state_reference=observations.reported_actuator_state_reference,
            physical_operation_reference=observations.reported_actuator_state_reference,
        )


@pytest.mark.parametrize(
    ("scope", "field", "value"),
    [
        ("revision", "measurements", []),
        ("heating", "demand_decisions", []),
        ("source", "command_outcomes", []),
        ("diagnostics", "debug_expiry_deadline", NOW.isoformat()),
        ("diagnostics", "events", []),
        ("diagnostics", "traces", []),
        ("notifications", "delivery_results", []),
        ("notifications", "delivered_count", 1),
    ],
)
def test_operational_data_cannot_be_deserialized_as_configuration(scope: str, field: str, value: object) -> None:
    document = _migrate().model_dump(mode="json", by_alias=True)
    if scope == "revision":
        target = document
    elif scope == "heating":
        target = document["heating"]
    elif scope == "source":
        target = document["heating"]["heat_sources"][0]
    else:
        target = document[scope]
    target[field] = value

    with pytest.raises(ValidationError, match="extra_forbidden"):
        CanonicalConfigurationRevisionV3.model_validate(document)


def test_operational_data_cannot_be_smuggled_through_revision_provenance() -> None:
    document = _migrate().model_dump(mode="json", by_alias=True)
    document["import_provenance"] = {"events": [{"kind": "source_enabled"}]}

    with pytest.raises(ValidationError, match="operational data key"):
        CanonicalConfigurationRevisionV3.model_validate(document)


def test_operational_data_cannot_be_smuggled_through_provider_recovery_evidence() -> None:
    provider_reference = _reference("primary_sensor", "sensor.living_temperature").model_copy(
        update={"recovery_evidence": {"traces": []}}
    )

    with pytest.raises(ValidationError, match="operational data key"):
        PrimaryTemperatureSensorV3(
            sensor_id="logical_primary_sensor",
            display_name="Living sensor",
            provider_reference=provider_reference,
        )


def test_field_registry_is_schema_derived_complete_and_contains_no_default_values() -> None:
    registry = canonical_field_registry_v3()
    paths = tuple(item.canonical_path for item in registry)

    assert len(registry) == 50
    assert len(paths) == len(set(paths))
    assert paths == canonical_field_registry_v3_paths()
    assert {item.owner for item in registry} == set(ConfigurationOwnerV3)
    assert not hasattr(registry[0], "default_value")
    assert "heating.global.maximum_future_skew_seconds" in paths
    assert "heating.zones[].primary_temperature_sensor.provider_reference" in paths
    assert "heating.heat_sources[].observations.reported_actuator_state_reference" in paths
    assert "heating.heat_sources[].observations.physical_operation_reference" in paths
    assert "diagnostics.steady_profile" in paths
    assert "notifications.recipients[].target" in paths

    by_path = {item.canonical_path: item for item in registry}
    deferred = {
        item.canonical_path: item
        for item in registry
        if item.editability is ConfigurationEditabilityV3.DEFERRED_NON_EDITABLE
    }
    assert set(deferred) == {
        "heating.heat_sources[].observations.physical_operation_reference",
        "diagnostics.debug_policy.until_changed",
    }
    assert all(item.deferred_reason for item in deferred.values())
    assert all(
        item.deferred_reason is None
        for item in registry
        if item.editability is not ConfigurationEditabilityV3.DEFERRED_NON_EDITABLE
    )
    assert (
        by_path["heating.zones[].demand_policy.target_temperature_celsius"].default_policy
        is ConfigurationDefaultPolicyV3.RECOMMENDED_NEW_CONFIGURATION
    )
    assert by_path["heating.zones[].zone_id"].default_policy is ConfigurationDefaultPolicyV3.REQUIRED
    forbidden_leaf_names = {
        "current_temperature",
        "demand_decisions",
        "command_outcomes",
        "deadlines",
        "events",
        "traces",
        "counters",
        "delivery_results",
    }
    assert not forbidden_leaf_names & {path.rsplit(".", 1)[-1] for path in paths}


def test_every_v3_field_without_effective_v1_semantics_is_deferred_non_editable() -> None:
    fields = {item.canonical_path: item for item in canonical_field_registry_v3()}
    without_effective_v1_semantics = {
        "heating.heat_sources[].observations.physical_operation_reference",
        "diagnostics.debug_policy.until_changed",
    }

    assert {
        path for path, field in fields.items() if field.editability is ConfigurationEditabilityV3.DEFERRED_NON_EDITABLE
    } == without_effective_v1_semantics
    assert all(
        fields[path].editability is not ConfigurationEditabilityV3.EDITABLE
        and fields[path].editability is not ConfigurationEditabilityV3.EDITABLE_PROVIDER_BINDING
        for path in without_effective_v1_semantics
    )


def canonical_field_registry_v3_paths() -> tuple[str, ...]:
    """Return a second derivation to catch mutable or order-dependent registry behavior."""
    return tuple(item.canonical_path for item in canonical_field_registry_v3())


def test_v3_scope_models_reject_cross_owner_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DiagnosticsConfigurationV3.model_validate(
            {
                "steady_profile": "basic",
                "notification_recipients": [],
            }
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        NotificationsConfigurationV3.model_validate(
            {
                "enabled": False,
                "minimum_heating_on_seconds": 600,
            }
        )
