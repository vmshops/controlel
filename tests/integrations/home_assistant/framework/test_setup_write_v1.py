"""Real Home Assistant transport tests for Setup Write API v1."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
import custom_components.controlel.setup_write_websocket as setup_transport
from controlel.application.configuration.heating_setup_adapter import (
    PRIMARY_TEMPERATURE_ROLE,
    SOURCE_DISABLE_TARGET_ROLE,
    SOURCE_ENABLE_TARGET_ROLE,
    HeatingSetupPayload,
)
from controlel.infrastructure.home_assistant import ACTIVE_REFERENCE_KEY, HeatingBindingSelectionRequest
from custom_components.controlel.const import CONF_TEMPERATURE_ENTITY_ID, DOMAIN
from custom_components.controlel.setup_backend import async_get_setup_service
from custom_components.controlel.setup_write_websocket import (
    ERR_CANONICAL_V3_REQUIRED,
    SETUP_WRITE_V1_ACTIVATE,
    SETUP_WRITE_V1_CANONICALIZE,
    SETUP_WRITE_V1_DEFAULTS,
    SETUP_WRITE_V1_DELETE,
    SETUP_WRITE_V1_DISCOVERY,
    SETUP_WRITE_V1_RECOMMENDATIONS,
    SETUP_WRITE_V1_REOPEN,
    SETUP_WRITE_V1_START,
    SETUP_WRITE_V1_UPDATE,
    SETUP_WRITE_V1_VALIDATE,
)

NOW = "2026-08-24T12:00:00Z"


def _contract_messages(entry_id: str) -> tuple[tuple[str, str, dict[str, object]], ...]:
    common = {"config_entry_id": entry_id}
    preferences = {"preferred_area_id": None, "preferred_floor_id": None}
    return (
        (
            "get_discovery_snapshot",
            "discovery",
            {**common, "type": SETUP_WRITE_V1_DISCOVERY, "snapshot_id": "snapshot-1", "captured_at": NOW},
        ),
        (
            "get_recommendations",
            "recommendations",
            {
                **common,
                **preferences,
                "type": SETUP_WRITE_V1_RECOMMENDATIONS,
                "snapshot_id": "snapshot-1",
                "captured_at": NOW,
            },
        ),
        (
            "reopen_heating_setup",
            "reopen",
            {
                **common,
                **preferences,
                "type": SETUP_WRITE_V1_REOPEN,
                "draft_id": "draft-1",
                "snapshot_id": "snapshot-1",
                "captured_at": NOW,
            },
        ),
        (
            "validate_heating_draft",
            "validate",
            {
                **common,
                **preferences,
                "type": SETUP_WRITE_V1_VALIDATE,
                "draft_id": "draft-1",
                "snapshot_id": "snapshot-1",
                "evaluated_at": NOW,
                "report_id": "report-3",
            },
        ),
    )


@pytest.mark.asyncio
async def test_contract_routes_every_operation_to_existing_host_service(
    hass,
    hass_ws_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    service = SimpleNamespace(
        **{
            method: AsyncMock(return_value={"delegated_to": method})
            for method, _operation, _message in _contract_messages(entry.entry_id)
        }
    )

    async def get_service(hass_object, target_entry, *, module_key="heating"):
        assert hass_object is hass
        assert target_entry is entry
        assert module_key == "heating"
        return service

    monkeypatch.setattr(setup_transport, "async_get_setup_service", get_service)
    assert await component.async_setup(hass, {})
    client = await hass_ws_client(hass)

    for method, operation, message in _contract_messages(entry.entry_id):
        await client.send_json_auto_id(message)
        response = await client.receive_json()

        assert response["success"] is True
        assert response["result"] == {
            "setup_write_api_version": 1,
            "operation": operation,
            "result": {"delegated_to": method},
        }
        getattr(service, method).assert_awaited_once()


@pytest.mark.asyncio
async def test_v1_start_is_rejected_without_changing_runtime_control(
    hass,
    hass_ws_client,
    entry_data,
    service_calls,
) -> None:
    hass.states.async_set(
        entry_data[CONF_TEMPERATURE_ENTITY_ID],
        "21",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    host = entry.runtime_data.host
    assert host is not None
    client = await hass_ws_client(hass)
    data_before = deepcopy(dict(entry.data))
    options_before = deepcopy(dict(entry.options))
    runtime_before = (
        host.snapshot_source.current.revision,
        host.snapshot_source.total_trace_records,
        host.operational_event_diagnostics()["total_emitted"],
    )

    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_START,
            "config_entry_id": entry.entry_id,
            "draft_id": "draft-1",
            "module_instance_id": "main-heating",
            "created_at": NOW,
            "snapshot_id": "snapshot-1",
            "report_id": "report-1",
        }
    )
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == ERR_CANONICAL_V3_REQUIRED
    assert ACTIVE_REFERENCE_KEY not in entry.data
    assert dict(entry.data) == data_before
    assert dict(entry.options) == options_before
    assert (
        host.snapshot_source.current.revision,
        host.snapshot_source.total_trace_records,
        host.operational_event_diagnostics()["total_emitted"],
    ) == runtime_before
    assert service_calls == []


@pytest.mark.asyncio
async def test_invalid_request_fails_before_setup_service_is_called(
    hass,
    hass_ws_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    get_service = AsyncMock()
    monkeypatch.setattr(setup_transport, "async_get_setup_service", get_service)
    assert await component.async_setup(hass, {})
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_START,
            "config_entry_id": entry.entry_id,
            "draft_id": "draft-1",
            "module_instance_id": "main-heating",
            "created_at": "2026-08-24 12:00:00",
            "snapshot_id": "snapshot-1",
            "report_id": "report-1",
        }
    )
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"
    get_service.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_config_entry_and_missing_draft_are_deterministically_rejected(
    hass,
    hass_ws_client,
) -> None:
    controlel_entry = MockConfigEntry(domain=DOMAIN, data={})
    controlel_entry.add_to_hass(hass)
    other_entry = MockConfigEntry(domain="other_integration", data={})
    other_entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_DISCOVERY,
            "config_entry_id": other_entry.entry_id,
            "snapshot_id": "snapshot-1",
            "captured_at": NOW,
        }
    )
    wrong_entry = await client.receive_json()
    assert wrong_entry["success"] is False
    assert wrong_entry["error"]["code"] == "not_found"

    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_REOPEN,
            "config_entry_id": controlel_entry.entry_id,
            "draft_id": "missing-draft",
            "snapshot_id": "snapshot-1",
            "captured_at": NOW,
        }
    )
    missing_draft = await client.receive_json()
    assert missing_draft["success"] is False
    assert missing_draft["error"]["code"] == "not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        {
            "type": SETUP_WRITE_V1_START,
            "draft_id": "v2-must-not-start",
            "module_instance_id": "main-heating",
            "created_at": NOW,
            "snapshot_id": "snapshot-1",
            "report_id": "report-1",
        },
        {
            "type": SETUP_WRITE_V1_UPDATE,
            "draft_id": "existing-v2-draft",
            "expected_revision": 1,
            "updated_at": NOW,
            "snapshot_id": "snapshot-1",
            "report_id": "report-2",
            "settings": {},
            "selections": [],
        },
        {
            "type": SETUP_WRITE_V1_CANONICALIZE,
            "draft_id": "existing-v2-draft",
            "snapshot_id": "snapshot-1",
            "created_at": NOW,
            "validation_report_id": "report-3",
            "configuration_id": "configuration-1",
            "revision_id": "v2-must-not-canonicalize",
            "revision": 1,
            "actor": "test:admin",
            "source": "test",
            "change_kind": "CREATE",
            "reason": "authority_gate",
            "core_version": "0.16.0",
        },
        {
            "type": SETUP_WRITE_V1_ACTIVATE,
            "revision_id": "existing-v2-revision",
            "semantic_configuration_fingerprint": "a" * 64,
            "expected_active_revision_id": None,
            "expected_active_generation": 0,
            "attempt_id": "v2-must-not-activate",
        },
    ],
    ids=("start", "update", "canonicalize", "activate"),
)
async def test_v1_mutation_and_activation_routes_require_canonical_v3(
    hass,
    hass_ws_client,
    message: dict[str, object],
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({**message, "config_entry_id": entry.entry_id})
    rejected = await client.receive_json()

    assert rejected["success"] is False
    assert rejected["error"]["code"] == ERR_CANONICAL_V3_REQUIRED


@pytest.mark.asyncio
async def test_existing_v2_draft_remains_reopen_validate_delete_compatible(
    hass,
    hass_ws_client,
) -> None:
    """A normal HA area, temperature sensor, and switch can reach READY."""

    area = ar.async_get(hass).async_create("Printing room")
    registry = er.async_get(hass)
    temperature = registry.async_get_or_create(
        "sensor",
        "setup-ready-test",
        "printing-room-temperature",
        suggested_object_id="printing_room_temperature",
        original_device_class="temperature",
        unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    temperature = registry.async_update_entity(temperature.entity_id, area_id=area.id)
    source = registry.async_get_or_create(
        "switch",
        "setup-ready-test",
        "boiler-permission",
        suggested_object_id="boiler_permission",
    )
    source = registry.async_update_entity(source.entity_id, area_id=area.id)
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": SETUP_WRITE_V1_DEFAULTS, "config_entry_id": entry.entry_id})
    defaults_response = await client.receive_json()
    assert defaults_response["success"] is True
    defaults = defaults_response["result"]["result"]
    assert defaults["core_version"] == "0.16.0"
    assert defaults["integration_version"] == "0.14.0"
    assert defaults["settings"]["target_temperature_celsius"] == 21.0
    assert defaults["settings"]["primary_measurement_max_age_seconds"] == 900.0
    assert defaults["settings"]["maximum_future_skew_seconds"] == 30.0
    assert defaults["settings"]["indeterminate_grace_period_seconds"] == 120.0

    host_service = await async_get_setup_service(hass, entry)
    created_at = datetime.fromisoformat(NOW)
    started_model = await host_service.start_new_heating_setup(
        draft_id="draft-simple-switch-ready",
        module_instance_id="main-heating",
        created_at=created_at,
        snapshot_id="snapshot-ready-1",
        report_id="report-ready-1",
        settings=defaults["settings"],
    )
    started = started_model.model_dump(mode="json")

    candidates_by_role = {
        recommendation["role"]: [
            candidate
            for candidate in [recommendation["recommended"], *recommendation["alternatives"]]
            if candidate is not None
        ]
        for recommendation in started["recommendations"]
    }

    def candidate_for(role: str, locator: str) -> dict[str, object]:
        return next(candidate for candidate in candidates_by_role[role] if candidate["current_locator"] == locator)

    selected = {
        PRIMARY_TEMPERATURE_ROLE: candidate_for(PRIMARY_TEMPERATURE_ROLE, temperature.entity_id),
        SOURCE_ENABLE_TARGET_ROLE: candidate_for(SOURCE_ENABLE_TARGET_ROLE, source.entity_id),
        SOURCE_DISABLE_TARGET_ROLE: candidate_for(SOURCE_DISABLE_TARGET_ROLE, source.entity_id),
    }
    settings = {
        **defaults["settings"],
        **defaults["simple_switch"],
        "zone_id": area.id,
        "zone_name": area.id,
        "sensor_id": temperature.id,
        "sensor_name": temperature.entity_id,
    }
    selections = tuple(
        HeatingBindingSelectionRequest(
            role=role,
            candidate_id=str(candidate["candidate_id"]),
            user_confirmed=True,
        )
        for role, candidate in selected.items()
    )

    saved_model = await host_service.update_heating_draft(
        str(started["draft_id"]),
        expected_revision=int(started["draft_revision"]),
        updated_at=created_at,
        snapshot_id="snapshot-ready-1",
        report_id="report-ready-2",
        settings=settings,
        selections=selections,
        preferred_area_id=area.id,
    )
    saved = saved_model.model_dump(mode="json")
    assert saved["draft_revision"] == 2
    assert set(saved["settings"]) == set(HeatingSetupPayload.model_fields)
    assert saved["settings"]["source_enable"] == {
        "domain": "switch",
        "service": "turn_on",
        "target_binding_role": SOURCE_ENABLE_TARGET_ROLE,
    }
    assert saved["settings"]["source_disable"] == {
        "domain": "switch",
        "service": "turn_off",
        "target_binding_role": SOURCE_DISABLE_TARGET_ROLE,
    }

    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_REOPEN,
            "config_entry_id": entry.entry_id,
            "draft_id": saved["draft_id"],
            "snapshot_id": "snapshot-ready-2",
            "captured_at": NOW,
            "preferred_area_id": area.id,
        }
    )
    reopened_response = await client.receive_json()
    assert reopened_response["success"] is True
    reopened = reopened_response["result"]["result"]
    assert reopened["draft_revision"] == 2
    assert reopened["settings"] == saved["settings"]

    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_VALIDATE,
            "config_entry_id": entry.entry_id,
            "draft_id": reopened["draft_id"],
            "snapshot_id": "snapshot-ready-3",
            "evaluated_at": NOW,
            "report_id": "report-ready-3",
            "preferred_area_id": area.id,
        }
    )
    validated_response = await client.receive_json()
    assert validated_response["success"] is True
    validated = validated_response["result"]["result"]
    assert validated["validation_status"] == "CURRENT"
    assert validated["incomplete"] is False
    assert validated["activation_ready"] is True
    assert validated["blocking_issue_count"] == 0

    await client.send_json_auto_id(
        {
            "type": SETUP_WRITE_V1_DELETE,
            "config_entry_id": entry.entry_id,
            "draft_id": validated["draft_id"],
            "expected_revision": validated["draft_revision"],
        }
    )
    deleted_response = await client.receive_json()
    assert deleted_response["success"] is True
    assert deleted_response["result"]["result"] == {
        "draft_id": validated["draft_id"],
        "deleted_revision": validated["draft_revision"],
    }
