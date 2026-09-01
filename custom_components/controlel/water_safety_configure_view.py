"""Read-only Water Safety state projection for native Home Assistant Configure."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from controlel.application.configuration.water_safety_setup_adapter import (
    NOTIFICATION_ROLE_PREFIX,
    SHUTOFF_VALVE_ROLE_PREFIX,
    SIREN_ROLE_PREFIX,
    WATER_SAFETY_MODULE_KEY,
    WATER_SAFETY_SENSOR_ROLE,
    WaterSafetySetupPayload,
)
from controlel.application.setup import ActiveReference, CanonicalConfigurationRevision, DraftRevision
from controlel.application.setup.json_data import canonical_json
from controlel.application.setup.model import ValidationReport
from controlel.infrastructure.home_assistant import ACTIVE_REFERENCE_KEY, HomeAssistantSetupRepository

WaterSafetyLifecycle = Literal["not_configured", "draft_incomplete", "draft_ready", "configured"]
WaterSafetySection = Literal[
    "status",
    "area_sensor",
    "notifications",
    "sirens",
    "shutoff_valves",
    "sensor_fault",
    "messages",
    "validation",
]


@dataclass(frozen=True)
class WaterSafetyConfigureView:
    lifecycle: WaterSafetyLifecycle
    draft: DraftRevision | None
    active: ActiveReference | None
    active_revision: CanonicalConfigurationRevision | None
    payload: WaterSafetySetupPayload | None
    validation: ValidationReport | None


async def async_build_water_safety_configure_view(
    repository: HomeAssistantSetupRepository,
    entry_data: Mapping[str, Any],
) -> WaterSafetyConfigureView:
    drafts = await async_list_module_drafts(repository, WATER_SAFETY_MODULE_KEY)
    latest_draft = drafts[0] if drafts else None
    validation = (
        await repository.get_latest_validation_report(latest_draft.draft_id) if latest_draft is not None else None
    )
    active = _active_reference(entry_data)
    active_revision = None
    active_payload = None
    if active is not None and active.module_key == WATER_SAFETY_MODULE_KEY:
        revision = await repository.get_canonical_revision(active.canonical_revision_id)
        if isinstance(revision, CanonicalConfigurationRevision):
            active_revision = revision
            active_payload = WaterSafetySetupPayload.model_validate_json(canonical_json(revision.module_payload))
    if latest_draft is not None:
        validation_ready = validation is not None and validation.assesses(latest_draft) and validation.activation_ready
        return WaterSafetyConfigureView(
            lifecycle="draft_ready" if validation_ready else "draft_incomplete",
            draft=latest_draft,
            active=active,
            active_revision=active_revision,
            payload=_water_safety_payload_from_draft(latest_draft),
            validation=validation,
        )
    if active_revision is not None:
        return WaterSafetyConfigureView(
            lifecycle="configured",
            draft=None,
            active=active,
            active_revision=active_revision,
            payload=active_payload,
            validation=None,
        )
    return WaterSafetyConfigureView(
        lifecycle="not_configured",
        draft=None,
        active=active,
        active_revision=None,
        payload=None,
        validation=None,
    )


async def async_list_module_drafts(
    repository: HomeAssistantSetupRepository,
    module_key: str,
) -> tuple[DraftRevision, ...]:
    if hasattr(repository, "list_module_drafts"):
        return await repository.list_module_drafts(module_key)
    loader = getattr(repository, "_load", None)
    drafts_parser = getattr(type(repository), "_drafts", None)
    if loader is None or drafts_parser is None:
        return ()
    document = await loader()
    latest: dict[str, DraftRevision] = {}
    for draft in drafts_parser(document):
        if draft.module_key != module_key:
            continue
        current = latest.get(draft.draft_id)
        if current is None or draft.revision > current.revision:
            latest[draft.draft_id] = draft
    return tuple(sorted(latest.values(), key=lambda item: item.updated_at, reverse=True))


def water_safety_menu_summary(view: WaterSafetyConfigureView) -> str:
    if view.lifecycle == "draft_ready":
        active = (
            f" Active revision {view.active.canonical_revision_id} remains unchanged."
            if view.active is not None and view.active.module_key == WATER_SAFETY_MODULE_KEY
            else ""
        )
        return f"Draft ready.{active}"
    if view.lifecycle == "draft_incomplete":
        draft_id = view.draft.draft_id if view.draft is not None else "unknown"
        active = (
            f" Active revision {view.active.canonical_revision_id} remains unchanged."
            if view.active is not None and view.active.module_key == WATER_SAFETY_MODULE_KEY
            else ""
        )
        return f"Draft incomplete: Water Safety has an incomplete draft ({draft_id}).{active}"
    if view.lifecycle == "configured":
        revision_id = view.active.canonical_revision_id if view.active is not None else "unknown"
        return f"Water Safety is configured. Active revision: {revision_id}."
    return "Water Safety is not configured. Choose a section below to review current state."


def water_safety_section_detail(view: WaterSafetyConfigureView, section: WaterSafetySection) -> str:
    if section == "area_sensor":
        return _area_sensor_detail(view)
    if view.lifecycle == "not_configured":
        return _not_configured_detail(section)
    if view.lifecycle in {"draft_incomplete", "draft_ready"}:
        return _draft_detail(view, section)
    return _configured_detail(view, section)


def _active_reference(data: Mapping[str, Any]) -> ActiveReference | None:
    raw = data.get(ACTIVE_REFERENCE_KEY)
    if not isinstance(raw, Mapping):
        return None
    return ActiveReference.model_validate(raw)


def _water_safety_payload_from_draft(draft: DraftRevision) -> WaterSafetySetupPayload | None:
    try:
        return WaterSafetySetupPayload.model_validate_json(canonical_json(dict(draft.settings)))
    except ValidationError:
        return None


def _not_configured_detail(section: WaterSafetySection) -> str:
    defaults = {
        "status": "Not configured.",
        "area_sensor": "Not configured.",
        "notifications": "Not configured.",
        "sirens": "Not configured.",
        "shutoff_valves": "Not configured.",
        "sensor_fault": "Default.",
        "messages": "Default.",
        "validation": "Not configured.",
    }
    return defaults[section]


def _draft_detail(view: WaterSafetyConfigureView, section: WaterSafetySection) -> str:
    draft = view.draft
    if draft is None:
        return _not_configured_detail(section)
    if section == "status":
        activation_ready = view.validation is not None and view.validation.activation_ready
        label = "Draft ready" if activation_ready else "Draft incomplete"
        return (
            f"{label} ({draft.draft_id}, revision {draft.revision}). "
            f"Activation ready: {'yes' if activation_ready else 'no'}."
        )
    if section == "validation":
        activation_ready = view.validation is not None and view.validation.activation_ready
        issue_count = len(view.validation.issues) if view.validation is not None else 0
        return (
            f"Draft validation: {'ready for activation' if activation_ready else 'not ready'}. "
            f"Issues reported: {issue_count}. Native activation is not available yet."
        )
    payload = view.payload
    if payload is None:
        return "Draft incomplete. Section details are not available yet."
    return _payload_detail(payload, draft, view.validation, section, lifecycle="draft_incomplete")


def _configured_detail(view: WaterSafetyConfigureView, section: WaterSafetySection) -> str:
    payload = view.payload
    if payload is None or view.active is None:
        return "Configured revision details are not available."
    if section == "status":
        return f"Configured and active. Revision: {view.active.canonical_revision_id}."
    return _payload_detail(payload, view.draft, view.validation, section, lifecycle="configured")


def _payload_detail(
    payload: WaterSafetySetupPayload,
    draft: DraftRevision | None,
    validation: ValidationReport | None,
    section: WaterSafetySection,
    *,
    lifecycle: WaterSafetyLifecycle,
) -> str:
    notification_bindings = _role_binding_locators(draft, NOTIFICATION_ROLE_PREFIX) if draft is not None else ()
    siren_bindings = _role_binding_locators(draft, SIREN_ROLE_PREFIX) if draft is not None else ()
    shutoff_valve_bindings = _role_binding_locators(draft, SHUTOFF_VALVE_ROLE_PREFIX) if draft is not None else ()
    if section == "notifications":
        roles = ", ".join(payload.notification_target_roles) or "None"
        targets = ", ".join(notification_bindings) or "Not selected"
        return f"Notification roles: {roles}. Targets: {targets}."
    if section == "sirens":
        if not payload.siren_target_roles:
            return "No sirens configured."
        roles = ", ".join(payload.siren_target_roles)
        targets = ", ".join(siren_bindings) or "Not selected"
        return f"Siren roles: {roles}. Targets: {targets}."
    if section == "shutoff_valves":
        if not payload.shutoff_valve_target_roles:
            return "No automatic shutoff valves configured."
        roles = ", ".join(payload.shutoff_valve_target_roles)
        targets = ", ".join(shutoff_valve_bindings) or "Not selected"
        return f"Shutoff valve roles: {roles}. Targets: {targets}. Recovery is manual; no reopen is requested."
    if section == "sensor_fault":
        repeat = (
            "disabled"
            if payload.fault_repeat_interval_seconds is None
            else f"{payload.fault_repeat_interval_seconds:g}s"
        )
        critical = "yes" if payload.critical_sensor else "no"
        return (
            f"Unavailable grace: {payload.unavailable_grace_seconds:g}s. "
            f"Fault repeat interval: {repeat}. Critical sensor: {critical}."
        )
    if section == "messages":
        custom = sum(
            1
            for value in (
                payload.messages.wet,
                payload.messages.recovery,
                payload.messages.fault,
            )
            if value
        )
        if custom:
            return f"Custom messages configured for {custom} event type(s)."
        return "Default messages."
    if section == "validation":
        if lifecycle == "configured":
            return "Active configuration. Native validation and activation editing is not available yet."
        activation_ready = validation is not None and validation.activation_ready
        issue_count = len(validation.issues) if validation is not None else 0
        return (
            f"Draft validation: {'ready for activation' if activation_ready else 'not ready'}. "
            f"Issues reported: {issue_count}. Native activation is not available yet."
        )
    return _not_configured_detail(section)


def _area_sensor_detail(view: WaterSafetyConfigureView) -> str:
    if view.draft is not None:
        settings = view.draft.settings
        sensor = _binding_locator(view.draft, WATER_SAFETY_SENSOR_ROLE)
    elif view.active_revision is not None:
        settings = view.active_revision.module_payload
        sensor = _binding_locator_from_bindings(view.active_revision.bindings, WATER_SAFETY_SENSOR_ROLE)
    else:
        return "Not configured."
    area_id = settings.get("area_id")
    area_name = settings.get("area_name")
    area = (
        f"{area_name} ({area_id})"
        if isinstance(area_name, str) and area_name and isinstance(area_id, str) and area_id
        else str(area_id)
        if isinstance(area_id, str) and area_id
        else "Not selected"
    )
    return f"Area: {area}. Moisture sensor: {sensor or 'Not selected'}."


def _binding_locator(draft: DraftRevision, role: str) -> str | None:
    return _binding_locator_from_bindings(draft.bindings, role)


def _binding_locator_from_bindings(bindings: tuple[Any, ...], role: str) -> str | None:
    for binding in bindings:
        if binding.role != role:
            continue
        reference = binding.reference
        locator = reference.current_locator or reference.native_id
        return str(locator) if locator else None
    return None


def _role_binding_locators(draft: DraftRevision, role_prefix: str) -> tuple[str, ...]:
    locators: list[str] = []
    for binding in sorted(draft.bindings, key=lambda item: item.role):
        if not binding.role.startswith(role_prefix):
            continue
        reference = binding.reference
        locator = reference.current_locator or reference.native_id
        if locator:
            locators.append(str(locator))
    return tuple(locators)
