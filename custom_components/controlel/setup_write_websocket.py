"""Authenticated Home Assistant-local transport for Setup Write API v1."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from pydantic import ValidationError

from controlel.application.configuration.heating_setup_adapter import (
    SOURCE_DISABLE_TARGET_ROLE,
    SOURCE_ENABLE_TARGET_ROLE,
)
from controlel.application.setup import SetupConflictError, SetupNotFoundError
from controlel.infrastructure.home_assistant import (
    HeatingBindingSelectionRequest,
    HeatingSetupHostService,
    SetupStorageIntegrityError,
)

from .const import DOMAIN
from .setup_backend import (
    async_get_setup_backend,
    async_get_setup_service,
    canonical_heating_setup_defaults,
)

SETUP_WRITE_API_VERSION = 1
SETUP_WRITE_V1_DISCOVERY = f"{DOMAIN}/setup/write/v1/discovery"
SETUP_WRITE_V1_DEFAULTS = f"{DOMAIN}/setup/write/v1/defaults"
SETUP_WRITE_V1_RECOMMENDATIONS = f"{DOMAIN}/setup/write/v1/recommendations"
SETUP_WRITE_V1_START = f"{DOMAIN}/setup/write/v1/start"
SETUP_WRITE_V1_REOPEN = f"{DOMAIN}/setup/write/v1/reopen"
SETUP_WRITE_V1_UPDATE = f"{DOMAIN}/setup/write/v1/update"
SETUP_WRITE_V1_VALIDATE = f"{DOMAIN}/setup/write/v1/validate"
SETUP_WRITE_V1_CANONICALIZE = f"{DOMAIN}/setup/write/v1/canonicalize"
SETUP_WRITE_V1_ACTIVATE = f"{DOMAIN}/setup/write/v1/activate"
SETUP_WRITE_V1_DELETE = f"{DOMAIN}/setup/write/v1/delete"

ERR_SETUP_CONFLICT = "setup_conflict"
ERR_SETUP_STORAGE_INTEGRITY = "setup_storage_integrity"

_TRANSPORT_KEY = f"{DOMAIN}_setup_write_v1_transport_registered"
_NON_EMPTY_STRING = vol.All(str, vol.Length(min=1, max=256))
_OPTIONAL_STRING = vol.Any(None, _NON_EMPTY_STRING)

SetupOperation = Callable[[HeatingSetupHostService, dict[str, Any]], Awaitable[object]]


def async_register_setup_write_api_v1(hass: Any) -> None:
    """Register the process-wide Setup Write API v1 command types once."""

    if hass.data.get(_TRANSPORT_KEY):
        return
    for handler in (
        _discovery,
        _defaults,
        _recommendations,
        _start,
        _reopen,
        _update,
        _validate,
        _canonicalize,
        _activate,
        _delete,
    ):
        websocket_api.async_register_command(hass, handler)
    hass.data[_TRANSPORT_KEY] = True


def _schema(command_type: str, fields: Mapping[vol.Marker, object]) -> dict[vol.Marker, object]:
    return {
        vol.Required("type"): command_type,
        vol.Required("config_entry_id"): _NON_EMPTY_STRING,
        **fields,
    }


def _required_time(name: str) -> tuple[vol.Marker, object]:
    return vol.Required(name), _aware_datetime


def _optional_preferences() -> dict[vol.Marker, object]:
    return {
        vol.Optional("preferred_area_id", default=None): _OPTIONAL_STRING,
        vol.Optional("preferred_floor_id", default=None): _OPTIONAL_STRING,
    }


def _selection_schema() -> dict[vol.Marker, object]:
    return {
        vol.Required("role"): _NON_EMPTY_STRING,
        vol.Required("candidate_id"): vol.Match(r"^[0-9a-f]{64}$"),
        vol.Optional("user_confirmed", default=False): bool,
    }


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise vol.Invalid("expected an ISO 8601 timestamp string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise vol.Invalid("expected an ISO 8601 timestamp string") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise vol.Invalid("timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def _positive_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise vol.Invalid("expected a positive integer")
    return value


def _non_negative_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise vol.Invalid("expected a non-negative integer")
    return value


async def _service_for_entry(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> HeatingSetupHostService | None:
    entry = hass.config_entries.async_get_entry(msg["config_entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_NOT_FOUND,
            "Controlel setup config entry was not found",
        )
        return None
    return await async_get_setup_service(hass, entry)


async def _send(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    operation_name: str,
    operation: SetupOperation,
) -> None:
    service = await _service_for_entry(hass, connection, msg)
    if service is None:
        return
    try:
        result = await operation(service, msg)
    except SetupNotFoundError:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Controlel setup draft was not found")
        return
    except SetupConflictError:
        connection.send_error(msg["id"], ERR_SETUP_CONFLICT, "Controlel setup request conflicts with current state")
        return
    except SetupStorageIntegrityError:
        connection.send_error(
            msg["id"],
            ERR_SETUP_STORAGE_INTEGRITY,
            "Controlel setup storage failed integrity validation",
        )
        return
    except (TypeError, ValueError, ValidationError):
        connection.send_error(
            msg["id"],
            websocket_api.ERR_INVALID_FORMAT,
            "Controlel setup request is invalid",
        )
        return
    connection.send_result(
        msg["id"],
        {
            "setup_write_api_version": SETUP_WRITE_API_VERSION,
            "operation": operation_name,
            "result": _json_result(result),
        },
    )


def _json_result(result: object) -> object:
    if isinstance(result, tuple):
        return [_json_result(item) for item in result]
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return result


async def _get_discovery(service: HeatingSetupHostService, msg: dict[str, Any]) -> object:
    return await service.get_discovery_snapshot(
        snapshot_id=msg["snapshot_id"],
        captured_at=msg["captured_at"],
    )


async def _get_defaults(_service: HeatingSetupHostService, _msg: dict[str, Any]) -> object:
    return {
        "settings": canonical_heating_setup_defaults(),
        "simple_switch": {
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
        },
    }


async def _get_recommendations(service: HeatingSetupHostService, msg: dict[str, Any]) -> object:
    return await service.get_recommendations(
        snapshot_id=msg["snapshot_id"],
        captured_at=msg["captured_at"],
        preferred_area_id=msg["preferred_area_id"],
        preferred_floor_id=msg["preferred_floor_id"],
    )


def _selections(msg: dict[str, Any]) -> tuple[HeatingBindingSelectionRequest, ...]:
    return tuple(HeatingBindingSelectionRequest.model_validate(item) for item in msg["selections"])


async def _start_draft(service: HeatingSetupHostService, msg: dict[str, Any]) -> object:
    return await service.start_new_heating_setup(
        draft_id=msg["draft_id"],
        module_instance_id=msg["module_instance_id"],
        created_at=msg["created_at"],
        snapshot_id=msg["snapshot_id"],
        report_id=msg["report_id"],
        settings=msg["settings"],
        selections=_selections(msg),
        preferred_area_id=msg["preferred_area_id"],
        preferred_floor_id=msg["preferred_floor_id"],
        base_active_revision_id=msg["base_active_revision_id"],
    )


async def _reopen_draft(service: HeatingSetupHostService, msg: dict[str, Any]) -> object:
    return await service.reopen_heating_setup(
        msg["draft_id"],
        snapshot_id=msg["snapshot_id"],
        captured_at=msg["captured_at"],
        preferred_area_id=msg["preferred_area_id"],
        preferred_floor_id=msg["preferred_floor_id"],
    )


async def _update_draft(service: HeatingSetupHostService, msg: dict[str, Any]) -> object:
    return await service.update_heating_draft(
        msg["draft_id"],
        expected_revision=msg["expected_revision"],
        updated_at=msg["updated_at"],
        snapshot_id=msg["snapshot_id"],
        report_id=msg["report_id"],
        settings=msg["settings"],
        selections=_selections(msg),
        preferred_area_id=msg["preferred_area_id"],
        preferred_floor_id=msg["preferred_floor_id"],
    )


async def _validate_draft(service: HeatingSetupHostService, msg: dict[str, Any]) -> object:
    return await service.validate_heating_draft(
        msg["draft_id"],
        snapshot_id=msg["snapshot_id"],
        evaluated_at=msg["evaluated_at"],
        report_id=msg["report_id"],
        preferred_area_id=msg["preferred_area_id"],
        preferred_floor_id=msg["preferred_floor_id"],
    )


async def _canonicalize_draft(service: HeatingSetupHostService, msg: dict[str, Any]) -> object:
    return await service.canonicalize_heating_draft(
        msg["draft_id"],
        snapshot_id=msg["snapshot_id"],
        created_at=msg["created_at"],
        validation_report_id=msg["validation_report_id"],
        configuration_id=msg["configuration_id"],
        revision_id=msg["revision_id"],
        revision=msg["revision"],
        actor=msg["actor"],
        source=msg["source"],
        change_kind=msg["change_kind"],
        reason=msg["reason"],
        core_version=msg["core_version"],
        integration_version=msg["integration_version"],
        parent_revision_id=msg["parent_revision_id"],
        preferred_area_id=msg["preferred_area_id"],
        preferred_floor_id=msg["preferred_floor_id"],
    )


@websocket_api.websocket_command(
    _schema(
        SETUP_WRITE_V1_DISCOVERY,
        dict(
            (
                (vol.Required("snapshot_id"), _NON_EMPTY_STRING),
                _required_time("captured_at"),
            )
        ),
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _discovery(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send(hass, connection, msg, "discovery", _get_discovery)


@websocket_api.websocket_command(_schema(SETUP_WRITE_V1_DEFAULTS, {}))
@websocket_api.require_admin
@websocket_api.async_response
async def _defaults(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send(hass, connection, msg, "defaults", _get_defaults)


@websocket_api.websocket_command(
    _schema(
        SETUP_WRITE_V1_RECOMMENDATIONS,
        {
            vol.Required("snapshot_id"): _NON_EMPTY_STRING,
            **dict((_required_time("captured_at"),)),
            **_optional_preferences(),
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _recommendations(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send(hass, connection, msg, "recommendations", _get_recommendations)


@websocket_api.websocket_command(
    _schema(
        SETUP_WRITE_V1_START,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("module_instance_id"): _NON_EMPTY_STRING,
            **dict((_required_time("created_at"),)),
            vol.Required("snapshot_id"): _NON_EMPTY_STRING,
            vol.Required("report_id"): _NON_EMPTY_STRING,
            vol.Optional("settings", default=dict): dict,
            vol.Optional("selections", default=list): [_selection_schema()],
            **_optional_preferences(),
            vol.Optional("base_active_revision_id", default=None): _OPTIONAL_STRING,
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _start(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send(hass, connection, msg, "start", _start_draft)


@websocket_api.websocket_command(
    _schema(
        SETUP_WRITE_V1_REOPEN,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("snapshot_id"): _NON_EMPTY_STRING,
            **dict((_required_time("captured_at"),)),
            **_optional_preferences(),
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _reopen(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send(hass, connection, msg, "reopen", _reopen_draft)


@websocket_api.websocket_command(
    _schema(
        SETUP_WRITE_V1_UPDATE,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("expected_revision"): _positive_integer,
            **dict((_required_time("updated_at"),)),
            vol.Required("snapshot_id"): _NON_EMPTY_STRING,
            vol.Required("report_id"): _NON_EMPTY_STRING,
            vol.Required("settings"): dict,
            vol.Required("selections"): [_selection_schema()],
            **_optional_preferences(),
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _update(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send(hass, connection, msg, "update", _update_draft)


@websocket_api.websocket_command(
    _schema(
        SETUP_WRITE_V1_VALIDATE,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("snapshot_id"): _NON_EMPTY_STRING,
            **dict((_required_time("evaluated_at"),)),
            vol.Required("report_id"): _NON_EMPTY_STRING,
            **_optional_preferences(),
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _validate(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send(hass, connection, msg, "validate", _validate_draft)


@websocket_api.websocket_command(
    _schema(
        SETUP_WRITE_V1_CANONICALIZE,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("snapshot_id"): _NON_EMPTY_STRING,
            **dict((_required_time("created_at"),)),
            vol.Required("validation_report_id"): _NON_EMPTY_STRING,
            vol.Required("configuration_id"): _NON_EMPTY_STRING,
            vol.Required("revision_id"): _NON_EMPTY_STRING,
            vol.Required("revision"): _positive_integer,
            vol.Required("actor"): _NON_EMPTY_STRING,
            vol.Required("source"): _NON_EMPTY_STRING,
            vol.Required("change_kind"): _NON_EMPTY_STRING,
            vol.Required("reason"): _NON_EMPTY_STRING,
            vol.Required("core_version"): _NON_EMPTY_STRING,
            vol.Optional("integration_version", default=None): _OPTIONAL_STRING,
            vol.Optional("parent_revision_id", default=None): _OPTIONAL_STRING,
            **_optional_preferences(),
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _canonicalize(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _send(hass, connection, msg, "canonicalize", _canonicalize_draft)


@websocket_api.websocket_command(
    _schema(
        SETUP_WRITE_V1_ACTIVATE,
        {
            vol.Required("revision_id"): _NON_EMPTY_STRING,
            vol.Required("semantic_configuration_fingerprint"): vol.Match(r"^[0-9a-f]{64}$"),
            vol.Optional("expected_active_revision_id", default=None): _OPTIONAL_STRING,
            vol.Required("expected_active_generation"): _non_negative_integer,
            vol.Required("attempt_id"): _NON_EMPTY_STRING,
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _activate(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Activate one inactive canonical revision within the addressed config entry."""

    entry = hass.config_entries.async_get_entry(msg["config_entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_NOT_FOUND,
            "Controlel setup config entry was not found",
        )
        return
    try:
        from .activation_backend import async_activate_canonical_revision

        result = await async_activate_canonical_revision(
            hass,
            entry,
            revision_id=msg["revision_id"],
            semantic_configuration_fingerprint=msg["semantic_configuration_fingerprint"],
            expected_active_revision_id=msg["expected_active_revision_id"],
            expected_active_generation=msg["expected_active_generation"],
            attempt_id=msg["attempt_id"],
        )
    except SetupNotFoundError:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Canonical revision was not found")
        return
    except SetupConflictError:
        connection.send_error(msg["id"], ERR_SETUP_CONFLICT, "Canonical activation conflicts with current state")
        return
    except SetupStorageIntegrityError:
        connection.send_error(
            msg["id"],
            ERR_SETUP_STORAGE_INTEGRITY,
            "Controlel setup storage failed integrity validation",
        )
        return
    except (TypeError, ValueError, ValidationError):
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, "Canonical activation request is invalid")
        return
    connection.send_result(
        msg["id"],
        {
            "setup_write_api_version": SETUP_WRITE_API_VERSION,
            "operation": "activate",
            "result": _json_result(result),
        },
    )


@websocket_api.websocket_command(
    _schema(
        SETUP_WRITE_V1_DELETE,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("expected_revision"): _positive_integer,
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _delete(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Delete one persisted draft after explicit wizard confirmation."""

    entry = hass.config_entries.async_get_entry(msg["config_entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_NOT_FOUND,
            "Controlel setup config entry was not found",
        )
        return
    try:
        backend = await async_get_setup_backend(hass, entry)
        await backend.repository.delete_draft(
            msg["draft_id"],
            expected_revision=msg["expected_revision"],
        )
    except SetupNotFoundError:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Controlel setup draft was not found")
        return
    except SetupConflictError:
        connection.send_error(msg["id"], ERR_SETUP_CONFLICT, "Controlel setup request conflicts with current state")
        return
    except SetupStorageIntegrityError:
        connection.send_error(
            msg["id"],
            ERR_SETUP_STORAGE_INTEGRITY,
            "Controlel setup storage failed integrity validation",
        )
        return
    connection.send_result(
        msg["id"],
        {
            "setup_write_api_version": SETUP_WRITE_API_VERSION,
            "operation": "delete",
            "result": {
                "draft_id": msg["draft_id"],
                "deleted_revision": msg["expected_revision"],
            },
        },
    )
