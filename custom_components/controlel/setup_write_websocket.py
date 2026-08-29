"""Authenticated Home Assistant-local transport for Setup Write API v1."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from importlib import metadata
from typing import Any, Protocol

import voluptuous as vol
from homeassistant.components import websocket_api
from pydantic import ValidationError

from controlel.application.configuration import CanonicalDraftRevisionConflict
from controlel.application.configuration.heating_setup_adapter import (
    SOURCE_DISABLE_TARGET_ROLE,
    SOURCE_ENABLE_TARGET_ROLE,
)
from controlel.application.setup import SetupConflictError, SetupNotFoundError
from controlel.infrastructure.home_assistant import (
    HeatingBindingSelectionRequest,
    SetupStorageIntegrityError,
)

from .const import DOMAIN, INTEGRATION_VERSION
from .core_capabilities import water_safety_core_available
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

CANONICAL_CONFIGURATION_API_VERSION = 3
CONFIGURATION_V3_START = f"{DOMAIN}/configuration/v3/start"
CONFIGURATION_V3_CONVERT_V2 = f"{DOMAIN}/configuration/v3/convert-v2"
CONFIGURATION_V3_CONVERT_LEGACY = f"{DOMAIN}/configuration/v3/convert-legacy"
CONFIGURATION_V3_ACTIVE = f"{DOMAIN}/configuration/v3/active"
CONFIGURATION_V3_EDIT = f"{DOMAIN}/configuration/v3/edit"
CONFIGURATION_V3_DRAFT = f"{DOMAIN}/configuration/v3/draft"
CONFIGURATION_V3_DRAFTS = f"{DOMAIN}/configuration/v3/drafts"
CONFIGURATION_V3_ABANDON = f"{DOMAIN}/configuration/v3/abandon"
CONFIGURATION_V3_UPDATE = f"{DOMAIN}/configuration/v3/update"
CONFIGURATION_V3_VALIDATE = f"{DOMAIN}/configuration/v3/validate"
CONFIGURATION_V3_CANONICALIZE = f"{DOMAIN}/configuration/v3/canonicalize"
CONFIGURATION_V3_ACTIVATE = f"{DOMAIN}/configuration/v3/activate"

ERR_SETUP_CONFLICT = "setup_conflict"
ERR_SETUP_STORAGE_INTEGRITY = "setup_storage_integrity"
ERR_CANONICAL_V3_REQUIRED = "canonical_v3_required"
ERR_CANONICAL_V3_DRAFT_STALE = "canonical_v3_draft_stale"

_TRANSPORT_KEY = f"{DOMAIN}_setup_write_v1_transport_registered"
_NON_EMPTY_STRING = vol.All(str, vol.Length(min=1, max=256))
_OPTIONAL_STRING = vol.Any(None, _NON_EMPTY_STRING)
_HEATING_MODULE_KEY = "heating"
_WATER_SAFETY_MODULE_KEY = "water_safety"


def _water_safety_module_key() -> str:
    return _WATER_SAFETY_MODULE_KEY


class SetupHostService(Protocol):
    async def get_discovery_snapshot(self, *, snapshot_id: str, captured_at: datetime) -> object: ...

    async def get_recommendations(
        self,
        *,
        snapshot_id: str,
        captured_at: datetime,
        preferred_area_id: str | None = None,
        preferred_floor_id: str | None = None,
        notification_roles: tuple[str, ...] | None = None,
        siren_roles: tuple[str, ...] | None = None,
    ) -> object: ...


SetupOperation = Callable[[SetupHostService, dict[str, Any]], Awaitable[object]]


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
        _configuration_v3_start,
        _configuration_v3_convert_v2,
        _configuration_v3_convert_legacy,
        _configuration_v3_active,
        _configuration_v3_edit,
        _configuration_v3_draft,
        _configuration_v3_drafts,
        _configuration_v3_abandon,
        _configuration_v3_update,
        _configuration_v3_validate,
        _configuration_v3_canonicalize,
        _configuration_v3_activate,
    ):
        websocket_api.async_register_command(hass, handler)
    hass.data[_TRANSPORT_KEY] = True


def _schema(command_type: str, fields: Mapping[vol.Marker, object]) -> dict[vol.Marker, object]:
    return {
        vol.Required("type"): command_type,
        vol.Required("config_entry_id"): _NON_EMPTY_STRING,
        vol.Optional("module_key", default=_HEATING_MODULE_KEY): _NON_EMPTY_STRING,
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


def _module_key(msg: dict[str, Any]) -> str:
    return msg.get("module_key", _HEATING_MODULE_KEY)


async def _service_for_entry(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> SetupHostService | None:
    entry = hass.config_entries.async_get_entry(msg["config_entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_NOT_FOUND,
            "Controlel setup config entry was not found",
        )
        return None
    try:
        return await async_get_setup_service(hass, entry, module_key=_module_key(msg))
    except ValueError:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_INVALID_FORMAT,
            "Controlel setup module_key is not supported",
        )
        return None


async def _backend_for_entry(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> object | None:
    entry = hass.config_entries.async_get_entry(msg["config_entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_NOT_FOUND,
            "Controlel configuration config entry was not found",
        )
        return None
    return await async_get_setup_backend(hass, entry)


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


async def _send_configuration_v3(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    operation_name: str,
    operation: Callable[[Any, dict[str, Any]], Awaitable[object]],
) -> None:
    backend = await _backend_for_entry(hass, connection, msg)
    if backend is None:
        return
    try:
        result = await operation(getattr(backend, "configuration_v3"), msg)
    except SetupNotFoundError:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Canonical v3 resource was not found")
        return
    except CanonicalDraftRevisionConflict:
        connection.send_error(
            msg["id"],
            ERR_CANONICAL_V3_DRAFT_STALE,
            "Canonical v3 draft changed before the requested operation",
        )
        return
    except SetupConflictError:
        connection.send_error(
            msg["id"],
            ERR_SETUP_CONFLICT,
            "Canonical v3 request conflicts with current authority",
        )
        return
    except SetupStorageIntegrityError:
        connection.send_error(
            msg["id"],
            ERR_SETUP_STORAGE_INTEGRITY,
            "Controlel setup storage failed integrity validation",
        )
        return
    except (TypeError, ValueError, ValidationError):
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, "Canonical v3 request is invalid")
        return
    connection.send_result(
        msg["id"],
        {
            "canonical_configuration_api_version": CANONICAL_CONFIGURATION_API_VERSION,
            "operation": operation_name,
            "result": _json_result(result),
        },
    )


async def _read_configuration_v3(service: Any, msg: dict[str, Any]) -> object:
    return await service.read_active(snapshot_id=msg["snapshot_id"], captured_at=msg["captured_at"])


async def _start_configuration_v3(service: Any, msg: dict[str, Any]) -> object:
    return await service.start_greenfield(
        draft_id=msg["draft_id"],
        created_at=msg["created_at"],
        snapshot_id=msg["snapshot_id"],
        bindings=msg["bindings"],
    )


async def _convert_v2_configuration_v3(service: Any, msg: dict[str, Any]) -> object:
    return await service.convert_v2(
        source_revision_id=msg["source_revision_id"],
        draft_id=msg["draft_id"],
        projection_revision_id=msg["projection_revision_id"],
        created_at=msg["created_at"],
        snapshot_id=msg["snapshot_id"],
        expected_active_revision_id=msg["expected_active_revision_id"],
        expected_active_generation=msg["expected_active_generation"],
        binding_overrides=msg["binding_overrides"],
    )


async def _convert_legacy_configuration_v3(service: Any, msg: dict[str, Any]) -> object:
    return await service.convert_legacy(
        draft_id=msg["draft_id"],
        v2_revision_id=msg["v2_revision_id"],
        projection_revision_id=msg["projection_revision_id"],
        created_at=msg["created_at"],
        snapshot_id=msg["snapshot_id"],
        core_version=msg["core_version"],
        integration_version=msg["integration_version"],
        binding_overrides=msg["binding_overrides"],
    )


async def _edit_configuration_v3(service: Any, msg: dict[str, Any]) -> object:
    return await service.edit_from_active(
        draft_id=msg["draft_id"],
        created_at=msg["created_at"],
        expected_active_generation=msg["expected_active_generation"],
    )


async def _reopen_configuration_v3(service: Any, msg: dict[str, Any]) -> object:
    return await service.reopen_draft(msg["draft_id"])


async def _list_configuration_v3_drafts(service: Any, _msg: dict[str, Any]) -> object:
    return await service.list_drafts()


async def _abandon_configuration_v3(service: Any, msg: dict[str, Any]) -> object:
    await service.abandon_draft(
        msg["draft_id"],
        expected_revision=msg["expected_revision"],
    )
    return {
        "draft_id": msg["draft_id"],
        "abandoned_revision": msg["expected_revision"],
    }


async def _update_configuration_v3(service: Any, msg: dict[str, Any]) -> object:
    return await service.update_draft(
        msg["draft_id"],
        expected_revision=msg["expected_revision"],
        updated_at=msg["updated_at"],
        configuration_scopes=msg["configuration_scopes"],
    )


async def _validate_configuration_v3(service: Any, msg: dict[str, Any]) -> object:
    return await service.validate_draft(
        msg["draft_id"],
        report_id=msg["report_id"],
        snapshot_id=msg["snapshot_id"],
        evaluated_at=msg["evaluated_at"],
    )


async def _canonicalize_configuration_v3(service: Any, msg: dict[str, Any]) -> object:
    return await service.canonicalize_draft(
        msg["draft_id"],
        validation_report_id=msg["validation_report_id"],
        revision_id=msg["revision_id"],
        snapshot_id=msg["snapshot_id"],
        created_at=msg["created_at"],
        actor=msg["actor"],
        source=msg["source"],
        change_kind=msg["change_kind"],
        reason=msg["reason"],
        core_version=msg["core_version"],
        integration_version=msg["integration_version"],
    )


async def _get_discovery(service: SetupHostService, msg: dict[str, Any]) -> object:
    return await service.get_discovery_snapshot(
        snapshot_id=msg["snapshot_id"],
        captured_at=msg["captured_at"],
    )


async def _get_defaults(_service: SetupHostService, _msg: dict[str, Any]) -> object:
    return {
        "core_version": metadata.version("controlel"),
        "integration_version": INTEGRATION_VERSION,
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


async def _get_recommendations(service: SetupHostService, msg: dict[str, Any]) -> object:
    kwargs: dict[str, object] = {
        "snapshot_id": msg["snapshot_id"],
        "captured_at": msg["captured_at"],
        "preferred_area_id": msg["preferred_area_id"],
        "preferred_floor_id": msg["preferred_floor_id"],
    }
    if _module_key(msg) == _water_safety_module_key():
        kwargs["notification_roles"] = tuple(msg.get("notification_roles") or ())
        kwargs["siren_roles"] = tuple(msg.get("siren_roles") or ())
    return await service.get_recommendations(**kwargs)


def _heating_selections(msg: dict[str, Any]) -> tuple[HeatingBindingSelectionRequest, ...]:
    return tuple(HeatingBindingSelectionRequest.model_validate(item) for item in msg["selections"])


def _water_selections(msg: dict[str, Any]) -> tuple[object, ...]:
    from controlel.infrastructure.home_assistant import WaterSafetyBindingSelectionRequest

    return tuple(WaterSafetyBindingSelectionRequest.model_validate(item) for item in msg["selections"])


async def _start_draft(service: SetupHostService, msg: dict[str, Any]) -> object:
    if _module_key(msg) == _water_safety_module_key():
        return await service.start_new_water_safety_setup(
            draft_id=msg["draft_id"],
            module_instance_id=msg["module_instance_id"],
            created_at=msg["created_at"],
            snapshot_id=msg["snapshot_id"],
            report_id=msg["report_id"],
            settings=msg["settings"],
            selections=_water_selections(msg),
            preferred_area_id=msg["preferred_area_id"],
            preferred_floor_id=msg["preferred_floor_id"],
            base_active_revision_id=msg["base_active_revision_id"],
        )
    return await service.start_new_heating_setup(
        draft_id=msg["draft_id"],
        module_instance_id=msg["module_instance_id"],
        created_at=msg["created_at"],
        snapshot_id=msg["snapshot_id"],
        report_id=msg["report_id"],
        settings=msg["settings"],
        selections=_heating_selections(msg),
        preferred_area_id=msg["preferred_area_id"],
        preferred_floor_id=msg["preferred_floor_id"],
        base_active_revision_id=msg["base_active_revision_id"],
    )


async def _reopen_draft(service: SetupHostService, msg: dict[str, Any]) -> object:
    if _module_key(msg) == _water_safety_module_key():
        return await service.reopen_water_safety_setup(
            msg["draft_id"],
            snapshot_id=msg["snapshot_id"],
            captured_at=msg["captured_at"],
            preferred_area_id=msg["preferred_area_id"],
            preferred_floor_id=msg["preferred_floor_id"],
        )
    return await service.reopen_heating_setup(
        msg["draft_id"],
        snapshot_id=msg["snapshot_id"],
        captured_at=msg["captured_at"],
        preferred_area_id=msg["preferred_area_id"],
        preferred_floor_id=msg["preferred_floor_id"],
    )


async def _update_draft(service: SetupHostService, msg: dict[str, Any]) -> object:
    if _module_key(msg) == _water_safety_module_key():
        return await service.update_water_draft(
            msg["draft_id"],
            expected_revision=msg["expected_revision"],
            updated_at=msg["updated_at"],
            snapshot_id=msg["snapshot_id"],
            report_id=msg["report_id"],
            settings=msg["settings"],
            selections=_water_selections(msg),
            preferred_area_id=msg["preferred_area_id"],
            preferred_floor_id=msg["preferred_floor_id"],
        )
    return await service.update_heating_draft(
        msg["draft_id"],
        expected_revision=msg["expected_revision"],
        updated_at=msg["updated_at"],
        snapshot_id=msg["snapshot_id"],
        report_id=msg["report_id"],
        settings=msg["settings"],
        selections=_heating_selections(msg),
        preferred_area_id=msg["preferred_area_id"],
        preferred_floor_id=msg["preferred_floor_id"],
    )


async def _validate_draft(service: SetupHostService, msg: dict[str, Any]) -> object:
    if _module_key(msg) == _water_safety_module_key():
        return await service.validate_water_draft(
            msg["draft_id"],
            snapshot_id=msg["snapshot_id"],
            evaluated_at=msg["evaluated_at"],
            report_id=msg["report_id"],
            preferred_area_id=msg["preferred_area_id"],
            preferred_floor_id=msg["preferred_floor_id"],
        )
    return await service.validate_heating_draft(
        msg["draft_id"],
        snapshot_id=msg["snapshot_id"],
        evaluated_at=msg["evaluated_at"],
        report_id=msg["report_id"],
        preferred_area_id=msg["preferred_area_id"],
        preferred_floor_id=msg["preferred_floor_id"],
    )


async def _canonicalize_draft(service: SetupHostService, msg: dict[str, Any]) -> object:
    common = {
        "snapshot_id": msg["snapshot_id"],
        "created_at": msg["created_at"],
        "validation_report_id": msg["validation_report_id"],
        "configuration_id": msg["configuration_id"],
        "revision_id": msg["revision_id"],
        "revision": msg["revision"],
        "actor": msg["actor"],
        "source": msg["source"],
        "change_kind": msg["change_kind"],
        "reason": msg["reason"],
        "core_version": msg["core_version"],
        "integration_version": msg["integration_version"],
        "parent_revision_id": msg["parent_revision_id"],
        "preferred_area_id": msg["preferred_area_id"],
        "preferred_floor_id": msg["preferred_floor_id"],
    }
    if _module_key(msg) == _water_safety_module_key():
        return await service.canonicalize_water_draft(msg["draft_id"], **common)
    return await service.canonicalize_heating_draft(msg["draft_id"], **common)


async def _activate_water_setup(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    if _module_key(msg) != _water_safety_module_key():
        _reject_v2_write(connection, msg, "activate")
        return
    if not water_safety_core_available():
        connection.send_error(
            msg["id"],
            websocket_api.ERR_HOME_ASSISTANT_ERROR,
            "Water Safety requires candidate Controlel core",
        )
        return
    entry = hass.config_entries.async_get_entry(msg["config_entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_NOT_FOUND,
            "Controlel setup config entry was not found",
        )
        return
    try:
        service = await async_get_setup_service(hass, entry, module_key=_water_safety_module_key())
    except ValueError:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_INVALID_FORMAT,
            "Controlel setup module_key is not supported",
        )
        return

    runtime_data = getattr(entry, "runtime_data", None)
    existing_host = getattr(runtime_data, "water_safety_host", None) if runtime_data is not None else None
    if existing_host is not None:
        await existing_host.async_stop()

    from .frontend_api import create_frontend_api_provider_v1
    from .frontend_api_websocket import register_frontend_api_provider_v1, register_water_safety_action_handler_v1
    from .water_safety_activation import WaterSafetyActivationService

    try:
        water_host = await WaterSafetyActivationService().activate_canonical_revision(
            hass,
            entry,
            msg["canonical_revision_id"],
            attempt_id=msg.get("attempt_id"),
        )
    except SetupNotFoundError:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Controlel setup draft was not found")
        return
    except SetupConflictError:
        connection.send_error(msg["id"], ERR_SETUP_CONFLICT, "Controlel setup request conflicts with current state")
        return
    except (TypeError, ValueError, ValidationError):
        connection.send_error(
            msg["id"],
            websocket_api.ERR_INVALID_FORMAT,
            "Controlel setup request is invalid",
        )
        return

    if runtime_data is not None:
        runtime_data.water_safety_host = water_host
        heating_host = runtime_data.host
        if heating_host is not None:
            if runtime_data.frontend_api_unregister is not None:
                runtime_data.frontend_api_unregister()
            runtime_data.frontend_api_unregister = register_frontend_api_provider_v1(
                hass,
                entry.entry_id,
                create_frontend_api_provider_v1(heating_host, water_safety_host=water_host),
            )

            async def _water_safety_action(action: str) -> dict[str, object]:
                return await water_host.async_frontend_api_water_safety_action(action)

            if runtime_data.water_safety_action_unregister is not None:
                runtime_data.water_safety_action_unregister()
            runtime_data.water_safety_action_unregister = register_water_safety_action_handler_v1(
                hass,
                entry.entry_id,
                _water_safety_action,
            )

    try:
        result = await service.validate_water_draft(
            msg["draft_id"],
            snapshot_id=msg["snapshot_id"],
            evaluated_at=msg["captured_at"],
            report_id=msg["report_id"],
            notification_roles=tuple(msg.get("notification_roles") or ()),
            siren_roles=tuple(msg.get("siren_roles") or ()),
            preferred_area_id=msg.get("preferred_area_id"),
            preferred_floor_id=msg.get("preferred_floor_id"),
        )
    except SetupNotFoundError:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Controlel setup draft was not found")
        return
    except SetupConflictError:
        connection.send_error(msg["id"], ERR_SETUP_CONFLICT, "Controlel setup request conflicts with current state")
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
            "operation": "activate",
            "result": _json_result(result),
        },
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
            vol.Optional("notification_roles", default=list): [_NON_EMPTY_STRING],
            vol.Optional("siren_roles", default=list): [_NON_EMPTY_STRING],
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
    if _module_key(msg) == _HEATING_MODULE_KEY:
        _reject_v2_write(connection, msg, "start")
        return
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
    if _module_key(msg) == _HEATING_MODULE_KEY:
        _reject_v2_write(connection, msg, "update")
        return
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
    if _module_key(msg) == _HEATING_MODULE_KEY:
        _reject_v2_write(connection, msg, "canonicalize")
        return
    await _send(hass, connection, msg, "canonicalize", _canonicalize_draft)


@websocket_api.websocket_command(
    _schema(
        SETUP_WRITE_V1_ACTIVATE,
        {
            vol.Optional("draft_id"): _NON_EMPTY_STRING,
            vol.Optional("canonical_revision_id"): _NON_EMPTY_STRING,
            vol.Optional("snapshot_id"): _NON_EMPTY_STRING,
            vol.Optional("captured_at"): _aware_datetime,
            vol.Optional("report_id"): _NON_EMPTY_STRING,
            vol.Optional("attempt_id", default=None): _OPTIONAL_STRING,
            vol.Optional("notification_roles", default=list): [_NON_EMPTY_STRING],
            vol.Optional("siren_roles", default=list): [_NON_EMPTY_STRING],
            vol.Optional("revision_id"): _NON_EMPTY_STRING,
            vol.Optional("semantic_configuration_fingerprint"): vol.Match(r"^[0-9a-f]{64}$"),
            vol.Optional("expected_active_revision_id", default=None): _OPTIONAL_STRING,
            vol.Optional("expected_active_generation"): _non_negative_integer,
            **_optional_preferences(),
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _activate(hass: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _activate_water_setup(hass, connection, msg)


def _reject_v2_write(
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    operation: str,
) -> None:
    connection.send_error(
        msg["id"],
        ERR_CANONICAL_V3_REQUIRED,
        f"Setup Write v1 {operation} is compatibility-only; use Canonical configuration v3",
    )


@websocket_api.websocket_command(
    _schema(
        CONFIGURATION_V3_START,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("snapshot_id"): _NON_EMPTY_STRING,
            **dict((_required_time("created_at"),)),
            vol.Required("bindings"): dict,
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _configuration_v3_start(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await _send_configuration_v3(hass, connection, msg, "start", _start_configuration_v3)


@websocket_api.websocket_command(
    _schema(
        CONFIGURATION_V3_CONVERT_V2,
        {
            vol.Required("source_revision_id"): _NON_EMPTY_STRING,
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("projection_revision_id"): _NON_EMPTY_STRING,
            vol.Required("snapshot_id"): _NON_EMPTY_STRING,
            **dict((_required_time("created_at"),)),
            vol.Optional("expected_active_revision_id", default=None): _OPTIONAL_STRING,
            vol.Required("expected_active_generation"): _non_negative_integer,
            vol.Optional("binding_overrides", default=dict): dict,
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _configuration_v3_convert_v2(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await _send_configuration_v3(hass, connection, msg, "convert-v2", _convert_v2_configuration_v3)


@websocket_api.websocket_command(
    _schema(
        CONFIGURATION_V3_CONVERT_LEGACY,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("v2_revision_id"): _NON_EMPTY_STRING,
            vol.Required("projection_revision_id"): _NON_EMPTY_STRING,
            vol.Required("snapshot_id"): _NON_EMPTY_STRING,
            **dict((_required_time("created_at"),)),
            vol.Required("core_version"): _NON_EMPTY_STRING,
            vol.Optional("integration_version", default=None): _OPTIONAL_STRING,
            vol.Optional("binding_overrides", default=dict): dict,
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _configuration_v3_convert_legacy(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await _send_configuration_v3(
        hass,
        connection,
        msg,
        "convert-legacy",
        _convert_legacy_configuration_v3,
    )


@websocket_api.websocket_command(
    _schema(
        CONFIGURATION_V3_ACTIVE,
        {
            vol.Required("snapshot_id"): _NON_EMPTY_STRING,
            **dict((_required_time("captured_at"),)),
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _configuration_v3_active(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await _send_configuration_v3(hass, connection, msg, "active", _read_configuration_v3)


@websocket_api.websocket_command(
    _schema(
        CONFIGURATION_V3_EDIT,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            **dict((_required_time("created_at"),)),
            vol.Required("expected_active_generation"): _positive_integer,
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _configuration_v3_edit(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await _send_configuration_v3(hass, connection, msg, "edit", _edit_configuration_v3)


@websocket_api.websocket_command(
    _schema(
        CONFIGURATION_V3_DRAFT,
        {vol.Required("draft_id"): _NON_EMPTY_STRING},
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _configuration_v3_draft(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await _send_configuration_v3(hass, connection, msg, "draft", _reopen_configuration_v3)


@websocket_api.websocket_command(_schema(CONFIGURATION_V3_DRAFTS, {}))
@websocket_api.require_admin
@websocket_api.async_response
async def _configuration_v3_drafts(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await _send_configuration_v3(hass, connection, msg, "drafts", _list_configuration_v3_drafts)


@websocket_api.websocket_command(
    _schema(
        CONFIGURATION_V3_ABANDON,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("expected_revision"): _positive_integer,
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _configuration_v3_abandon(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await _send_configuration_v3(hass, connection, msg, "abandon", _abandon_configuration_v3)


@websocket_api.websocket_command(
    _schema(
        CONFIGURATION_V3_UPDATE,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("expected_revision"): _positive_integer,
            **dict((_required_time("updated_at"),)),
            vol.Required("configuration_scopes"): dict,
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _configuration_v3_update(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await _send_configuration_v3(hass, connection, msg, "update", _update_configuration_v3)


@websocket_api.websocket_command(
    _schema(
        CONFIGURATION_V3_VALIDATE,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("report_id"): _NON_EMPTY_STRING,
            vol.Required("snapshot_id"): _NON_EMPTY_STRING,
            **dict((_required_time("evaluated_at"),)),
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _configuration_v3_validate(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await _send_configuration_v3(hass, connection, msg, "validate", _validate_configuration_v3)


@websocket_api.websocket_command(
    _schema(
        CONFIGURATION_V3_CANONICALIZE,
        {
            vol.Required("draft_id"): _NON_EMPTY_STRING,
            vol.Required("validation_report_id"): _NON_EMPTY_STRING,
            vol.Required("revision_id"): _NON_EMPTY_STRING,
            vol.Required("snapshot_id"): _NON_EMPTY_STRING,
            **dict((_required_time("created_at"),)),
            vol.Required("actor"): _NON_EMPTY_STRING,
            vol.Required("source"): _NON_EMPTY_STRING,
            vol.Required("change_kind"): _NON_EMPTY_STRING,
            vol.Required("reason"): _NON_EMPTY_STRING,
            vol.Required("core_version"): _NON_EMPTY_STRING,
            vol.Optional("integration_version", default=None): _OPTIONAL_STRING,
        },
    )
)
@websocket_api.require_admin
@websocket_api.async_response
async def _configuration_v3_canonicalize(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await _send_configuration_v3(
        hass,
        connection,
        msg,
        "canonicalize",
        _canonicalize_configuration_v3,
    )


@websocket_api.websocket_command(
    _schema(
        CONFIGURATION_V3_ACTIVATE,
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
async def _configuration_v3_activate(
    hass: Any,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Use the same serialized CAS transaction as every canonical activation."""

    entry = hass.config_entries.async_get_entry(msg["config_entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Controlel config entry was not found")
        return
    try:
        from .activation_backend import async_activate_canonical_revision

        backend = await async_get_setup_backend(hass, entry)
        await backend.repository.get_canonical_revision_v3(msg["revision_id"])
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
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Canonical v3 revision was not found")
        return
    except SetupConflictError:
        connection.send_error(msg["id"], ERR_SETUP_CONFLICT, "Canonical v3 activation conflicts with authority")
        return
    except SetupStorageIntegrityError:
        connection.send_error(msg["id"], ERR_SETUP_STORAGE_INTEGRITY, "Setup storage failed integrity validation")
        return
    except (TypeError, ValueError, ValidationError):
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, "Canonical v3 activation is invalid")
        return
    connection.send_result(
        msg["id"],
        {
            "canonical_configuration_api_version": CANONICAL_CONFIGURATION_API_VERSION,
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
