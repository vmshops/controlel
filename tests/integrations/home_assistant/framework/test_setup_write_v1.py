"""Real Home Assistant transport tests for Setup Write API v1."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
import custom_components.controlel.setup_write_websocket as setup_transport
from controlel.infrastructure.home_assistant import ACTIVE_REFERENCE_KEY
from custom_components.controlel.const import CONF_TEMPERATURE_ENTITY_ID, DOMAIN
from custom_components.controlel.setup_write_websocket import (
    ERR_SETUP_CONFLICT,
    SETUP_WRITE_V1_CANONICALIZE,
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
            "start_new_heating_setup",
            "start",
            {
                **common,
                **preferences,
                "type": SETUP_WRITE_V1_START,
                "draft_id": "draft-1",
                "module_instance_id": "main-heating",
                "created_at": NOW,
                "snapshot_id": "snapshot-1",
                "report_id": "report-1",
                "settings": {},
                "selections": [],
                "base_active_revision_id": None,
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
            "update_heating_draft",
            "update",
            {
                **common,
                **preferences,
                "type": SETUP_WRITE_V1_UPDATE,
                "draft_id": "draft-1",
                "expected_revision": 1,
                "updated_at": NOW,
                "snapshot_id": "snapshot-1",
                "report_id": "report-2",
                "settings": {},
                "selections": [],
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
        (
            "canonicalize_heating_draft",
            "canonicalize",
            {
                **common,
                **preferences,
                "type": SETUP_WRITE_V1_CANONICALIZE,
                "draft_id": "draft-1",
                "snapshot_id": "snapshot-1",
                "created_at": NOW,
                "validation_report_id": "report-4",
                "configuration_id": "configuration-1",
                "revision_id": "canonical-1",
                "revision": 1,
                "actor": "user:owner",
                "source": "setup_write_v1",
                "change_kind": "CREATE",
                "reason": "initial_setup",
                "core_version": "0.12.0",
                "integration_version": None,
                "parent_revision_id": None,
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

    async def get_service(hass_object, target_entry):
        assert hass_object is hass
        assert target_entry is entry
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
async def test_valid_start_is_config_entry_scoped_and_never_changes_runtime_control(
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

    assert response["success"] is True
    assert response["result"]["setup_write_api_version"] == 1
    assert response["result"]["operation"] == "start"
    session = response["result"]["result"]
    assert session["draft_id"] == "draft-1"
    assert session["draft_revision"] == 1
    assert session["canonical_revision_id"] is None
    assert session["active_revision_id"] is None
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
async def test_stale_draft_identity_returns_structured_conflict(
    hass,
    hass_ws_client,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await component.async_setup(hass, {})
    client = await hass_ws_client(hass)
    message = {
        "type": SETUP_WRITE_V1_START,
        "config_entry_id": entry.entry_id,
        "draft_id": "draft-1",
        "module_instance_id": "main-heating",
        "created_at": NOW,
        "snapshot_id": "snapshot-1",
        "report_id": "report-1",
    }

    await client.send_json_auto_id(message)
    assert (await client.receive_json())["success"] is True
    await client.send_json_auto_id(
        {
            **message,
            "created_at": "2026-08-24T12:01:00Z",
            "report_id": "report-2",
        }
    )
    conflict = await client.receive_json()

    assert conflict["success"] is False
    assert conflict["error"]["code"] == ERR_SETUP_CONFLICT
