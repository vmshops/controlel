import json
import logging
import re
from pathlib import Path

import pytest
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.controlel as component
from controlel.domain.commands.command_family import CommandFamily
from controlel.domain.commands.heat_source_command import HeatSourceCommand
from controlel.domain.commands.heating_action import HeatingAction
from custom_components.controlel.config import (
    HomeAssistantHeatSourceBinding,
    HomeAssistantServiceCall,
)
from custom_components.controlel.const import DOMAIN
from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.failure_sink import HomeAssistantScheduledFailureSink
from custom_components.controlel.heat_source import (
    HomeAssistantHeatSourcePort,
    HomeAssistantServiceCallError,
)
from custom_components.controlel.runtime_executor import HomeAssistantRuntimeExecutor

ROOT = Path(__file__).parents[4]


def service_error() -> HomeAssistantServiceCallError:
    return HomeAssistantServiceCallError(
        HeatingAction.ENABLE_HEATING,
        HomeAssistantServiceCall("switch", "turn_on", "switch.boiler"),
        RuntimeError("service unavailable"),
    )


@pytest.mark.asyncio
async def test_real_repairs_registry_reuses_recoverable_issue_and_success_removes_it(hass) -> None:
    bridge = HomeAssistantEventLoopBridge(hass.loop)
    sink = HomeAssistantScheduledFailureSink(
        hass=hass,
        bridge=bridge,
        entry_id="repairs-entry",
        logger=logging.getLogger(__name__),
    )
    registry = ir.async_get(hass)

    sink.handle_synchronous_failure(service_error())
    first = registry.async_get_issue(DOMAIN, sink.recoverable_issue_id)
    sink.handle_synchronous_failure(service_error())
    second = registry.async_get_issue(DOMAIN, sink.recoverable_issue_id)

    assert first is not None
    assert second is not None
    assert first.issue_id == second.issue_id == sink.recoverable_issue_id
    assert second.severity is ir.IssueSeverity.WARNING
    assert second.translation_key == "heat_source_service_failure"
    assert second.translation_placeholders == {
        "error": ("Home Assistant service switch.turn_on failed for switch.boiler (RuntimeError)")
    }
    assert len([issue for issue in registry.issues.values() if issue.domain == DOMAIN]) == 1

    async def successful_service(call) -> None:
        return None

    hass.services.async_register("switch", "turn_on", successful_service)
    executor = HomeAssistantRuntimeExecutor()
    port = HomeAssistantHeatSourcePort(
        hass=hass,
        bridge=bridge,
        binding=HomeAssistantHeatSourceBinding(
            enable_heating=HomeAssistantServiceCall("switch", "turn_on", "switch.boiler"),
            disable_heating=HomeAssistantServiceCall("switch", "turn_off", "switch.boiler"),
        ),
        on_success=sink.clear_service_failure_issue,
    )
    await executor.async_submit(
        port.execute,
        HeatSourceCommand(
            command_type=CommandFamily.HEATING,
            action=HeatingAction.ENABLE_HEATING,
        ),
    )
    await hass.async_block_till_done()

    assert registry.async_get_issue(DOMAIN, sink.recoverable_issue_id) is None
    await executor.async_close()


@pytest.mark.asyncio
async def test_real_repairs_registry_creates_one_stable_error_issue_for_fatal_failure(hass) -> None:
    fatal_errors: list[Exception] = []
    sink = HomeAssistantScheduledFailureSink(
        hass=hass,
        bridge=HomeAssistantEventLoopBridge(hass.loop),
        entry_id="fatal-entry",
        logger=logging.getLogger(__name__),
    )
    sink.bind_fatal_handler(fatal_errors.append)
    registry = ir.async_get(hass)
    error = RuntimeError("fatal programming failure")

    sink.handle_synchronous_failure(error)
    sink.handle_synchronous_failure(error)
    issue = registry.async_get_issue(DOMAIN, sink.fatal_issue_id)

    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.translation_key == "fatal_runtime_failure"
    assert issue.translation_placeholders == {"error": "RuntimeError"}
    assert fatal_errors == [error, error]
    assert len([item for item in registry.issues.values() if item.domain == DOMAIN]) == 1


@pytest.mark.asyncio
async def test_config_entry_removal_clears_all_owned_repairs_issues(hass, entry_data) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=entry_data)
    registry = ir.async_get(hass)
    recoverable_issue_id = f"{entry.entry_id}_heat_source_service_failure"
    fatal_issue_id = f"{entry.entry_id}_fatal_runtime_failure"
    ir.async_create_issue(
        hass,
        DOMAIN,
        recoverable_issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="heat_source_service_failure",
        translation_placeholders={"error": "test"},
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        fatal_issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="fatal_runtime_failure",
        translation_placeholders={"error": "test"},
    )

    await component.async_remove_entry(hass, entry)

    assert registry.async_get_issue(DOMAIN, recoverable_issue_id) is None
    assert registry.async_get_issue(DOMAIN, fatal_issue_id) is None


def test_repairs_translation_contract_has_matching_keys_and_placeholders() -> None:
    component = ROOT / "custom_components" / DOMAIN
    strings = json.loads((component / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((component / "translations" / "en.json").read_text(encoding="utf-8"))

    assert set(strings["issues"]) == {
        "heat_source_service_failure",
        "fatal_runtime_failure",
    }
    assert english["issues"] == strings["issues"]
    for issue in strings["issues"].values():
        assert set(re.findall(r"\{([^}]+)\}", issue["description"])) == {"error"}
    assert not (component / "repairs.py").exists()
