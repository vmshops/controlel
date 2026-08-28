"""Native Home Assistant projection of canonical configuration v3."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from importlib import metadata
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, FlowType, OptionsFlow
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
from controlel.application.setup import ActiveReference, SetupConflictError, SetupNotFoundError
from controlel.infrastructure.home_assistant import (
    ACTIVE_REFERENCE_KEY,
    HomeAssistantDiscoveryAdapter,
)
from controlel.infrastructure.home_assistant.setup_discovery import HA_AREA_KIND, HA_FLOOR_KIND

from .activation_backend import async_activate_canonical_revision
from .const import CONFIG_ENTRY_VERSION, DOMAIN, INTEGRATION_VERSION
from .setup_backend import async_get_setup_backend

WIZARD_URL = f"/{DOMAIN}"
TOP_EXPLANATION = (
    "You can configure Controlel here manually or use the simpler guided Setup Wizard in the Controlel panel. "
    "Both edit the same configuration."
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
                title="Controlel heating",
                data={},
                options={},
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={"configure_explanation": TOP_EXPLANATION},
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

    async def _service(self) -> Any:
        return (await async_get_setup_backend(self.hass, self.config_entry)).configuration_v3

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        del user_input
        drafts = await (await self._service()).list_drafts()
        authority = await self._authority_kind()
        if authority == "mixed":
            return self.async_abort(reason="canonical_legacy_mixed")
        menu = ["open_wizard"]
        menu.append(
            {"v3": "edit_active", "v2": "convert_v2", "legacy": "convert_legacy"}.get(authority, "start_greenfield")
        )
        if drafts:
            menu.extend(("resume_draft", "abandon_draft"))
        return self.async_show_menu(
            step_id="init",
            menu_options=menu,
            description_placeholders={"configure_explanation": TOP_EXPLANATION},
        )

    async def _authority_kind(self) -> str:
        raw = self.config_entry.data.get(ACTIVE_REFERENCE_KEY)
        legacy = bool(set(self.config_entry.data) - {ACTIVE_REFERENCE_KEY} or self.config_entry.options)
        if raw is None:
            return "legacy" if legacy else "empty"
        if legacy or set(self.config_entry.data) != {ACTIVE_REFERENCE_KEY}:
            return "mixed"
        active = ActiveReference.model_validate(raw)
        backend = await async_get_setup_backend(self.hass, self.config_entry)
        revision = await backend.repository.get_canonical_revision(active.canonical_revision_id)
        return "v3" if isinstance(revision, CanonicalConfigurationRevisionV3) else "v2"

    async def async_step_open_wizard(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        del user_input
        return self.async_external_step(step_id="open_wizard", url=WIZARD_URL)

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
                return await self.async_step_zone()
            except (KeyError, SetupConflictError, SetupNotFoundError, TypeError, ValueError, ValidationError):
                errors["base"] = "invalid_configuration"
        return self.async_show_form(
            step_id="start_greenfield", data_schema=_greenfield_schema(user_input or {}), errors=errors
        )

    async def async_step_edit_active(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        del user_input
        active = ActiveReference.model_validate(self.config_entry.data[ACTIVE_REFERENCE_KEY])
        self._draft = await (await self._service()).edit_from_active(
            draft_id=_id("ha-edit-draft"), created_at=_now(), expected_active_generation=active.generation
        )
        self._load_document()
        return await self.async_step_zone()

    async def async_step_convert_v2(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="convert_v2", data_schema=vol.Schema({}))
        active = ActiveReference.model_validate(self.config_entry.data[ACTIVE_REFERENCE_KEY])
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
        review = await (await self._service()).convert_legacy(
            draft_id=_id("ha-legacy-conversion-draft"),
            v2_revision_id=_id("ha-legacy-v2-projection"),
            projection_revision_id=_id("ha-legacy-v3-projection"),
            created_at=now,
            snapshot_id=_id("ha-legacy-conversion-snapshot"),
            core_version=metadata.version("controlel"),
            integration_version=INTEGRATION_VERSION,
        )
        return await self._load_review(review)

    async def _load_review(self, review: Any) -> ConfigFlowResult:
        if review.draft is None:
            return self.async_abort(reason="conversion_not_ready")
        self._draft = review.draft
        self._load_document()
        return await self.async_step_zone()

    async def async_step_resume_draft(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        service = await self._service()
        drafts = await service.list_drafts()
        if user_input is not None:
            self._draft = await service.reopen_draft(str(user_input["draft_id"]))
            self._load_document()
            return await self.async_step_zone()
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
                return await self.async_step_sensor()
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
                return await self.async_step_heat_source()
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
                return await self.async_step_heat_delivery()
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
                return await self.async_step_safety_timing()
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
                return await self.async_step_diagnostics()
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
        if user_input is not None:
            try:
                diagnostics["steady_profile"] = user_input[DIAGNOSTIC_PROFILE]
                diagnostics["debug_policy"]["configured_duration_seconds"] = user_input[DEBUG_DURATION]
                ConfigurationScopesV3.model_validate(document)
                return await self.async_step_notifications()
            except (KeyError, TypeError, ValueError, ValidationError):
                return self.async_show_form(
                    step_id="diagnostics",
                    data_schema=_diagnostics_schema(diagnostics),
                    errors={"base": "invalid_configuration"},
                )
        return self.async_show_form(step_id="diagnostics", data_schema=_diagnostics_schema(diagnostics))

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
                return await self.async_step_save_draft()
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
        return await self.async_step_zone()

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
            core_version=metadata.version("controlel"),
            integration_version=INTEGRATION_VERSION,
        )
        return await self.async_step_activate()

    async def async_step_activate(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._candidate is None:
            raise SetupConflictError("canonical v3 flow has no canonical candidate")
        if user_input is None:
            return self.async_show_form(
                step_id="activate",
                data_schema=vol.Schema({}),
                description_placeholders={"revision_id": self._candidate.revision_id},
            )
        draft = self._require_draft()
        await async_activate_canonical_revision(
            self.hass,
            self.config_entry,
            revision_id=self._candidate.revision_id,
            semantic_configuration_fingerprint=self._candidate.semantic_configuration_fingerprint,
            expected_active_revision_id=draft.base_active_revision_id,
            expected_active_generation=draft.base_active_generation,
            attempt_id=_id("ha-activation"),
        )
        return self.async_create_entry(title="", data={})


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
    return vol.Optional(name, default=value) if value else vol.Optional(name)


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
    return f"{draft.heating.zones[0].display_name} — revision {draft.revision} — {draft.updated_at.isoformat()}"
