from copy import deepcopy
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from controlel.application.configuration.heating_setup_adapter import (
    HEAT_DELIVERY_ACTUATOR_ROLE,
    HEATING_SETUP_SCHEMA_VERSION,
    PRIMARY_TEMPERATURE_ROLE,
    REPORTED_SOURCE_STATE_ROLE,
    SOURCE_DISABLE_TARGET_ROLE,
    SOURCE_ENABLE_TARGET_ROLE,
)
from controlel.application.setup import (
    ActiveReference,
    InMemorySetupRepository,
    SelectionOrigin,
    SetupNotFoundError,
)
from controlel.application.setup.json_data import normalize_json
from controlel.domain.commands.heating_action import HeatingAction
from controlel.domain.notifications import NotificationLevel, NotificationPolicy, NotificationRecipient
from controlel.domain.operational_events import OperationalEventCategory
from controlel.domain.value_objects.sensor_id import SensorId
from controlel.domain.value_objects.temperature import Temperature
from controlel.domain.value_objects.zone_id import ZoneId
from custom_components.controlel.config import (
    HomeAssistantHeatSourceBinding,
    HomeAssistantIntegrationConfig,
    HomeAssistantServiceCall,
    integration_config_from_entry_data,
)
from custom_components.controlel.const import CONTROL_MODE_CUSTOM, CONTROL_MODE_SIMPLE
from custom_components.controlel.legacy_config_converter import (
    LEGACY_FIELD_MAPPINGS,
    LegacyHeatingConversionError,
    LegacyHeatingConversionResult,
    convert_legacy_heating_config,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def _custom_legacy_config() -> HomeAssistantIntegrationConfig:
    return HomeAssistantIntegrationConfig(
        sensor_id=SensorId(value="study_temperature"),
        sensor_name="Study temperature",
        temperature_entity_id="sensor.study_temperature",
        zone_id=ZoneId(value="study"),
        zone_name="Study",
        target_temperature=Temperature(value=22.25),
        heating_turn_on_differential=0.45,
        heating_turn_off_differential=0.15,
        minimum_heating_on_time=timedelta(minutes=11, microseconds=2),
        minimum_heating_off_time=timedelta(minutes=7, microseconds=3),
        primary_measurement_max_age=timedelta(minutes=8, microseconds=4),
        max_future_skew=timedelta(seconds=17, microseconds=5),
        indeterminate_grace_period=timedelta(minutes=3, microseconds=6),
        indeterminate_timeout_action=HeatingAction.ENABLE_HEATING,
        heat_source=HomeAssistantHeatSourceBinding(
            enable_heating=HomeAssistantServiceCall(
                domain="vendor_boiler",
                service="grant_heat_permission",
                target_entity_id="climate.plant_room",
            ),
            disable_heating=HomeAssistantServiceCall(
                domain="script",
                service="revoke_heat_permission",
                target_entity_id="script.stop_boiler",
            ),
        ),
        heat_source_control_mode=CONTROL_MODE_CUSTOM,
        controlled_entity_id=None,
        diagnostic_profile="debug",
        debug_duration=None,
        configured_debug_duration=timedelta(minutes=37, microseconds=7),
        diagnostic_profile_before_debug="basic",
        heat_demand_confirmation_duration=timedelta(seconds=83, microseconds=8),
        heat_delivery_mode="setpoint_assist",
        heat_delivery_actuator_entity_id="climate.study_radiator",
        heat_delivery_ownership="controlel_owned",
        heat_delivery_assist_policy="always_assist_while_heating",
        heat_delivery_assist_target=31.75,
        notification_policy=NotificationPolicy(
            enabled=True,
            recipients=(
                NotificationRecipient(
                    "wall_panel",
                    "home_assistant_notify",
                    "notify.wall_panel",
                    enabled=False,
                    minimum_level=NotificationLevel.CRITICAL,
                    categories=(OperationalEventCategory.RUNTIME, OperationalEventCategory.SAFETY),
                ),
                NotificationRecipient(
                    "family_phone",
                    "home_assistant_notify",
                    "notify.family_phone",
                    minimum_level=NotificationLevel.DETAILED,
                    categories=(
                        OperationalEventCategory.RUNTIME,
                        OperationalEventCategory.SUPERVISION,
                    ),
                ),
            ),
            maximum_per_window=4,
            rate_window=timedelta(seconds=121, microseconds=9),
            critical_maximum_per_window=31,
            critical_rate_window=timedelta(seconds=181, microseconds=10),
            history_capacity=251,
        ),
    )


def _simple_legacy_config() -> HomeAssistantIntegrationConfig:
    controlled = "switch.boiler"
    return replace(
        _custom_legacy_config(),
        heat_source=HomeAssistantHeatSourceBinding(
            enable_heating=HomeAssistantServiceCall("switch", "turn_on", controlled),
            disable_heating=HomeAssistantServiceCall("switch", "turn_off", controlled),
        ),
        heat_source_control_mode=CONTROL_MODE_SIMPLE,
        controlled_entity_id=controlled,
        heat_delivery_mode="unmanaged",
        heat_delivery_actuator_entity_id=None,
        heat_delivery_ownership="device_owned",
        heat_delivery_assist_policy="no_assist",
    )


def _convert(
    legacy: HomeAssistantIntegrationConfig,
    *,
    revision_id: str = "legacy-revision-1",
    created_at: datetime = NOW,
) -> LegacyHeatingConversionResult:
    return convert_legacy_heating_config(
        legacy,
        environment_id="home",
        provider_instance_id="ha-instance",
        module_instance_id="main-heating",
        configuration_id="heating-configuration",
        revision_id=revision_id,
        created_at=created_at,
        core_version="0.14.0",
        integration_version="0.12.0",
    )


def _binding_locators(result: LegacyHeatingConversionResult) -> dict[str, str | None]:
    return {binding.role: binding.reference.current_locator for binding in result.canonical_revision.bindings}


def test_representative_full_conversion_is_schema_v2_validator_v3_compatible() -> None:
    legacy = _custom_legacy_config()

    result = _convert(legacy)
    canonical = result.canonical_revision
    payload = normalize_json(canonical.module_payload)
    assert isinstance(payload, dict)

    assert canonical.module_schema_version == HEATING_SETUP_SCHEMA_VERSION == 2
    assert result.validation_report.validator_policy_version == 3
    assert result.validation_report.activation_ready is True
    assert canonical.logical_identities == {"sensor_id": "study_temperature", "zone_id": "study"}
    assert payload == {
        "zone_id": "study",
        "zone_name": "Study",
        "sensor_id": "study_temperature",
        "sensor_name": "Study temperature",
        "target_temperature_celsius": 22.25,
        "primary_measurement_max_age_seconds": 480.000004,
        "maximum_future_skew_seconds": 17.000005,
        "indeterminate_grace_period_seconds": 180.000006,
        "indeterminate_timeout_action": "enable_heating",
        "heating_turn_on_differential_celsius": 0.45,
        "heating_turn_off_differential_celsius": 0.15,
        "heat_demand_confirmation_seconds": 83.000008,
        "minimum_heating_on_seconds": 660.000002,
        "minimum_heating_off_seconds": 420.000003,
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
        "reported_source_state_binding_role": None,
        "heat_delivery_mode": "setpoint_assist",
        "heat_delivery_actuator_binding_role": HEAT_DELIVERY_ACTUATOR_ROLE,
        "heat_delivery_ownership": "controlel_owned",
        "heat_delivery_assist_policy": "always_assist_while_heating",
        "heat_delivery_assist_target_celsius": 31.75,
        "diagnostic_policy": {
            "diagnostic_profile": "debug",
            "configured_debug_duration_seconds": 2220.000007,
            "debug_until_changed": True,
            "diagnostic_profile_before_debug": "basic",
        },
        "notification_policy": {
            "enabled": True,
            "recipients": [
                {
                    "recipient_id": "wall_panel",
                    "transport": "home_assistant_notify",
                    "target": "notify.wall_panel",
                    "enabled": False,
                    "minimum_level": "critical",
                    "categories": ["runtime", "safety"],
                },
                {
                    "recipient_id": "family_phone",
                    "transport": "home_assistant_notify",
                    "target": "notify.family_phone",
                    "enabled": True,
                    "minimum_level": "detailed",
                    "categories": ["runtime", "supervision"],
                },
            ],
            "maximum_per_window": 4,
            "rate_window_seconds": 121.000009,
            "critical_maximum_per_window": 31,
            "critical_rate_window_seconds": 181.00001,
            "history_capacity": 251,
        },
    }
    assert _binding_locators(result) == {
        PRIMARY_TEMPERATURE_ROLE: "sensor.study_temperature",
        SOURCE_ENABLE_TARGET_ROLE: "climate.plant_room",
        SOURCE_DISABLE_TARGET_ROLE: "script.stop_boiler",
        HEAT_DELIVERY_ACTUATOR_ROLE: "climate.study_radiator",
    }
    assert all(binding.selection_origin is SelectionOrigin.MIGRATED for binding in canonical.bindings)


def test_mapping_table_covers_exactly_all_28_legacy_fields() -> None:
    legacy_fields = {field.name for field in fields(HomeAssistantIntegrationConfig)}

    assert len(legacy_fields) == 28
    assert set(LEGACY_FIELD_MAPPINGS) == legacy_fields
    assert all(paths for paths in LEGACY_FIELD_MAPPINGS.values())


def test_missing_legacy_diagnostic_profile_materializes_explicit_detailed_policy() -> None:
    data = {
        "sensor_id": "living_room_temperature",
        "sensor_name": "Living room temperature",
        "temperature_entity_id": "sensor.living_room_temperature",
        "zone_id": "living_room",
        "zone_name": "Living room",
        "target_temperature": 21.0,
        "primary_measurement_max_age": 300.0,
        "max_future_skew": 5.0,
        "indeterminate_grace_period": 60.0,
        "indeterminate_timeout_action": "disable_heating",
        "enable_service_domain": "switch",
        "enable_service_name": "turn_on",
        "enable_target_entity_id": "switch.boiler",
        "disable_service_domain": "switch",
        "disable_service_name": "turn_off",
        "disable_target_entity_id": "switch.boiler",
    }
    original = deepcopy(data)

    result = _convert(integration_config_from_entry_data(data))

    assert result.canonical_revision.module_payload["diagnostic_policy"] == {
        "diagnostic_profile": "detailed",
        "configured_debug_duration_seconds": 3600.0,
        "debug_until_changed": False,
        "diagnostic_profile_before_debug": "detailed",
    }
    assert data == original
    assert "diagnostic_profile" not in data


@pytest.mark.parametrize("until_changed", [False, True])
def test_debug_until_changed_and_configured_duration_are_both_preserved(until_changed: bool) -> None:
    configured = timedelta(minutes=29)
    legacy = replace(
        _custom_legacy_config(),
        debug_duration=None if until_changed else configured,
        configured_debug_duration=configured,
    )

    policy = _convert(legacy).canonical_revision.module_payload["diagnostic_policy"]

    assert policy["debug_until_changed"] is until_changed
    assert policy["configured_debug_duration_seconds"] == 1740.0


def test_notification_recipient_order_is_preserved() -> None:
    legacy = _custom_legacy_config()
    reversed_policy = replace(
        legacy.notification_policy,
        recipients=tuple(reversed(legacy.notification_policy.recipients)),
    )

    forward = _convert(legacy).canonical_revision
    reverse = _convert(replace(legacy, notification_policy=reversed_policy)).canonical_revision

    assert [recipient["recipient_id"] for recipient in forward.module_payload["notification_policy"]["recipients"]] == [
        "wall_panel",
        "family_phone",
    ]
    assert [recipient["recipient_id"] for recipient in reverse.module_payload["notification_policy"]["recipients"]] == [
        "family_phone",
        "wall_panel",
    ]
    assert forward.semantic_configuration_fingerprint != reverse.semantic_configuration_fingerprint


@pytest.mark.parametrize("action", [HeatingAction.ENABLE_HEATING, HeatingAction.DISABLE_HEATING])
def test_timeout_enable_and_disable_actions_are_preserved(action: HeatingAction) -> None:
    canonical = _convert(replace(_custom_legacy_config(), indeterminate_timeout_action=action)).canonical_revision

    assert canonical.module_payload["indeterminate_timeout_action"] == action.value


def test_simple_source_control_preserves_command_and_reported_state_bindings() -> None:
    result = _convert(_simple_legacy_config())
    payload = result.canonical_revision.module_payload

    assert payload["source_control_mode"] == "simple"
    assert payload["source_enable"] == {
        "domain": "switch",
        "service": "turn_on",
        "target_binding_role": SOURCE_ENABLE_TARGET_ROLE,
    }
    assert payload["source_disable"] == {
        "domain": "switch",
        "service": "turn_off",
        "target_binding_role": SOURCE_DISABLE_TARGET_ROLE,
    }
    assert payload["reported_source_state_binding_role"] == REPORTED_SOURCE_STATE_ROLE
    assert _binding_locators(result) == {
        PRIMARY_TEMPERATURE_ROLE: "sensor.study_temperature",
        SOURCE_ENABLE_TARGET_ROLE: "switch.boiler",
        SOURCE_DISABLE_TARGET_ROLE: "switch.boiler",
        REPORTED_SOURCE_STATE_ROLE: "switch.boiler",
    }


def test_repeated_conversion_has_the_same_semantic_fingerprint() -> None:
    legacy = _custom_legacy_config()

    first = _convert(legacy, revision_id="artifact-a", created_at=NOW).canonical_revision
    second = _convert(
        legacy,
        revision_id="artifact-b",
        created_at=NOW + timedelta(days=1),
    ).canonical_revision

    assert first.revision_id != second.revision_id
    assert first.document_hash != second.document_hash
    assert first.semantic_configuration_fingerprint == second.semantic_configuration_fingerprint


def test_converted_result_is_inactive_and_existing_active_reference_is_unchanged() -> None:
    repository = InMemorySetupRepository()
    existing = _convert(_simple_legacy_config(), revision_id="active-revision")
    repository.add_canonical_revision(existing.canonical_revision)
    reference = ActiveReference(
        environment_id="home",
        module_key="heating",
        module_instance_id="main-heating",
        canonical_revision_id=existing.canonical_revision.revision_id,
        semantic_configuration_fingerprint=(existing.canonical_revision.semantic_configuration_fingerprint),
        generation=1,
        committing_operation_id="existing-activation",
    )
    repository.compare_and_swap_active_reference(
        scope=reference.scope_key,
        expected_revision_id=None,
        expected_generation=0,
        replacement=reference,
    )

    converted = _convert(_custom_legacy_config(), revision_id="inactive-migration")

    assert converted.activated is False
    assert repository.get_active_reference(reference.scope_key) == reference
    with pytest.raises(SetupNotFoundError, match="canonical revision not found"):
        repository.get_canonical_revision(converted.canonical_revision.revision_id)


def test_conversion_does_not_modify_legacy_input() -> None:
    legacy = _custom_legacy_config()
    original = deepcopy(legacy)

    _convert(legacy)

    assert legacy == original


def test_unrepresentable_legacy_input_fails_explicitly() -> None:
    legacy = replace(
        _custom_legacy_config(),
        debug_duration=timedelta(minutes=10),
        configured_debug_duration=timedelta(minutes=20),
    )

    with pytest.raises(
        LegacyHeatingConversionError,
        match="debug_duration differs from configured_debug_duration",
    ):
        _convert(legacy)
