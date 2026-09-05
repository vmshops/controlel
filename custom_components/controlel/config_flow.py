"""Native Home Assistant projection of canonical configuration v3."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib import metadata
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, FlowType, OptionsFlow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from pydantic import ValidationError

from controlel.application.configuration import (
    CanonicalConfigurationDraftV3,
    CanonicalConfigurationRevisionV3,
    CanonicalConfigurationValidationV3,
    ConfigurationEditabilityV3,
    ConfigurationScopesV3,
    canonical_field_registry_v3,
)
from controlel.application.configuration.heating_setup_adapter import HeatingSetupAdapter
from controlel.application.configuration.water_safety_setup_adapter import (
    WATER_SAFETY_MODULE_KEY,
    WATER_SAFETY_SENSOR_ROLE,
)
from controlel.application.setup import SetupConflictError, SetupNotFoundError
from controlel.application.setup.json_data import canonical_json
from controlel.infrastructure.home_assistant import (
    ACTIVE_REFERENCE_KEY,
    ACTIVE_REFERENCES_KEY,
    HomeAssistantDiscoveryAdapter,
    active_reference_for_module,
)
from controlel.infrastructure.home_assistant.setup_discovery import HA_AREA_KIND, HA_FLOOR_KIND

from .activation_backend import async_activate_canonical_revision
from .const import CONFIG_ENTRY_VERSION, DOMAIN, INTEGRATION_VERSION
from .lifecycle_diagnostics import lifecycle_failures_for_entry, record_lifecycle_failure
from .setup_backend import async_get_setup_backend, async_get_setup_service
from .water_safety_activation import WaterSafetyActivationService
from .water_safety_area_sensor import (
    WaterSafetyAreaSensorEditor,
    async_load_water_safety_area_sensor_editor,
    async_save_water_safety_area_sensor_draft,
)
from .water_safety_configure_view import (
    WaterSafetySection,
    async_build_water_safety_configure_view,
    water_safety_menu_summary,
    water_safety_section_detail,
)
from .water_safety_notifications import (
    WaterSafetyNotificationsEditor,
    async_load_water_safety_notifications_editor,
    async_save_water_safety_notifications_draft,
    async_test_water_safety_notification,
)
from .water_safety_shutoff_valves import (
    WaterSafetyShutoffValvesEditor,
    async_load_water_safety_shutoff_valves_editor,
    async_save_water_safety_shutoff_valves_draft,
)
from .water_safety_sirens import (
    WaterSafetySirensEditor,
    async_load_water_safety_sirens_editor,
    async_save_water_safety_sirens_draft,
)

LOGGER = logging.getLogger(__name__)

HUB_MENU_OPTIONS = ("general_hub", "heating", "water_safety")
GENERAL_MENU_OPTIONS = ("back_to_hub",)
HEATING_BASIC_SECTIONS = ("zone",)
HEATING_REQUIRED_SECTIONS = ("sensor", "heat_source")
HEATING_OPTIONAL_SECTIONS = ("heat_delivery", "notifications")
HEATING_ADVANCED_SECTIONS = ("safety_timing", "diagnostics")
HEATING_SECTION_MENU_OPTIONS = (
    "heating_review",
    "abandon_current",
    "zone",
    "sensor",
    "heat_source",
    "heat_delivery",
    "safety_timing",
    "notifications",
    "diagnostics",
    "back_to_hub",
)
WATER_SAFETY_MENU_OPTIONS = (
    "water_safety_validation",
    "water_safety_area_sensor",
    "water_safety_notifications",
    "water_safety_sirens",
    "water_safety_shutoff_valves",
    "back_to_hub",
)
HUB_EXPLANATION = (
    "Controlel is a multi-module platform. Choose a module below. "
    "You can leave any module without completing its configuration."
)
CREATE_EXPLANATION = "Create the Controlel integration, then configure modules through native Home Assistant Configure."
GENERAL_EXPLANATION = (
    "No shared General settings are currently required. Heating and Water Safety remain independently configurable. "
    "Opening General never changes module configuration or active authority."
)

ZONE_NAME = "zone_display_name"
ZONE_AREA = "zone_area"
ZONE_FLOOR = "zone_floor"
TARGET_TEMPERATURE = "target_temperature_celsius"
TURN_ON_DIFFERENTIAL = "heating_turn_on_differential_celsius"
TURN_OFF_DIFFERENTIAL = "heating_turn_off_differential_celsius"
DEMAND_CONFIRMATION = "heat_demand_confirmation_seconds"
SENSOR_NAME = "primary_sensor_display_name"
TEMPERATURE_ENTITY = "primary_temperature_entity_id"
MEASUREMENT_MAX_AGE = "primary_measurement_max_age_seconds"
SOURCE_NAME = "heat_source_display_name"
SOURCE_ENTITY = "heat_source_entity_id"
SOURCE_MODE = "heat_source_command_mode"
ENABLE_DOMAIN = "enable_service_domain"
ENABLE_SERVICE = "enable_service_name"
ENABLE_TARGET = "enable_target_entity_id"
DISABLE_DOMAIN = "disable_service_domain"
DISABLE_SERVICE = "disable_service_name"
DISABLE_TARGET = "disable_target_entity_id"
REPORTED_SOURCE_STATE = "reported_source_state_entity_id"
DELIVERY_MODE = "heat_delivery_mode"
DELIVERY_ACTUATOR = "heat_delivery_actuator_entity_id"
DELIVERY_OWNERSHIP = "heat_delivery_ownership"
DELIVERY_ASSIST_POLICY = "heat_delivery_assist_policy"
DELIVERY_ASSIST_TARGET = "heat_delivery_assist_target_celsius"
MAXIMUM_FUTURE_SKEW = "maximum_future_skew_seconds"
INDETERMINATE_GRACE = "indeterminate_grace_period_seconds"
INDETERMINATE_ACTION = "indeterminate_timeout_action"
MINIMUM_ON = "minimum_heating_on_seconds"
MINIMUM_OFF = "minimum_heating_off_seconds"
DIAGNOSTIC_PROFILE = "diagnostic_steady_profile"
DEBUG_DURATION = "debug_configured_duration_seconds"
NOTIFICATIONS_ENABLED = "notifications_enabled"
NOTIFICATION_RECIPIENTS = "notification_recipients"
NOTIFICATION_MAXIMUM = "notification_maximum_per_window"
NOTIFICATION_WINDOW = "notification_rate_window_seconds"
CRITICAL_NOTIFICATION_MAXIMUM = "critical_notification_maximum_per_window"
CRITICAL_NOTIFICATION_WINDOW = "critical_notification_rate_window_seconds"
NOTIFICATION_HISTORY = "notification_history_capacity"
WATER_AREA = "water_safety_area_id"
WATER_MOISTURE_SENSOR = "water_safety_moisture_entity_id"
WATER_SHOW_ALL_COMPATIBLE = "show_all_compatible_entities"
WATER_NOTIFICATION_TARGETS = "water_safety_notification_targets"
WATER_TEST_NOTIFICATION = "water_safety_test_notification"
WATER_SIREN_TARGETS = "water_safety_siren_targets"
WATER_SHUTOFF_VALVE_TARGETS = "water_safety_shutoff_valve_targets"

_FORM_PATHS = {
    "heating.zones[].display_name": ZONE_NAME,
    "heating.zones[].topology.area_reference": ZONE_AREA,
    "heating.zones[].topology.floor_reference": ZONE_FLOOR,
    "heating.zones[].primary_temperature_sensor.display_name": SENSOR_NAME,
    "heating.zones[].primary_temperature_sensor.provider_reference": TEMPERATURE_ENTITY,
    "heating.zones[].demand_policy.target_temperature_celsius": TARGET_TEMPERATURE,
    "heating.zones[].demand_policy.heating_turn_on_differential_celsius": TURN_ON_DIFFERENTIAL,
    "heating.zones[].demand_policy.heating_turn_off_differential_celsius": TURN_OFF_DIFFERENTIAL,
    "heating.zones[].demand_policy.heat_demand_confirmation_seconds": DEMAND_CONFIRMATION,
    "heating.zones[].demand_policy.primary_measurement_max_age_seconds": MEASUREMENT_MAX_AGE,
    "heating.global.maximum_future_skew_seconds": MAXIMUM_FUTURE_SKEW,
    "heating.heat_sources[].display_name": SOURCE_NAME,
    "heating.heat_sources[].provider_reference": SOURCE_ENTITY,
    "heating.heat_sources[].command_strategy.mode": SOURCE_MODE,
    "heating.heat_sources[].command_strategy.enable_permission.domain": ENABLE_DOMAIN,
    "heating.heat_sources[].command_strategy.enable_permission.service": ENABLE_SERVICE,
    "heating.heat_sources[].command_strategy.enable_permission.command_target_reference": ENABLE_TARGET,
    "heating.heat_sources[].command_strategy.disable_permission.domain": DISABLE_DOMAIN,
    "heating.heat_sources[].command_strategy.disable_permission.service": DISABLE_SERVICE,
    "heating.heat_sources[].command_strategy.disable_permission.command_target_reference": DISABLE_TARGET,
    "heating.heat_sources[].observations.reported_actuator_state_reference": REPORTED_SOURCE_STATE,
    "heating.heat_sources[].protection.indeterminate_grace_period_seconds": INDETERMINATE_GRACE,
    "heating.heat_sources[].protection.indeterminate_timeout_action": INDETERMINATE_ACTION,
    "heating.heat_sources[].protection.minimum_heating_on_seconds": MINIMUM_ON,
    "heating.heat_sources[].protection.minimum_heating_off_seconds": MINIMUM_OFF,
    "heating.heat_delivery[].mode": DELIVERY_MODE,
    "heating.heat_delivery[].actuator_reference": DELIVERY_ACTUATOR,
    "heating.heat_delivery[].ownership": DELIVERY_OWNERSHIP,
    "heating.heat_delivery[].assist_policy": DELIVERY_ASSIST_POLICY,
    "heating.heat_delivery[].assist_target_celsius": DELIVERY_ASSIST_TARGET,
    "diagnostics.steady_profile": DIAGNOSTIC_PROFILE,
    "diagnostics.debug_policy.configured_duration_seconds": DEBUG_DURATION,
    "notifications.enabled": NOTIFICATIONS_ENABLED,
    "notifications.recipients[].transport": NOTIFICATION_RECIPIENTS,
    "notifications.recipients[].target": NOTIFICATION_RECIPIENTS,
    "notifications.recipients[].enabled": NOTIFICATION_RECIPIENTS,
    "notifications.recipients[].minimum_level": NOTIFICATION_RECIPIENTS,
    "notifications.recipients[].categories": NOTIFICATION_RECIPIENTS,
    "notifications.maximum_per_window": NOTIFICATION_MAXIMUM,
    "notifications.rate_window_seconds": NOTIFICATION_WINDOW,
    "notifications.critical_maximum_per_window": CRITICAL_NOTIFICATION_MAXIMUM,
    "notifications.critical_rate_window_seconds": CRITICAL_NOTIFICATION_WINDOW,
    "notifications.history_capacity": NOTIFICATION_HISTORY,
}


def canonical_v3_ha_editable_field_paths() -> tuple[str, ...]:
    """Return the registry-derived field surface projected by native HA Configure."""
    editable = {
        item.canonical_path
        for item in canonical_field_registry_v3()
        if item.editability
        in {ConfigurationEditabilityV3.EDITABLE, ConfigurationEditabilityV3.EDITABLE_PROVIDER_BINDING}
    }
    if editable != set(_FORM_PATHS):
        missing = sorted(editable - set(_FORM_PATHS))
        extra = sorted(set(_FORM_PATHS) - editable)
        raise RuntimeError(f"canonical v3 HA field projection drifted (missing={missing}, extra={extra})")
    return tuple(item.canonical_path for item in canonical_field_registry_v3() if item.canonical_path in editable)


CANONICAL_V3_HA_EDITABLE_FIELD_PATHS = canonical_v3_ha_editable_field_paths()


class ControlelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create an empty shell entry; all new authoring is canonical v3."""

    VERSION = CONFIG_ENTRY_VERSION

    @staticmethod
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        return ControlelOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(
                title="Controlel",
                data={},
                options={},
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={"configure_explanation": CREATE_EXPLANATION},
        )

    async def async_on_create_entry(self, result: ConfigFlowResult) -> ConfigFlowResult:
        """Open native Configure after the empty shell entry exists."""
        options_result = await self.hass.config_entries.options.async_init(result["result"].entry_id)
        result["next_flow"] = (FlowType.OPTIONS_FLOW, options_result["flow_id"])
        return result


class ControlelOptionsFlow(OptionsFlow):
    """Project canonical v3 lifecycle operations into native HA forms."""

    def __init__(self) -> None:
        self._draft: CanonicalConfigurationDraftV3 | None = None
        self._document: dict[str, Any] | None = None
        self._validation: CanonicalConfigurationValidationV3 | None = None
        self._candidate: CanonicalConfigurationRevisionV3 | None = None
        self._heating_activation_failure_reason: str | None = None
        self._water_area_sensor_show_all = False
        self._water_area_sensor_pending: dict[str, Any] | None = None
        self._water_notification_test_result = "No test request has been sent."
        self._water_activation_candidate_id: str | None = None
        self._water_activation_draft: tuple[str, int] | None = None

    async def _service(self) -> Any:
        return (await async_get_setup_backend(self.hass, self.config_entry)).configuration_v3

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        del user_input
        authority = await self._authority_kind()
        if authority == "mixed":
            return self.async_abort(reason="canonical_legacy_mixed")
        return self.async_show_menu(
            step_id="init",
            menu_options=list(HUB_MENU_OPTIONS),
            description_placeholders={"hub_explanation": HUB_EXPLANATION},
        )

    async def async_step_back_to_hub(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_init(user_input)

    async def async_step_heating(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        del user_input
        service = await self._service()
        drafts = await service.list_drafts()
        authority = await self._authority_kind()
        overview_draft = self._draft or (max(drafts, key=lambda item: item.updated_at) if drafts else None)
        validation = await self._async_heating_overview_validation(service, overview_draft)
        if self._draft is not None:
            menu = list(HEATING_SECTION_MENU_OPTIONS)
        else:
            menu = []
            menu.append(
                {"v3": "edit_active", "v2": "convert_v2", "legacy": "convert_legacy"}.get(authority, "start_greenfield")
            )
            if drafts:
                menu.extend(("resume_draft", "abandon_draft"))
            menu.append("back_to_hub")
        return self.async_show_menu(
            step_id="heating",
            menu_options=menu,
            description_placeholders={
                "heating_summary": _heating_menu_summary(
                    active=active_reference_for_module(self.config_entry.data, HeatingSetupAdapter.module_key),
                    drafts=drafts,
                    current=self._draft,
                    overview_draft=overview_draft,
                    validation=validation,
                )
            },
        )

    async def async_step_back_to_heating(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_heating(user_input)

    async def async_step_heating_status(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        del user_input
        service = await self._service()
        drafts = await service.list_drafts()
        overview_draft = self._draft or (max(drafts, key=lambda item: item.updated_at) if drafts else None)
        validation = await self._async_heating_overview_validation(service, overview_draft)
        return self.async_show_menu(
            step_id="heating_status",
            menu_options=["back_to_heating"],
            description_placeholders={
                "heating_status_summary": _heating_menu_summary(
                    active=active_reference_for_module(self.config_entry.data, HeatingSetupAdapter.module_key),
                    drafts=drafts,
                    current=self._draft,
                    overview_draft=overview_draft,
                    validation=validation,
                )
            },
        )

    async def _async_heating_overview_validation(
        self,
        service: Any,
        draft: CanonicalConfigurationDraftV3 | None,
    ) -> CanonicalConfigurationValidationV3 | None:
        if draft is None:
            return None
        try:
            return await service.validate_draft(
                draft.draft_id,
                report_id=_id("ha-heating-overview-validation"),
                snapshot_id=_id("ha-heating-overview-snapshot"),
                evaluated_at=_now(),
            )
        except (SetupConflictError, SetupNotFoundError):
            LOGGER.warning("Heating draft readiness could not be evaluated", exc_info=True)
            return None

    async def async_step_water_safety(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        del user_input
        view = await async_build_water_safety_configure_view(
            (await async_get_setup_backend(self.hass, self.config_entry)).repository,
            self.config_entry.data,
        )
        menu = ["water_safety_validation"]
        if view.draft is not None:
            menu.append("water_safety_abandon")
        menu.extend(
            (
                "water_safety_area_sensor",
                "water_safety_notifications",
                "water_safety_sirens",
                "water_safety_shutoff_valves",
                "back_to_hub",
            )
        )
        return self.async_show_menu(
            step_id="water_safety",
            menu_options=menu,
            description_placeholders={"water_safety_summary": water_safety_menu_summary(view)},
        )

    async def async_step_back_to_water_safety(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_water_safety(user_input)

    async def async_step_water_safety_status(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_water_safety_section("water_safety_status", "status", user_input)

    async def async_step_water_safety_area_sensor(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            self._water_area_sensor_show_all = False
            self._water_area_sensor_pending = None

        errors: dict[str, str] = {}
        values = dict(user_input or self._water_area_sensor_pending or {})
        preferred_area_id = _optional_input(values.get(WATER_AREA))
        backend = await async_get_setup_backend(self.hass, self.config_entry)
        editor = await async_load_water_safety_area_sensor_editor(
            self.hass,
            backend.repository,
            self.config_entry.data,
            snapshot_id=_id("ha-water-area-sensor-snapshot"),
            captured_at=_now(),
            preferred_area_id=preferred_area_id,
        )

        if user_input is not None:
            requested_show_all = bool(user_input.get(WATER_SHOW_ALL_COMPATIBLE, False))
            if requested_show_all and not self._water_area_sensor_show_all:
                self._water_area_sensor_show_all = True
                self._water_area_sensor_pending = dict(user_input)
                return self._show_water_safety_area_sensor_form(editor, values, errors, use_values=True)
            try:
                saved_at = _now()
                await async_save_water_safety_area_sensor_draft(
                    self.hass,
                    backend.repository,
                    editor,
                    area_id=preferred_area_id,
                    moisture_entity_id=_optional_input(user_input.get(WATER_MOISTURE_SENSOR)),
                    saved_at=saved_at,
                    report_id=_id("ha-water-area-sensor-report"),
                )
            except (KeyError, SetupConflictError, SetupNotFoundError, TypeError, ValueError, ValidationError):
                errors["base"] = "invalid_water_area_sensor"
            else:
                self._water_area_sensor_show_all = False
                self._water_area_sensor_pending = None
                return await self.async_step_water_safety()

        return self._show_water_safety_area_sensor_form(
            editor,
            values,
            errors,
            use_values=user_input is not None or self._water_area_sensor_pending is not None,
        )

    def _show_water_safety_area_sensor_form(
        self,
        editor: WaterSafetyAreaSensorEditor,
        values: Mapping[str, Any],
        errors: Mapping[str, str],
        *,
        use_values: bool,
    ) -> ConfigFlowResult:
        area_id = _optional_input(values.get(WATER_AREA)) if use_values else editor.area_id
        sensor_id = _optional_input(values.get(WATER_MOISTURE_SENSOR)) if use_values else editor.moisture_entity_id
        candidates = list(editor.visible_entity_ids(show_all=self._water_area_sensor_show_all))
        if sensor_id is not None and sensor_id not in candidates:
            candidates.append(sensor_id)
        scope = (
            "all compatible entities" if self._water_area_sensor_show_all or area_id is None else "the selected area"
        )
        return self.async_show_form(
            step_id="water_safety_area_sensor",
            data_schema=_water_safety_area_sensor_schema(
                area_id=area_id,
                sensor_id=sensor_id,
                candidate_entity_ids=tuple(candidates),
                show_all=self._water_area_sensor_show_all,
            ),
            errors=dict(errors),
            description_placeholders={
                "candidate_scope": scope,
                "candidate_count": str(len(candidates)),
                "unavailable_area_sensor": (", ".join(editor.unavailable_selection_labels) or "None"),
            },
        )

    async def async_step_water_safety_notifications(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            self._water_notification_test_result = "No test request has been sent."
        backend = await async_get_setup_backend(self.hass, self.config_entry)
        editor = await async_load_water_safety_notifications_editor(
            self.hass,
            backend.repository,
            self.config_entry.data,
            snapshot_id=_id("ha-water-notifications-snapshot"),
            captured_at=_now(),
        )
        errors: dict[str, str] = {}
        target_ids = (
            _notification_targets_input(user_input.get(WATER_NOTIFICATION_TARGETS))
            if user_input is not None
            else editor.selected_target_ids
        )
        if user_input is not None:
            try:
                if bool(user_input.get(WATER_TEST_NOTIFICATION, False)):
                    accepted = await async_test_water_safety_notification(
                        self.hass,
                        editor,
                        target_ids=target_ids,
                    )
                    self._water_notification_test_result = (
                        f"Home Assistant accepted {len(accepted)} notification service request(s). "
                        "Controlel did not verify delivery. No configuration was saved."
                    )
                    user_input = {**user_input, WATER_TEST_NOTIFICATION: False}
                else:
                    saved_at = _now()
                    await async_save_water_safety_notifications_draft(
                        backend.repository,
                        editor,
                        target_ids=target_ids,
                        saved_at=saved_at,
                        report_id=_id("ha-water-notifications-report"),
                    )
                    return await self.async_step_water_safety()
            except (
                HomeAssistantError,
                KeyError,
                SetupConflictError,
                SetupNotFoundError,
                TypeError,
                ValueError,
                ValidationError,
            ):
                errors[WATER_NOTIFICATION_TARGETS] = "invalid_water_notification_targets"

        return self._show_water_safety_notifications_form(
            editor,
            target_ids=target_ids,
            test_requested=bool(user_input and user_input.get(WATER_TEST_NOTIFICATION, False)),
            errors=errors,
        )

    def _show_water_safety_notifications_form(
        self,
        editor: WaterSafetyNotificationsEditor,
        *,
        target_ids: tuple[str, ...],
        test_requested: bool,
        errors: Mapping[str, str],
    ) -> ConfigFlowResult:
        return self.async_show_form(
            step_id="water_safety_notifications",
            data_schema=_water_safety_notifications_schema(
                target_ids=target_ids,
                available_target_ids=editor.available_target_ids,
                unavailable_target_ids=editor.unavailable_target_ids,
                test_requested=test_requested,
            ),
            errors=dict(errors),
            description_placeholders={
                "notification_behavior": (
                    "Optional. Wet and cleared notifications go to the same selected targets for this one "
                    "monitored area. Clearing all targets is valid and leaves notifications unconfigured."
                ),
                "notification_test_result": self._water_notification_test_result,
                "unavailable_notification_targets": (", ".join(editor.unavailable_target_ids) or "None"),
            },
        )

    async def async_step_water_safety_sirens(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        backend = await async_get_setup_backend(self.hass, self.config_entry)
        editor = await async_load_water_safety_sirens_editor(
            self.hass,
            backend.repository,
            self.config_entry.data,
            snapshot_id=_id("ha-water-sirens-snapshot"),
            captured_at=_now(),
        )
        errors: dict[str, str] = {}
        target_ids = (
            _water_entity_targets_input(user_input.get(WATER_SIREN_TARGETS))
            if user_input is not None
            else editor.selected_target_ids
        )
        if user_input is not None:
            try:
                await async_save_water_safety_sirens_draft(
                    backend.repository,
                    editor,
                    target_ids=target_ids,
                    saved_at=_now(),
                    report_id=_id("ha-water-sirens-report"),
                )
            except (KeyError, SetupConflictError, SetupNotFoundError, TypeError, ValueError, ValidationError):
                errors[WATER_SIREN_TARGETS] = "invalid_water_siren_targets"
            else:
                return await self.async_step_water_safety()

        return self._show_water_safety_sirens_form(editor, target_ids=target_ids, errors=errors)

    def _show_water_safety_sirens_form(
        self,
        editor: WaterSafetySirensEditor,
        *,
        target_ids: tuple[str, ...],
        errors: Mapping[str, str],
    ) -> ConfigFlowResult:
        candidates = list(editor.compatible_target_ids)
        candidates.extend(target for target in target_ids if target not in candidates)
        unavailable = ", ".join(editor.unavailable_target_ids) or "None"
        return self.async_show_form(
            step_id="water_safety_sirens",
            data_schema=_water_safety_sirens_schema(
                target_ids=target_ids,
                candidate_entity_ids=tuple(candidates),
            ),
            errors=dict(errors),
            description_placeholders={
                "siren_behavior": (
                    "Optional. Sirens are alarm outputs only. Moisture evidence still decides wet or dry. "
                    "A service request does not prove that a siren physically sounded."
                ),
                "unavailable_sirens": unavailable,
            },
        )

    async def async_step_water_safety_shutoff_valves(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        backend = await async_get_setup_backend(self.hass, self.config_entry)
        editor = await async_load_water_safety_shutoff_valves_editor(
            self.hass,
            backend.repository,
            self.config_entry.data,
            snapshot_id=_id("ha-water-shutoff-valves-snapshot"),
            captured_at=_now(),
        )
        errors: dict[str, str] = {}
        target_ids = (
            _water_entity_targets_input(user_input.get(WATER_SHUTOFF_VALVE_TARGETS))
            if user_input is not None
            else editor.selected_target_ids
        )
        if user_input is not None:
            try:
                await async_save_water_safety_shutoff_valves_draft(
                    backend.repository,
                    editor,
                    target_ids=target_ids,
                    saved_at=_now(),
                    report_id=_id("ha-water-shutoff-valves-report"),
                )
            except (KeyError, SetupConflictError, SetupNotFoundError, TypeError, ValueError, ValidationError):
                errors[WATER_SHUTOFF_VALVE_TARGETS] = "invalid_water_shutoff_valve_targets"
            else:
                return await self.async_step_water_safety()

        return self._show_water_safety_shutoff_valves_form(editor, target_ids=target_ids, errors=errors)

    def _show_water_safety_shutoff_valves_form(
        self,
        editor: WaterSafetyShutoffValvesEditor,
        *,
        target_ids: tuple[str, ...],
        errors: Mapping[str, str],
    ) -> ConfigFlowResult:
        candidates = list(editor.compatible_target_ids)
        candidates.extend(target for target in target_ids if target not in candidates)
        unavailable = ", ".join(editor.unavailable_target_ids) or "None"
        return self.async_show_form(
            step_id="water_safety_shutoff_valves",
            data_schema=_water_safety_shutoff_valves_schema(
                target_ids=target_ids,
                candidate_entity_ids=tuple(candidates),
            ),
            errors=dict(errors),
            description_placeholders={
                "shutoff_valve_behavior": (
                    "Optional. On wet detection Controlel requests every selected water shutoff valve to close. "
                    "That is a close request only, not proof of physical valve position. Clearing moisture never "
                    "reopens water."
                ),
                "unavailable_shutoff_valves": unavailable,
            },
        )

    async def async_step_water_safety_validation(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        backend = await async_get_setup_backend(self.hass, self.config_entry)
        view = await async_build_water_safety_configure_view(backend.repository, self.config_entry.data)
        if view.draft is None:
            if view.active_revision is not None:
                summary = (
                    "NO DRAFT CHANGES. Active Water Safety remains in effect. "
                    "Review & activate is only needed after you save draft changes."
                )
            else:
                summary = (
                    "Water Safety is NOT ACTIVE and there are NO DRAFT CHANGES. "
                    "Open Area & moisture sensor to configure the required settings."
                )
            return self.async_show_menu(
                step_id="water_safety_validation",
                menu_options=["back_to_water_safety"],
                description_placeholders={"validation_summary": summary},
            )

        draft = view.draft
        snapshot_id = str(
            draft.lineage.get("created_from_discovery_snapshot_id") or _id("ha-water-validation-snapshot")
        )
        service = await async_get_setup_service(
            self.hass,
            self.config_entry,
            module_key=WATER_SAFETY_MODULE_KEY,
        )
        await service.validate_water_draft(
            draft.draft_id,
            snapshot_id=snapshot_id,
            evaluated_at=_now(),
            report_id=_id("ha-water-validation-report"),
            notification_roles=tuple(draft.settings.get("notification_target_roles", ())),
            siren_roles=tuple(draft.settings.get("siren_target_roles", ())),
            preferred_area_id=_optional_input(draft.settings.get("area_id")),
        )
        validation = await backend.repository.get_latest_validation_report(draft.draft_id)
        activation_ready = bool(validation is not None and validation.assesses(draft) and validation.activation_ready)
        summary = (
            "READY TO ACTIVATE. Continue to create an immutable configuration; "
            "the active Water Safety configuration remains unchanged until the final confirmation."
            if activation_ready
            else _water_validation_user_summary(draft, validation)
        )
        if user_input is None or not activation_ready:
            return self.async_show_form(
                step_id="water_safety_validation",
                data_schema=vol.Schema({}),
                errors=({"base": "water_safety_validation_failed"} if user_input is not None else {}),
                description_placeholders={"validation_summary": summary},
            )

        active_revision = view.active_revision
        active_reference = (
            view.active if view.active is not None and view.active.module_key == WATER_SAFETY_MODULE_KEY else None
        )
        revision_number = active_revision.revision + 1 if active_revision is not None else 1
        configuration_id = (
            active_revision.configuration_id if active_revision is not None else _id("ha-water-configuration")
        )
        core_version = await self.hass.async_add_executor_job(metadata.version, "controlel")
        canonicalized = await service.canonicalize_water_draft(
            draft.draft_id,
            snapshot_id=snapshot_id,
            created_at=_now(),
            validation_report_id=_id("ha-water-canonical-validation"),
            configuration_id=configuration_id,
            revision_id=_id("ha-water-canonical"),
            revision=revision_number,
            actor=f"home_assistant:{self.context.get('user_id') or 'admin'}",
            source="home_assistant_native_configure",
            change_kind="UPDATE" if active_reference is not None else "CREATE",
            reason="native_home_assistant_water_safety_configure",
            core_version=core_version,
            integration_version=INTEGRATION_VERSION,
            parent_revision_id=(active_reference.canonical_revision_id if active_reference is not None else None),
            notification_roles=tuple(draft.settings.get("notification_target_roles", ())),
            siren_roles=tuple(draft.settings.get("siren_target_roles", ())),
            preferred_area_id=_optional_input(draft.settings.get("area_id")),
        )
        if canonicalized.canonical_revision_id is None:
            raise SetupConflictError("Water Safety canonicalization did not produce a revision")
        self._water_activation_candidate_id = canonicalized.canonical_revision_id
        self._water_activation_draft = (draft.draft_id, draft.revision)
        return await self.async_step_water_safety_activate()

    async def async_step_water_safety_abandon(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        backend = await async_get_setup_backend(self.hass, self.config_entry)
        view = await async_build_water_safety_configure_view(backend.repository, self.config_entry.data)
        if view.draft is None:
            return await self.async_step_water_safety()
        if user_input is None:
            return self.async_show_form(step_id="water_safety_abandon", data_schema=vol.Schema({}))
        await backend.repository.delete_draft(view.draft.draft_id, expected_revision=view.draft.revision)
        return await self.async_step_water_safety()

    async def async_step_water_safety_activate(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        candidate_id = self._water_activation_candidate_id
        draft_identity = self._water_activation_draft
        if candidate_id is None or draft_identity is None:
            raise SetupConflictError("Water Safety flow has no reviewed activation candidate")
        if user_input is None:
            return self.async_show_form(
                step_id="water_safety_activate",
                data_schema=vol.Schema({}),
            )

        try:
            await WaterSafetyActivationService().activate_canonical_revision(
                self.hass,
                self.config_entry,
                candidate_id,
                attempt_id=_id("ha-water-activation"),
            )
        except Exception:
            LOGGER.exception("Native Water Safety activation failed")
            return self.async_show_form(
                step_id="water_safety_activate",
                data_schema=vol.Schema({}),
                errors={"base": "water_safety_activation_failed"},
            )

        backend = await async_get_setup_backend(self.hass, self.config_entry)
        try:
            await backend.repository.delete_draft(
                draft_identity[0],
                expected_revision=draft_identity[1],
            )
        except (SetupConflictError, SetupNotFoundError):
            LOGGER.warning(
                "Activated Water Safety revision %s but retained a concurrently changed draft",
                candidate_id,
            )
        return self.async_create_entry(title="", data={})

    async def _async_step_water_safety_section(
        self,
        step_id: str,
        section: WaterSafetySection,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        del user_input
        view = await async_build_water_safety_configure_view(
            (await async_get_setup_backend(self.hass, self.config_entry)).repository,
            self.config_entry.data,
        )
        return self.async_show_menu(
            step_id=step_id,
            menu_options=["back_to_water_safety"],
            description_placeholders={"section_detail": water_safety_section_detail(view, section)},
        )

    async def async_step_general_hub(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        del user_input
        return self.async_show_menu(
            step_id="general_hub",
            menu_options=list(GENERAL_MENU_OPTIONS),
            description_placeholders={
                "general_summary": _general_summary(self.config_entry.data),
            },
        )

    async def _authority_kind(self) -> str:
        legacy = bool(
            set(self.config_entry.data) - {ACTIVE_REFERENCE_KEY, ACTIVE_REFERENCES_KEY} or self.config_entry.options
        )
        has_canonical_authority = bool(
            self.config_entry.data.get(ACTIVE_REFERENCE_KEY) is not None
            or self.config_entry.data.get(ACTIVE_REFERENCES_KEY) is not None
        )
        if legacy and has_canonical_authority:
            return "mixed"
        active = active_reference_for_module(self.config_entry.data, HeatingSetupAdapter.module_key)
        if active is None:
            return "legacy" if legacy else "empty"
        backend = await async_get_setup_backend(self.hass, self.config_entry)
        revision = await backend.repository.get_canonical_revision(active.canonical_revision_id)
        return "v3" if isinstance(revision, CanonicalConfigurationRevisionV3) else "v2"

    async def async_step_start_greenfield(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                now = _now()
                snapshot = await _snapshot(self.hass, now)
                self._draft = await (await self._service()).start_greenfield(
                    draft_id=_id("ha-greenfield-draft"),
                    created_at=now,
                    snapshot_id=_id("ha-greenfield-snapshot"),
                    bindings=_greenfield_bindings(snapshot, user_input),
                )
                self._load_document()
                return await self.async_step_heating()
            except (KeyError, SetupConflictError, SetupNotFoundError, TypeError, ValueError, ValidationError):
                errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="start_greenfield", data_schema=_greenfield_schema(user_input or {}), errors=errors
        )

    async def async_step_edit_active(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        del user_input
        active = active_reference_for_module(self.config_entry.data, HeatingSetupAdapter.module_key)
        if active is None:
            raise SetupConflictError("config entry has no active Heating configuration")
        self._draft = await (await self._service()).edit_from_active(
            draft_id=_id("ha-edit-draft"), created_at=_now(), expected_active_generation=active.generation
        )
        self._load_document()
        return await self.async_step_heating()

    async def async_step_convert_v2(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="convert_v2", data_schema=vol.Schema({}))
        active = active_reference_for_module(self.config_entry.data, HeatingSetupAdapter.module_key)
        if active is None:
            raise SetupConflictError("config entry has no active Heating configuration")
        now = _now()
        review = await (await self._service()).convert_v2(
            source_revision_id=active.canonical_revision_id,
            draft_id=_id("ha-v2-conversion-draft"),
            projection_revision_id=_id("ha-v3-projection"),
            created_at=now,
            snapshot_id=_id("ha-v2-conversion-snapshot"),
            expected_active_revision_id=active.canonical_revision_id,
            expected_active_generation=active.generation,
        )
        return await self._load_review(review)

    async def async_step_convert_legacy(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="convert_legacy", data_schema=vol.Schema({}))
        now = _now()
        core_version = await self.hass.async_add_executor_job(metadata.version, "controlel")
        review = await (await self._service()).convert_legacy(
            draft_id=_id("ha-legacy-conversion-draft"),
            v2_revision_id=_id("ha-legacy-v2-projection"),
            projection_revision_id=_id("ha-legacy-v3-projection"),
            created_at=now,
            snapshot_id=_id("ha-legacy-conversion-snapshot"),
            core_version=core_version,
            integration_version=INTEGRATION_VERSION,
        )
        return await self._load_review(review)

    async def _load_review(self, review: Any) -> ConfigFlowResult:
        if review.draft is None:
            return self.async_abort(reason="conversion_not_ready")
        self._draft = review.draft
        self._load_document()
        return await self.async_step_heating()

    async def async_step_resume_draft(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        service = await self._service()
        drafts = await service.list_drafts()
        if user_input is not None:
            self._draft = await service.reopen_draft(str(user_input["draft_id"]))
            self._load_document()
            return await self.async_step_heating()
        return self.async_show_form(step_id="resume_draft", data_schema=_draft_schema(drafts))

    async def async_step_abandon_draft(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        service = await self._service()
        drafts = await service.list_drafts()
        if user_input is not None:
            draft = await service.reopen_draft(str(user_input["draft_id"]))
            await service.abandon_draft(draft.draft_id, expected_revision=draft.revision)
            return self.async_abort(reason="draft_abandoned")
        return self.async_show_form(step_id="abandon_draft", data_schema=_draft_schema(drafts))

    async def async_step_abandon_current(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="abandon_current", data_schema=vol.Schema({}))
        draft = self._require_draft()
        await (await self._service()).abandon_draft(draft.draft_id, expected_revision=draft.revision)
        return self.async_abort(reason="draft_abandoned")

    def _load_document(self) -> None:
        self._document = self._require_draft().scopes.model_dump(mode="json", by_alias=True)

    def _require_draft(self) -> CanonicalConfigurationDraftV3:
        if self._draft is None:
            raise SetupConflictError("canonical v3 flow has no draft")
        return self._draft

    def _require_document(self) -> dict[str, Any]:
        if self._document is None:
            raise SetupConflictError("canonical v3 flow has no editable document")
        return self._document

    async def async_step_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        document = self._require_document()
        zone = document["heating"]["zones"][0]
        if user_input is not None:
            try:
                snapshot = await _snapshot(self.hass, _now())
                zone["display_name"] = str(user_input[ZONE_NAME]).strip()
                zone["topology"]["area_reference"] = _reference_json(snapshot, user_input.get(ZONE_AREA), HA_AREA_KIND)
                zone["topology"]["floor_reference"] = _reference_json(
                    snapshot, user_input.get(ZONE_FLOOR), HA_FLOOR_KIND
                )
                policy = zone["demand_policy"]
                policy["target_temperature_celsius"] = user_input[TARGET_TEMPERATURE]
                policy["heating_turn_on_differential_celsius"] = user_input[TURN_ON_DIFFERENTIAL]
                policy["heating_turn_off_differential_celsius"] = user_input[TURN_OFF_DIFFERENTIAL]
                policy["heat_demand_confirmation_seconds"] = user_input[DEMAND_CONFIRMATION]
                ConfigurationScopesV3.model_validate(document)
                await self._persist_heating_document()
                return await self.async_step_heating()
            except (KeyError, TypeError, ValueError, ValidationError):
                return self.async_show_form(
                    step_id="zone", data_schema=_zone_schema(zone), errors={"base": "invalid_configuration"}
                )
        return self.async_show_form(step_id="zone", data_schema=_zone_schema(zone))

    async def async_step_sensor(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        document = self._require_document()
        sensor_data = document["heating"]["zones"][0]["primary_temperature_sensor"]
        demand = document["heating"]["zones"][0]["demand_policy"]
        if user_input is not None:
            try:
                snapshot = await _snapshot(self.hass, _now())
                sensor_data["display_name"] = str(user_input[SENSOR_NAME]).strip()
                sensor_data["provider_reference"] = _reference_json(snapshot, user_input[TEMPERATURE_ENTITY])
                demand["primary_measurement_max_age_seconds"] = user_input[MEASUREMENT_MAX_AGE]
                ConfigurationScopesV3.model_validate(document)
                await self._persist_heating_document()
                return await self.async_step_heating()
            except (KeyError, TypeError, ValueError, ValidationError):
                return self.async_show_form(
                    step_id="sensor",
                    data_schema=_sensor_schema(sensor_data, demand),
                    errors={"base": "invalid_configuration"},
                )
        return self.async_show_form(step_id="sensor", data_schema=_sensor_schema(sensor_data, demand))

    async def async_step_heat_source(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        document = self._require_document()
        source = document["heating"]["heat_sources"][0]
        if user_input is not None:
            try:
                snapshot = await _snapshot(self.hass, _now())
                source["display_name"] = str(user_input[SOURCE_NAME]).strip()
                source["provider_reference"] = _reference_json(snapshot, user_input.get(SOURCE_ENTITY))
                _apply_command_strategy(source, snapshot, user_input)
                source["observations"]["reported_actuator_state_reference"] = _reference_json(
                    snapshot, user_input.get(REPORTED_SOURCE_STATE)
                )
                ConfigurationScopesV3.model_validate(document)
                await self._persist_heating_document()
                return await self.async_step_heating()
            except (KeyError, TypeError, ValueError, ValidationError):
                return self.async_show_form(
                    step_id="heat_source",
                    data_schema=_heat_source_schema(source),
                    errors={"base": "invalid_configuration"},
                )
        return self.async_show_form(step_id="heat_source", data_schema=_heat_source_schema(source))

    async def async_step_heat_delivery(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        document = self._require_document()
        delivery = document["heating"]["heat_delivery"][0]
        if user_input is not None:
            try:
                snapshot = await _snapshot(self.hass, _now())
                delivery["mode"] = user_input[DELIVERY_MODE]
                delivery["actuator_reference"] = _reference_json(snapshot, user_input.get(DELIVERY_ACTUATOR))
                delivery["ownership"] = user_input[DELIVERY_OWNERSHIP]
                delivery["assist_policy"] = user_input[DELIVERY_ASSIST_POLICY]
                delivery["assist_target_celsius"] = user_input[DELIVERY_ASSIST_TARGET]
                ConfigurationScopesV3.model_validate(document)
                await self._persist_heating_document()
                return await self.async_step_heating()
            except (KeyError, TypeError, ValueError, ValidationError):
                return self.async_show_form(
                    step_id="heat_delivery",
                    data_schema=_heat_delivery_schema(delivery),
                    errors={"base": "invalid_configuration"},
                )
        return self.async_show_form(step_id="heat_delivery", data_schema=_heat_delivery_schema(delivery))

    async def async_step_safety_timing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        document = self._require_document()
        global_config = document["heating"]["global"]
        protection = document["heating"]["heat_sources"][0]["protection"]
        if user_input is not None:
            try:
                global_config["maximum_future_skew_seconds"] = user_input[MAXIMUM_FUTURE_SKEW]
                protection["indeterminate_grace_period_seconds"] = user_input[INDETERMINATE_GRACE]
                protection["indeterminate_timeout_action"] = user_input[INDETERMINATE_ACTION]
                protection["minimum_heating_on_seconds"] = user_input[MINIMUM_ON]
                protection["minimum_heating_off_seconds"] = user_input[MINIMUM_OFF]
                ConfigurationScopesV3.model_validate(document)
                await self._persist_heating_document()
                return await self.async_step_heating()
            except (KeyError, TypeError, ValueError, ValidationError):
                return self.async_show_form(
                    step_id="safety_timing",
                    data_schema=_safety_schema(global_config, protection),
                    errors={"base": "invalid_configuration"},
                )
        return self.async_show_form(step_id="safety_timing", data_schema=_safety_schema(global_config, protection))

    async def async_step_diagnostics(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        document = self._require_document()
        diagnostics = document["diagnostics"]
        diagnostics_summary = await self._heating_diagnostics_summary()
        if user_input is not None:
            try:
                diagnostics["steady_profile"] = user_input[DIAGNOSTIC_PROFILE]
                diagnostics["debug_policy"]["configured_duration_seconds"] = user_input[DEBUG_DURATION]
                ConfigurationScopesV3.model_validate(document)
                await self._persist_heating_document()
                return await self.async_step_heating()
            except (KeyError, TypeError, ValueError, ValidationError):
                return self.async_show_form(
                    step_id="diagnostics",
                    data_schema=_diagnostics_schema(diagnostics),
                    errors={"base": "invalid_configuration"},
                    description_placeholders={"diagnostics_summary": diagnostics_summary},
                )
        return self.async_show_form(
            step_id="diagnostics",
            data_schema=_diagnostics_schema(diagnostics),
            description_placeholders={"diagnostics_summary": diagnostics_summary},
        )

    async def _heating_diagnostics_summary(self) -> str:
        draft = self._require_draft()
        validation = await self._async_heating_overview_validation(await self._service(), draft)
        readiness = (
            "READY TO ACTIVATE — required Home Assistant references are currently usable."
            if validation is not None and validation.activation_ready
            else (
                f"NOT READY — {_heating_validation_attention(validation)}"
                if validation is not None
                else "READINESS UNKNOWN — Home Assistant could not evaluate this saved draft."
            )
        )
        failures = lifecycle_failures_for_entry(self.hass, self.config_entry.entry_id)
        setup_failure = _lifecycle_failure_summary(failures["setup"])
        activation_failure = _lifecycle_failure_summary(failures["activation"])
        return (
            f"Configuration readiness: {readiness} Last setup failure: {setup_failure}. "
            f"Last activation failure: {activation_failure}. Full exception details remain in "
            "Settings → System → Logs."
        )

    async def async_step_notifications(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        document = self._require_document()
        notifications = document["notifications"]
        if user_input is not None:
            try:
                notifications["enabled"] = user_input[NOTIFICATIONS_ENABLED]
                notifications["recipients"] = _notification_recipients(
                    user_input[NOTIFICATION_RECIPIENTS], notifications["recipients"]
                )
                notifications["maximum_per_window"] = int(user_input[NOTIFICATION_MAXIMUM])
                notifications["rate_window_seconds"] = user_input[NOTIFICATION_WINDOW]
                notifications["critical_maximum_per_window"] = int(user_input[CRITICAL_NOTIFICATION_MAXIMUM])
                notifications["critical_rate_window_seconds"] = user_input[CRITICAL_NOTIFICATION_WINDOW]
                notifications["history_capacity"] = int(user_input[NOTIFICATION_HISTORY])
                ConfigurationScopesV3.model_validate(document)
                await self._persist_heating_document()
                return await self.async_step_heating()
            except (KeyError, TypeError, ValueError, ValidationError):
                return self.async_show_form(
                    step_id="notifications",
                    data_schema=_notifications_schema(notifications),
                    errors={"base": "invalid_configuration"},
                )
        return self.async_show_form(step_id="notifications", data_schema=_notifications_schema(notifications))

    async def async_step_save_draft(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="save_draft", data_schema=vol.Schema({}))
        draft = self._require_draft()
        self._draft = await (await self._service()).update_draft(
            draft.draft_id,
            expected_revision=draft.revision,
            updated_at=_now(),
            configuration_scopes=ConfigurationScopesV3.model_validate(self._require_document()),
        )
        self._load_document()
        return await self.async_step_draft_saved()

    async def async_step_draft_saved(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        del user_input
        return self.async_show_menu(
            step_id="draft_saved",
            menu_options=["validate", "continue_editing", "abandon_current"],
            description_placeholders={"draft_id": self._require_draft().draft_id},
        )

    async def async_step_continue_editing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        del user_input
        return await self.async_step_heating()

    async def _persist_heating_document(self) -> None:
        draft = self._require_draft()
        scopes = ConfigurationScopesV3.model_validate(self._require_document())
        if canonical_json(scopes.model_dump(mode="json", by_alias=True)) == canonical_json(
            draft.scopes.model_dump(mode="json", by_alias=True)
        ):
            return
        self._draft = await (await self._service()).update_draft(
            draft.draft_id,
            expected_revision=draft.revision,
            updated_at=_now(),
            configuration_scopes=scopes,
        )
        self._load_document()

    async def async_step_heating_review(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        draft = self._require_draft()
        preparation_failure: str | None = None
        self._validation = await (await self._service()).validate_draft(
            draft.draft_id,
            report_id=_id("ha-heating-validation"),
            snapshot_id=_id("ha-heating-validation-snapshot"),
            evaluated_at=_now(),
        )
        if user_input is not None and self._validation.activation_ready:
            try:
                return await self.async_step_canonicalize({})
            except (SetupConflictError, SetupNotFoundError) as error:
                LOGGER.exception("Heating draft could not be prepared for activation")
                self._validation = await (await self._service()).validate_draft(
                    draft.draft_id,
                    report_id=_id("ha-heating-revalidation"),
                    snapshot_id=_id("ha-heating-revalidation-snapshot"),
                    evaluated_at=_now(),
                )
                if self._validation.activation_ready:
                    preparation_failure = _heating_activation_failure_reason(error, self._validation)
        errors = (
            {"base": "heating_review_failed"}
            if preparation_failure is not None
            else ({} if self._validation.activation_ready else {"base": "heating_not_ready"})
        )
        review_summary = _heating_review_summary(self._validation)
        if preparation_failure is not None:
            review_summary = f"ACTIVATION PREPARATION STOPPED. {preparation_failure} {review_summary}"
        return self.async_show_form(
            step_id="heating_review",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"heating_review_summary": review_summary},
        )

    async def async_step_validate(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="validate", data_schema=vol.Schema({}))
        draft = self._require_draft()
        self._validation = await (await self._service()).validate_draft(
            draft.draft_id,
            report_id=_id("ha-validation"),
            snapshot_id=_id("ha-validation-snapshot"),
            evaluated_at=_now(),
        )
        return await self.async_step_validation_result()

    async def async_step_validation_result(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._validation is None:
            raise SetupConflictError("canonical v3 flow has no validation")
        issues = ", ".join(self._validation.issue_codes) or "None"
        if not self._validation.activation_ready:
            return self.async_show_form(
                step_id="validation_result",
                data_schema=vol.Schema({}),
                errors={"base": "validation_failed"},
                description_placeholders={"validation_issues": issues},
            )
        if user_input is not None:
            return await self.async_step_canonicalize()
        return self.async_show_form(
            step_id="validation_result",
            data_schema=vol.Schema({}),
            description_placeholders={"validation_issues": issues},
        )

    async def async_step_canonicalize(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="canonicalize", data_schema=vol.Schema({}))
        draft = self._require_draft()
        if self._validation is None:
            raise SetupConflictError("canonical v3 flow has no validation")
        change_kind = "CREATE" if draft.base_active_revision_id is None else "UPDATE"
        if draft.lineage.get("authoring_origin") == "canonical_v2_conversion":
            change_kind = "MIGRATE"
        core_version = await self.hass.async_add_executor_job(metadata.version, "controlel")
        self._candidate = await (await self._service()).canonicalize_draft(
            draft.draft_id,
            validation_report_id=self._validation.report_id,
            revision_id=_id("ha-canonical-v3"),
            snapshot_id=_id("ha-canonicalize-snapshot"),
            created_at=_now(),
            actor=f"home_assistant:{self.context.get('user_id') or 'admin'}",
            source="home_assistant_native_configure",
            change_kind=change_kind,
            reason="native_home_assistant_configure",
            core_version=core_version,
            integration_version=INTEGRATION_VERSION,
        )
        return await self.async_step_heating_activate()

    async def async_step_heating_activate(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._candidate is None:
            raise SetupConflictError("canonical v3 flow has no canonical candidate")
        if user_input is None:
            self._heating_activation_failure_reason = None
            return self.async_show_form(
                step_id="heating_activate",
                data_schema=vol.Schema({}),
                description_placeholders={"activation_summary": _heating_activation_summary()},
            )
        draft = self._require_draft()
        try:
            await async_activate_canonical_revision(
                self.hass,
                self.config_entry,
                revision_id=self._candidate.revision_id,
                semantic_configuration_fingerprint=self._candidate.semantic_configuration_fingerprint,
                expected_active_revision_id=draft.base_active_revision_id,
                expected_active_generation=draft.base_active_generation,
                attempt_id=_id("ha-activation"),
            )
        except Exception as error:
            LOGGER.exception("Heating canonical activation failed")
            record_lifecycle_failure(self.hass, self.config_entry, phase="activation", error=error)
            failure_validation = self._validation
            try:
                failure_validation = await (await self._service()).validate_draft(
                    draft.draft_id,
                    report_id=_id("ha-heating-activation-failure-validation"),
                    snapshot_id=_id("ha-heating-activation-failure-snapshot"),
                    evaluated_at=_now(),
                )
            except Exception:
                LOGGER.exception("Heating draft could not be revalidated after activation failure")
            self._validation = failure_validation
            self._heating_activation_failure_reason = _heating_activation_failure_reason(error, failure_validation)
            return self.async_show_form(
                step_id="heating_activate",
                data_schema=vol.Schema({}),
                errors={"base": "heating_activation_failed"},
                description_placeholders={
                    "activation_summary": _heating_activation_summary(self._heating_activation_failure_reason)
                },
            )
        try:
            await (await self._service()).abandon_draft(draft.draft_id, expected_revision=draft.revision)
        except (SetupConflictError, SetupNotFoundError):
            LOGGER.warning("Activated Heating draft could not be finalized", exc_info=True)
        return self.async_create_entry(title="", data={})


def _heating_menu_summary(
    *,
    active: Any | None,
    drafts: tuple[CanonicalConfigurationDraftV3, ...],
    current: CanonicalConfigurationDraftV3 | None,
    overview_draft: CanonicalConfigurationDraftV3 | None,
    validation: CanonicalConfigurationValidationV3 | None,
) -> str:
    active_summary = "ACTIVE" if active is not None else "NOT ACTIVE"
    if current is not None:
        draft_summary = "DRAFT CHANGES — section edits are durable but inactive."
    elif drafts:
        draft_summary = (
            "DRAFT CHANGES — continue the saved inactive draft to edit or review."
            if len(drafts) == 1
            else f"DRAFT CHANGES — {len(drafts)} saved inactive drafts; continue one to edit or review."
        )
    else:
        draft_summary = "NO DRAFT CHANGES."

    if overview_draft is None:
        readiness = (
            "READY TO ACTIVATE already applies to the active configuration."
            if active is not None
            else ("NEEDS ATTENTION — start Basic setup and provide a Temperature sensor and Heat source commands.")
        )
    elif validation is None:
        readiness = "NEEDS ATTENTION — continue the saved draft and review the required sections."
    elif validation.activation_ready:
        readiness = "READY TO ACTIVATE — all required runtime references are available."
    else:
        readiness = f"NEEDS ATTENTION — {_heating_validation_attention(validation)}"

    return (
        f"Heating: {active_summary}. Draft: {draft_summary} Readiness: {readiness}\n\n"
        "BASIC: Zone & demand. REQUIRED: Temperature sensor; Heat source commands. "
        "OPTIONAL: Heat delivery; Notifications. ADVANCED: Safety & timing; Diagnostics.\n\n"
        "Saving a section changes only the draft. The currently active Heating configuration and Water Safety "
        "stay unchanged until you explicitly choose Review & activate and confirm activation."
    )


def _heating_review_summary(validation: CanonicalConfigurationValidationV3) -> str:
    if validation.activation_ready:
        return (
            "READY TO ACTIVATE. The required/basic setup is complete and all required Home Assistant entity "
            "references are currently usable. Optional and advanced sections may keep their safe defaults. "
            "Continuing prepares an immutable candidate; the draft does not become active until the separate "
            "activation confirmation."
        )
    return (
        f"NOT READY TO ACTIVATE. {_heating_validation_attention(validation)} "
        "Return to Heating, open the named section, save the correction, then review again. The saved draft "
        "remains inactive and the current active Heating and Water Safety configurations are unchanged."
    )


def _heating_validation_attention(validation: CanonicalConfigurationValidationV3) -> str:
    problems = []
    for health in validation.reference_health:
        if not health.activation_required or health.runtime_ready:
            continue
        location = _heating_reference_location(health.canonical_path)
        status = str(health.status.value)
        explanation = {
            "MISSING": "the saved entity no longer exists in Home Assistant",
            "RECOVERY_CANDIDATE": "Home Assistant found a possible replacement that must be selected explicitly",
            "AMBIGUOUS": "more than one possible replacement exists; select the correct entity explicitly",
            "ENVIRONMENT_MISMATCH": "the saved entity belongs to a different Home Assistant installation",
        }.get(status, "the saved entity reference cannot currently be used")
        problems.append(f"{location}: {explanation}")
    if problems:
        return "Needs attention — " + "; ".join(dict.fromkeys(problems)) + "."
    return "Needs attention — validation could not confirm the required Home Assistant entities."


def _heating_section_for_reference(path: str) -> str:
    if "primary_temperature_sensor" in path:
        return "Temperature sensor"
    if "heat_delivery" in path:
        return "Heat delivery"
    if "heat_sources" in path:
        return "Heat source commands"
    if "zones" in path:
        return "Zone & demand"
    return "Basic Heating setup"


def _heating_reference_location(path: str) -> str:
    section = _heating_section_for_reference(path)
    if "primary_temperature_sensor" in path:
        field = "Temperature sensor"
    elif "enable_permission.command_target_reference" in path:
        field = "Enable target entity"
    elif "disable_permission.command_target_reference" in path:
        field = "Disable target entity"
    elif "reported_actuator_state_reference" in path:
        field = "Reported actuator-state entity"
    elif "heat_delivery" in path and "actuator_reference" in path:
        field = "Heat-delivery actuator"
    else:
        return section
    return f"{section} — {field}"


def _heating_activation_summary(failure_reason: str | None = None) -> str:
    if failure_reason is not None:
        return (
            f"ACTIVATION DID NOT COMPLETE. {failure_reason} The saved draft and every previously active module "
            "configuration were retained."
        )
    return (
        "READY TO ACTIVATE. Confirming changes only Heating authority and reloads Controlel. Water Safety is "
        "unchanged. Successful activation finalizes this draft. If activation cannot complete safely, the saved "
        "draft and all current active module configurations are retained."
    )


def _lifecycle_failure_summary(failure: object | None) -> str:
    if not isinstance(failure, Mapping):
        return "none recorded"
    chain = failure.get("exception_chain")
    first = chain[0] if isinstance(chain, list) and chain and isinstance(chain[0], Mapping) else {}
    exception_type = str(first.get("exception_type") or "unexpected error")
    occurred_at = str(failure.get("occurred_at") or "an unknown time")
    return f"{exception_type} at {occurred_at}"


def _heating_activation_failure_reason(
    error: Exception,
    validation: CanonicalConfigurationValidationV3 | None,
) -> str:
    if validation is not None and not validation.activation_ready:
        return (
            f"{_heating_validation_attention(validation)} Reopen the named section, select an available entity, "
            "save, and run Review & activate again."
        )
    error_chain = _exception_chain(error)
    messages = [str(item).strip() for item in error_chain if str(item).strip()]
    message = " | ".join(messages).lower()
    reference_path = _heating_reference_path(messages)
    if reference_path is not None:
        return (
            f"{_heating_reference_location(reference_path)}: the saved Home Assistant entity cannot be resolved "
            "for runtime. Reopen that section, select an available entity, save, and review again."
        )
    if "active" in message and ("changed" in message or "generation" in message or "authority" in message):
        return (
            "The active Heating configuration changed while this draft was being prepared. Return to Heating "
            "and start a new edit from the current active configuration."
        )
    if "reference" in message or "not activation-ready" in message or "not runtime-ready" in message:
        return (
            "A required Home Assistant entity changed after review. Return to Heating, review the Temperature "
            "sensor and Heat source commands sections, and try again."
        )
    if "config-entry reload did not complete" in message:
        home_assistant_reason = next(
            (
                safe_reason
                for item in error_chain
                if (safe_reason := _safe_home_assistant_reason(getattr(item, "home_assistant_reason", None)))
                is not None
            ),
            None,
        )
        reason_detail = "" if home_assistant_reason is None else f" Home Assistant reported: {home_assistant_reason}."
        return (
            "Home Assistant did not complete the Controlel reload."
            f"{reason_detail} Open Settings → System → Logs, correct the first Controlel setup error, and try "
            "Review & activate again."
        )
    if "did not load the prepared canonical revision" in message:
        return (
            "Home Assistant reloaded Controlel but did not load the saved Heating configuration. Reload the "
            "Controlel integration, reopen Heating, and run Review & activate again."
        )
    if "readiness boundary" in message:
        return (
            "The reloaded Heating runtime did not finish starting. Check Settings → System → Logs for the first "
            "Controlel setup error, then verify Temperature sensor and Heat source commands before retrying."
        )
    if any(isinstance(item, SetupNotFoundError) for item in error_chain):
        return (
            "The saved Heating draft or activation candidate is no longer available. "
            "Reopen Heating and review it again."
        )
    home_assistant_error = next((item for item in error_chain if isinstance(item, HomeAssistantError)), None)
    if home_assistant_error is not None and str(home_assistant_error).strip():
        return f"Home Assistant reported: {str(home_assistant_error).strip()}."
    return (
        "The candidate Heating runtime did not pass the safe activation checks. Check the Controlel logs and try again."
    )


def _exception_chain(error: Exception) -> tuple[BaseException, ...]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    return tuple(chain)


def _heating_reference_path(messages: list[str]) -> str | None:
    for message in messages:
        match = re.search(r"heating\.[a-zA-Z0-9_.\[\]]+", message)
        if match is not None:
            return match.group(0).rstrip(".")
    return None


def _safe_home_assistant_reason(reason: object) -> str | None:
    if not isinstance(reason, str):
        return None
    normalized = " ".join(reason.split())
    if not normalized or len(normalized) > 240:
        return None
    lowered = normalized.lower()
    if any(internal in lowered for internal in ("canonical", "draft", "revision", "fingerprint")):
        return None
    return normalized.rstrip(".")


def _general_summary(entry_data: Mapping[str, Any]) -> str:
    heating = active_reference_for_module(entry_data, HeatingSetupAdapter.module_key)
    water = active_reference_for_module(entry_data, WATER_SAFETY_MODULE_KEY)

    def module_status(active: Any | None) -> str:
        if active is None:
            return "not active"
        return "active"

    return f"{GENERAL_EXPLANATION} Heating is {module_status(heating)}. Water Safety is {module_status(water)}."


_WATER_VALIDATION_ISSUE_LABELS = {
    "water_safety.unsupported_module_contract": "unsupported Water Safety module version",
    "water_safety.invalid_setting": "invalid setting",
    "water_safety.unsupported_binding_role": "unexpected binding",
    "water_safety.required_binding_missing": "required selection missing",
    "water_safety.binding_confirmation_required": "selection needs confirmation",
    "water_safety.stable_reference_required": "selection needs a stable Home Assistant identity",
}


def _water_validation_issue_label(code: str) -> str:
    return _WATER_VALIDATION_ISSUE_LABELS.get(code, "configuration problem")


def _water_validation_user_summary(draft: Any, validation: Any | None) -> str:
    """Build a user-facing Review summary without raw codes or optional-as-required claims."""

    problems: list[str] = []
    settings = dict(getattr(draft, "settings", {}) or {})
    bindings = tuple(getattr(draft, "bindings", ()) or ())
    has_area = bool(_optional_input(settings.get("area_id")))
    has_sensor = any(binding.role == WATER_SAFETY_SENSOR_ROLE for binding in bindings)
    if not has_area:
        problems.append("Open Area & moisture sensor and select an area.")
    if not has_sensor:
        problems.append("Moisture sensor is required. Open Area & moisture sensor and select a moisture/leak sensor.")

    if validation is not None:
        for issue in validation.issues:
            code = getattr(issue, "code", "")
            path = tuple(getattr(issue, "path", ()) or ())
            role = getattr(issue, "module_role", None)
            parameters = getattr(issue, "parameters", None) or {}
            if role is None and isinstance(parameters, Mapping):
                role = parameters.get("role")
            if code == "water_safety.required_binding_missing" and role == WATER_SAFETY_SENSOR_ROLE:
                continue
            if code == "water_safety.unsupported_binding_role":
                continue
            if code == "water_safety.invalid_setting":
                if path and path[0] in {"area_id", "area_name", "zone_id", "zone_name"}:
                    message = "Area selection is incomplete."
                elif path and path[0] in {"sensor_id"}:
                    message = "Moisture sensor is required."
                else:
                    message = "One configured value is invalid. Open the related Water Safety section and correct it."
                if message not in problems:
                    problems.append(message)
                continue
            if code == "water_safety.stable_reference_required":
                message = (
                    "A selected Home Assistant entity needs a stable identity. "
                    "Re-open the related section and choose again."
                )
                if message not in problems:
                    problems.append(message)
                continue
            if code == "water_safety.binding_confirmation_required":
                message = "Confirm the selected bindings in the related Water Safety section."
                if message not in problems:
                    problems.append(message)
                continue
            if code == "water_safety.unsupported_module_contract":
                message = "This Water Safety draft uses an unsupported module version."
                if message not in problems:
                    problems.append(message)
                continue
            if code == "water_safety.required_binding_missing" and isinstance(role, str):
                if role.startswith("water_safety.notification"):
                    message = "A notification target listed in the draft is missing. Open Notifications and save again."
                elif role.startswith("water_safety.siren"):
                    message = "A siren listed in the draft is missing. Open Sirens and save again."
                elif role.startswith("water_safety.shutoff"):
                    message = "A shutoff valve listed in the draft is missing. Open Shutoff valves and save again."
                else:
                    message = "A required selection is missing. Open the related Water Safety section and complete it."
                if message not in problems:
                    problems.append(message)

    if not problems:
        problems.append("Complete the required area and moisture sensor settings.")

    active_note = (
        " The currently active Water Safety configuration remains unchanged."
        if getattr(draft, "base_active_revision_id", None)
        else ""
    )
    return "NEEDS ATTENTION. Draft cannot be activated. " + " ".join(problems) + active_note


def _now() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}:{uuid4().hex}"


async def _snapshot(hass: Any, captured_at: datetime) -> Any:
    return await HomeAssistantDiscoveryAdapter.async_snapshot_from_hass(
        hass, snapshot_id=_id("ha-configure-discovery"), captured_at=captured_at
    )


def _reference(snapshot: Any, selected: object, object_kind: str | None = None) -> Any:
    if selected in (None, ""):
        return None
    value = str(selected)
    for item in snapshot.objects:
        if object_kind is not None and item.object_kind != object_kind:
            continue
        if item.current_locator == value or item.native_id == value:
            return item
    raise ValueError(f"selected Home Assistant reference {value!r} is not registered")


def _reference_json(snapshot: Any, selected: object, object_kind: str | None = None) -> dict[str, Any] | None:
    reference = _reference(snapshot, selected, object_kind)
    return None if reference is None else reference.model_dump(mode="json")


def _locator(reference: Mapping[str, Any] | None) -> str | None:
    if not reference:
        return None
    value = reference.get("current_locator") or reference.get("native_id")
    return str(value) if value else None


def _optional_marker(name: str, value: str | None) -> vol.Marker:
    if value is None:
        return vol.Optional(name)
    return vol.Optional(name, description={"suggested_value": value})


def _suggested_optional_marker(name: str, value: str | None) -> vol.Marker:
    if value is None:
        return vol.Optional(name)
    return vol.Optional(name, description={"suggested_value": value})


def _optional_input(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _notification_targets_input(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise ValueError("notification targets must be a list")
    return tuple(str(item) for item in value)


def _water_entity_targets_input(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise ValueError("Water Safety entity targets must be a list")
    return tuple(str(item) for item in value)


def _water_safety_area_sensor_schema(
    *,
    area_id: str | None,
    sensor_id: str | None,
    candidate_entity_ids: tuple[str, ...],
    show_all: bool,
) -> vol.Schema:
    return vol.Schema(
        {
            _suggested_optional_marker(WATER_AREA, area_id): selector.AreaSelector(),
            _suggested_optional_marker(WATER_MOISTURE_SENSOR, sensor_id): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    filter={"domain": "binary_sensor", "device_class": "moisture"},
                    include_entities=list(candidate_entity_ids),
                )
            ),
            vol.Optional(WATER_SHOW_ALL_COMPATIBLE, default=show_all): selector.BooleanSelector(),
        }
    )


def _water_safety_notifications_schema(
    *,
    target_ids: tuple[str, ...],
    available_target_ids: tuple[str, ...],
    unavailable_target_ids: tuple[str, ...],
    test_requested: bool,
) -> vol.Schema:
    options: list[selector.SelectOptionDict] = [{"value": target, "label": target} for target in available_target_ids]
    options.extend(
        {"value": target, "label": f"{target} (currently unavailable)"}
        for target in unavailable_target_ids
        if target not in available_target_ids
    )
    return vol.Schema(
        {
            vol.Optional(WATER_NOTIFICATION_TARGETS, default=list(target_ids)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(WATER_TEST_NOTIFICATION, default=test_requested): selector.BooleanSelector(),
        }
    )


def _water_safety_sirens_schema(
    *,
    target_ids: tuple[str, ...],
    candidate_entity_ids: tuple[str, ...],
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(WATER_SIREN_TARGETS, default=list(target_ids)): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="siren",
                    include_entities=list(candidate_entity_ids),
                    multiple=True,
                    reorder=True,
                )
            )
        }
    )


def _water_safety_shutoff_valves_schema(
    *,
    target_ids: tuple[str, ...],
    candidate_entity_ids: tuple[str, ...],
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(WATER_SHUTOFF_VALVE_TARGETS, default=list(target_ids)): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="valve",
                    include_entities=list(candidate_entity_ids),
                    multiple=True,
                    reorder=True,
                )
            )
        }
    )


def _number(unit: str | None = None, *, minimum: float | None = None) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX)
    if minimum is not None:
        config["min"] = minimum
    if unit is not None:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _select(values: tuple[str, ...]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=list(values), mode=selector.SelectSelectorMode.DROPDOWN)
    )


def _draft_schema(drafts: tuple[CanonicalConfigurationDraftV3, ...]) -> vol.Schema:
    choices: list[selector.SelectOptionDict] = [
        {"value": item.draft_id, "label": _draft_label(item)} for item in drafts
    ]
    return vol.Schema(
        {
            vol.Required("draft_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=choices, mode=selector.SelectSelectorMode.DROPDOWN)
            )
        }
    )


def _greenfield_schema(values: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(ZONE_NAME, default=values.get(ZONE_NAME, "Living room")): selector.TextSelector(),
            vol.Optional(ZONE_AREA): selector.AreaSelector(),
            vol.Optional(ZONE_FLOOR): selector.FloorSelector(),
            vol.Required(
                SENSOR_NAME, default=values.get(SENSOR_NAME, "Living room temperature")
            ): selector.TextSelector(),
            vol.Required(TEMPERATURE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(filter={"domain": "sensor", "device_class": "temperature"})
            ),
            vol.Required(
                SOURCE_NAME, default=values.get(SOURCE_NAME, "Heat source permission")
            ): selector.TextSelector(),
            vol.Optional(SOURCE_ENTITY): selector.EntitySelector(),
            vol.Required(SOURCE_MODE, default=values.get(SOURCE_MODE, "simple")): _select(("simple", "custom")),
            vol.Required(ENABLE_DOMAIN, default=values.get(ENABLE_DOMAIN, "switch")): selector.TextSelector(),
            vol.Required(ENABLE_SERVICE, default=values.get(ENABLE_SERVICE, "turn_on")): selector.TextSelector(),
            vol.Required(ENABLE_TARGET): selector.EntitySelector(),
            vol.Required(DISABLE_DOMAIN, default=values.get(DISABLE_DOMAIN, "switch")): selector.TextSelector(),
            vol.Required(DISABLE_SERVICE, default=values.get(DISABLE_SERVICE, "turn_off")): selector.TextSelector(),
            vol.Required(DISABLE_TARGET): selector.EntitySelector(),
            vol.Optional(REPORTED_SOURCE_STATE): selector.EntitySelector(),
        }
    )


def _greenfield_bindings(snapshot: Any, values: Mapping[str, Any]) -> dict[str, Any]:
    source: dict[str, Any] = {}
    _apply_command_strategy(source, snapshot, values)
    return {
        "zone_display_name": str(values[ZONE_NAME]).strip(),
        "primary_sensor_display_name": str(values[SENSOR_NAME]).strip(),
        "topology": {
            "area_reference": _reference_json(snapshot, values.get(ZONE_AREA), HA_AREA_KIND),
            "floor_reference": _reference_json(snapshot, values.get(ZONE_FLOOR), HA_FLOOR_KIND),
        },
        "primary_temperature_sensor_reference": _reference_json(snapshot, values[TEMPERATURE_ENTITY]),
        "heat_source_display_name": str(values[SOURCE_NAME]).strip(),
        "heat_source_reference": _reference_json(snapshot, values.get(SOURCE_ENTITY)),
        "command_strategy": source["command_strategy"],
        "observations": {
            "reported_actuator_state_reference": _reference_json(snapshot, values.get(REPORTED_SOURCE_STATE)),
            "physical_operation_reference": None,
        },
    }


def _apply_command_strategy(source: dict[str, Any], snapshot: Any, values: Mapping[str, Any]) -> None:
    mode = str(values[SOURCE_MODE])
    enable_target = _reference_json(snapshot, values[ENABLE_TARGET])
    disable_target = _reference_json(snapshot, values[DISABLE_TARGET])
    enable_domain, enable_service = str(values[ENABLE_DOMAIN]).strip(), str(values[ENABLE_SERVICE]).strip()
    disable_domain, disable_service = str(values[DISABLE_DOMAIN]).strip(), str(values[DISABLE_SERVICE]).strip()
    if mode == "simple":
        if enable_target != disable_target:
            raise ValueError("simple heat-source control requires one target")
        enable_domain, enable_service = "switch", "turn_on"
        disable_domain, disable_service = "switch", "turn_off"
    source["command_strategy"] = {
        "mode": mode,
        "enable_permission": {
            "domain": enable_domain,
            "service": enable_service,
            "command_target_reference": enable_target,
        },
        "disable_permission": {
            "domain": disable_domain,
            "service": disable_service,
            "command_target_reference": disable_target,
        },
    }


def _zone_schema(zone: Mapping[str, Any]) -> vol.Schema:
    topology, policy = zone["topology"], zone["demand_policy"]
    return vol.Schema(
        {
            vol.Required(ZONE_NAME, default=zone["display_name"]): selector.TextSelector(),
            _optional_marker(ZONE_AREA, _locator(topology["area_reference"])): selector.AreaSelector(),
            _optional_marker(ZONE_FLOOR, _locator(topology["floor_reference"])): selector.FloorSelector(),
            vol.Required(TARGET_TEMPERATURE, default=policy["target_temperature_celsius"]): _number("°C"),
            vol.Required(TURN_ON_DIFFERENTIAL, default=policy["heating_turn_on_differential_celsius"]): _number(
                "°C", minimum=0
            ),
            vol.Required(TURN_OFF_DIFFERENTIAL, default=policy["heating_turn_off_differential_celsius"]): _number(
                "°C", minimum=0
            ),
            vol.Required(DEMAND_CONFIRMATION, default=policy["heat_demand_confirmation_seconds"]): _number(
                "s", minimum=0
            ),
        }
    )


def _sensor_schema(sensor_data: Mapping[str, Any], demand: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(SENSOR_NAME, default=sensor_data["display_name"]): selector.TextSelector(),
            vol.Required(
                TEMPERATURE_ENTITY, default=_locator(sensor_data["provider_reference"])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(filter={"domain": "sensor", "device_class": "temperature"})
            ),
            vol.Required(MEASUREMENT_MAX_AGE, default=demand["primary_measurement_max_age_seconds"]): _number(
                "s", minimum=0.001
            ),
        }
    )


def _heat_source_schema(source: Mapping[str, Any]) -> vol.Schema:
    command = source["command_strategy"]
    enable, disable = command["enable_permission"], command["disable_permission"]
    observations = source["observations"]
    return vol.Schema(
        {
            vol.Required(SOURCE_NAME, default=source["display_name"]): selector.TextSelector(),
            _optional_marker(SOURCE_ENTITY, _locator(source["provider_reference"])): selector.EntitySelector(),
            vol.Required(SOURCE_MODE, default=command["mode"]): _select(("simple", "custom")),
            vol.Required(ENABLE_DOMAIN, default=enable["domain"]): selector.TextSelector(),
            vol.Required(ENABLE_SERVICE, default=enable["service"]): selector.TextSelector(),
            vol.Required(
                ENABLE_TARGET, default=_locator(enable["command_target_reference"])
            ): selector.EntitySelector(),
            vol.Required(DISABLE_DOMAIN, default=disable["domain"]): selector.TextSelector(),
            vol.Required(DISABLE_SERVICE, default=disable["service"]): selector.TextSelector(),
            vol.Required(
                DISABLE_TARGET, default=_locator(disable["command_target_reference"])
            ): selector.EntitySelector(),
            _optional_marker(
                REPORTED_SOURCE_STATE, _locator(observations["reported_actuator_state_reference"])
            ): selector.EntitySelector(),
        }
    )


def _heat_delivery_schema(delivery: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(DELIVERY_MODE, default=delivery["mode"]): _select(("unmanaged", "setpoint_assist")),
            _optional_marker(DELIVERY_ACTUATOR, _locator(delivery["actuator_reference"])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Required(DELIVERY_OWNERSHIP, default=delivery["ownership"]): _select(
                ("device_owned", "controlel_owned")
            ),
            vol.Required(DELIVERY_ASSIST_POLICY, default=delivery["assist_policy"]): _select(
                ("no_assist", "always_assist_while_heating")
            ),
            vol.Required(DELIVERY_ASSIST_TARGET, default=delivery["assist_target_celsius"]): _number("°C"),
        }
    )


def _safety_schema(global_config: Mapping[str, Any], protection: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(MAXIMUM_FUTURE_SKEW, default=global_config["maximum_future_skew_seconds"]): _number(
                "s", minimum=0
            ),
            vol.Required(INDETERMINATE_GRACE, default=protection["indeterminate_grace_period_seconds"]): _number(
                "s", minimum=0
            ),
            vol.Required(INDETERMINATE_ACTION, default=protection["indeterminate_timeout_action"]): _select(
                ("disable_heating", "enable_heating")
            ),
            vol.Required(MINIMUM_ON, default=protection["minimum_heating_on_seconds"]): _number("s", minimum=0),
            vol.Required(MINIMUM_OFF, default=protection["minimum_heating_off_seconds"]): _number("s", minimum=0),
        }
    )


def _diagnostics_schema(diagnostics: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(DIAGNOSTIC_PROFILE, default=diagnostics["steady_profile"]): _select(("basic", "detailed")),
            vol.Required(DEBUG_DURATION, default=diagnostics["debug_policy"]["configured_duration_seconds"]): _number(
                "s", minimum=0.001
            ),
        }
    )


def _editable_recipients(recipients: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "target": item["target"],
            "enabled": item["enabled"],
            "minimum_level": item["minimum_level"],
            "categories": item["categories"],
        }
        for item in recipients
    ]


def _notification_recipients(value: object, current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("notification recipients must be a list")
    current_by_target = {str(item["target"]): item for item in current}
    result = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("notification recipient must be an object")
        target = str(raw["target"]).strip()
        existing = current_by_target.get(target)
        result.append(
            {
                "recipient_id": existing["recipient_id"] if existing else f"recipient_{uuid4().hex}",
                "transport": "home_assistant_notify",
                "target": target,
                "enabled": raw.get("enabled", True),
                "minimum_level": raw.get("minimum_level", "operational"),
                "categories": raw.get("categories", []),
            }
        )
    return result


def _notifications_schema(notifications: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(NOTIFICATIONS_ENABLED, default=notifications["enabled"]): selector.BooleanSelector(),
            vol.Required(
                NOTIFICATION_RECIPIENTS, default=_editable_recipients(notifications["recipients"])
            ): selector.ObjectSelector(),
            vol.Required(NOTIFICATION_MAXIMUM, default=notifications["maximum_per_window"]): _number(minimum=1),
            vol.Required(NOTIFICATION_WINDOW, default=notifications["rate_window_seconds"]): _number("s", minimum=1),
            vol.Required(CRITICAL_NOTIFICATION_MAXIMUM, default=notifications["critical_maximum_per_window"]): _number(
                minimum=1
            ),
            vol.Required(CRITICAL_NOTIFICATION_WINDOW, default=notifications["critical_rate_window_seconds"]): _number(
                "s", minimum=1
            ),
            vol.Required(NOTIFICATION_HISTORY, default=notifications["history_capacity"]): _number(minimum=1),
        }
    )


def _draft_label(draft: CanonicalConfigurationDraftV3) -> str:
    saved_at = draft.updated_at.astimezone().strftime("%Y-%m-%d %H:%M")
    return f"{draft.heating.zones[0].display_name} — last saved {saved_at}"
