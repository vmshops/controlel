"""User-journey regressions for Water/Heating draft lifecycle and navigation no-ops."""

from __future__ import annotations

from copy import deepcopy

import pytest
from homeassistant import data_entry_flow

from controlel.infrastructure.home_assistant import ACTIVE_REFERENCE_KEY, active_reference_for_module
from custom_components.controlel import config_flow as cf
from custom_components.controlel.setup_backend import async_get_setup_backend

from .test_config_flow import (
    _activate_new_heating,
    _activate_water_draft,
    _choose,
    _defaults,
    _empty_entry,
    _open_heating_menu,
    _open_water_menu,
    _register_notify_targets,
    _register_shutoff_valve_candidates,
    _register_siren_candidates,
    _register_water_candidates,
    _water_drafts,
)


async def _activate_complete_water_baseline(hass):
    utility, _garage, moisture, _outside, _unrelated = _register_water_candidates(hass)
    (phone,) = _register_notify_targets(hass, "journey_phone")
    siren, _other, _bad = _register_siren_candidates(hass)
    _register_shutoff_valve_candidates(hass)
    hass.states.async_set(moisture, "off")
    entry = await _empty_entry(hass, title="Water draft lifecycle")

    water = await _open_water_menu(hass, entry)
    area = await _choose(hass, water, "water_safety_area_sensor")
    water = await hass.config_entries.options.async_configure(
        area["flow_id"],
        {
            cf.WATER_AREA: utility.id,
            cf.WATER_MOISTURE_SENSOR: moisture,
            cf.WATER_SHOW_ALL_COMPATIBLE: False,
        },
    )
    notifications = await _choose(hass, water, "water_safety_notifications")
    water = await hass.config_entries.options.async_configure(
        notifications["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [phone], cf.WATER_TEST_NOTIFICATION: False},
    )
    sirens = await _choose(hass, water, "water_safety_sirens")
    water = await hass.config_entries.options.async_configure(
        sirens["flow_id"],
        {cf.WATER_SIREN_TARGETS: [siren]},
    )
    activated = await _activate_water_draft(hass, water)
    assert activated["type"].name == "CREATE_ENTRY"
    await hass.async_block_till_done()
    assert await _water_drafts(hass, entry) == ()
    return entry, utility, moisture, phone, siren


def _assert_clean_review_summary(summary: str) -> None:
    assert "unexpected binding" not in summary
    assert "invalid setting" not in summary
    assert "water_safety." not in summary
    assert "notification settings" not in summary.lower()


@pytest.mark.asyncio
async def test_water_a_active_empty_shutoff_submit_is_noop_and_review_clean(hass) -> None:
    entry, _utility, _moisture, _phone, _siren = await _activate_complete_water_baseline(hass)
    before_data = deepcopy(dict(entry.data))
    active = entry.data[ACTIVE_REFERENCE_KEY]
    backend = await async_get_setup_backend(hass, entry)
    before_revision = await backend.repository.get_canonical_revision(active["canonical_revision_id"])

    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_shutoff_valves")
    assert _defaults(form)[cf.WATER_SHUTOFF_VALVE_TARGETS] == []
    after = await hass.config_entries.options.async_configure(form["flow_id"], _defaults(form))

    assert await _water_drafts(hass, entry) == ()
    assert "NO DRAFT CHANGES" in after["description_placeholders"]["water_safety_summary"]
    assert "water_safety_abandon" not in after["menu_options"]
    review = await _choose(hass, after, "water_safety_validation")
    summary = review["description_placeholders"]["validation_summary"]
    assert "NO DRAFT CHANGES" in summary
    _assert_clean_review_summary(summary)
    assert entry.data == before_data
    assert await backend.repository.get_canonical_revision(active["canonical_revision_id"]) == before_revision


@pytest.mark.asyncio
async def test_water_b_c_g_optional_sections_resubmit_preserve_siren_and_notifications(hass) -> None:
    entry, _utility, _moisture, phone, siren = await _activate_complete_water_baseline(hass)
    before_data = deepcopy(dict(entry.data))

    for step, field, expected in (
        ("water_safety_sirens", cf.WATER_SIREN_TARGETS, [siren]),
        ("water_safety_notifications", cf.WATER_NOTIFICATION_TARGETS, [phone]),
        ("water_safety_shutoff_valves", cf.WATER_SHUTOFF_VALVE_TARGETS, []),
    ):
        form = await _choose(hass, await _open_water_menu(hass, entry), step)
        assert _defaults(form)[field] == expected
        after = await hass.config_entries.options.async_configure(form["flow_id"], _defaults(form))
        assert await _water_drafts(hass, entry) == ()
        assert "NO DRAFT CHANGES" in after["description_placeholders"]["water_safety_summary"]

    assert entry.data == before_data
    reopen_sirens = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_sirens")
    assert _defaults(reopen_sirens)[cf.WATER_SIREN_TARGETS] == [siren]


@pytest.mark.asyncio
async def test_water_d_e_f_explicit_empty_optional_clears_remain_valid(hass) -> None:
    entry, utility, _moisture, _phone, _siren = await _activate_complete_water_baseline(hass)

    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_shutoff_valves")
    water = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_SHUTOFF_VALVE_TARGETS: []},
    )
    assert await _water_drafts(hass, entry) == ()

    form = await _choose(hass, water, "water_safety_sirens")
    water = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_SIREN_TARGETS: []},
    )
    draft = (await _water_drafts(hass, entry))[0]
    assert list(draft.settings.get("siren_target_roles", ())) == []
    assert not any(binding.role.startswith("water_safety.siren.") for binding in draft.bindings)
    assert draft.settings.get("area_id") == utility.id
    assert any(binding.role == "water_safety.moisture_sensor" for binding in draft.bindings)

    form = await _choose(hass, water, "water_safety_notifications")
    water = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_NOTIFICATION_TARGETS: [], cf.WATER_TEST_NOTIFICATION: False},
    )
    draft = (await _water_drafts(hass, entry))[0]
    assert list(draft.settings.get("notification_target_roles", ())) == []
    assert not any(binding.role.startswith("water_safety.notification.") for binding in draft.bindings)

    backend = await async_get_setup_backend(hass, entry)
    report = await backend.repository.get_latest_validation_report(draft.draft_id)
    assert report is not None
    assert report.activation_ready is True
    assert all(issue.code != "water_safety.unsupported_binding_role" for issue in report.issues)

    review = await _choose(hass, water, "water_safety_validation")
    summary = review["description_placeholders"]["validation_summary"]
    assert "READY TO ACTIVATE" in summary
    _assert_clean_review_summary(summary)


@pytest.mark.asyncio
async def test_water_h_missing_moisture_review_message(hass) -> None:
    utility, _garage, _moisture, _outside, _unrelated = _register_water_candidates(hass)
    entry = await _empty_entry(hass)
    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_area_sensor")
    water = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_AREA: utility.id, cf.WATER_SHOW_ALL_COMPATIBLE: False},
    )
    review = await _choose(hass, water, "water_safety_validation")
    summary = review["description_placeholders"]["validation_summary"]
    assert "Moisture sensor is required" in summary
    assert "notification" not in summary.lower()
    _assert_clean_review_summary(summary)


@pytest.mark.asyncio
async def test_water_i_abandon_restores_active_without_runtime_change(hass) -> None:
    entry, _utility, _moisture, _phone, siren = await _activate_complete_water_baseline(hass)
    before_data = deepcopy(dict(entry.data))
    active = entry.data[ACTIVE_REFERENCE_KEY]
    backend = await async_get_setup_backend(hass, entry)
    before_revision = await backend.repository.get_canonical_revision(active["canonical_revision_id"])

    form = await _choose(hass, await _open_water_menu(hass, entry), "water_safety_sirens")
    water = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {cf.WATER_SIREN_TARGETS: []},
    )
    assert await _water_drafts(hass, entry)
    assert "water_safety_abandon" in water["menu_options"]

    abandon = await _choose(hass, water, "water_safety_abandon")
    water = await hass.config_entries.options.async_configure(abandon["flow_id"], {})
    assert await _water_drafts(hass, entry) == ()
    assert "NO DRAFT CHANGES" in water["description_placeholders"]["water_safety_summary"]
    assert "water_safety_abandon" not in water["menu_options"]
    assert entry.data == before_data
    assert await backend.repository.get_canonical_revision(active["canonical_revision_id"]) == before_revision

    reopen = await _choose(hass, water, "water_safety_sirens")
    assert _defaults(reopen)[cf.WATER_SIREN_TARGETS] == [siren]


@pytest.mark.asyncio
async def test_water_j_open_every_section_abort_without_changes(hass) -> None:
    entry, *_rest = await _activate_complete_water_baseline(hass)
    before_data = deepcopy(dict(entry.data))
    active = entry.data[ACTIVE_REFERENCE_KEY]
    backend = await async_get_setup_backend(hass, entry)
    before_revision = await backend.repository.get_canonical_revision(active["canonical_revision_id"])

    for step in (
        "water_safety_area_sensor",
        "water_safety_notifications",
        "water_safety_sirens",
        "water_safety_shutoff_valves",
    ):
        form = await _choose(hass, await _open_water_menu(hass, entry), step)
        hass.config_entries.options.async_abort(form["flow_id"])
        assert await _water_drafts(hass, entry) == ()

    root = await _open_water_menu(hass, entry)
    assert "NO DRAFT CHANGES" in root["description_placeholders"]["water_safety_summary"]
    assert entry.data == before_data
    assert await backend.repository.get_canonical_revision(active["canonical_revision_id"]) == before_revision


@pytest.mark.asyncio
async def test_heating_optional_section_resubmit_is_noop(hass) -> None:
    entry = await _empty_entry(hass, title="Heating no-op")
    active_before = await _activate_new_heating(hass, entry, platform="heating-noop")
    before_data = deepcopy(dict(entry.data))

    heating_root = await _open_heating_menu(hass, entry)
    assert "NO DRAFT CHANGES" in heating_root["description_placeholders"]["heating_summary"]
    assert "edit_active" in heating_root["menu_options"]

    edit = await _choose(hass, heating_root, "edit_active")
    service = (await async_get_setup_backend(hass, entry)).configuration_v3
    drafts = await service.list_drafts()
    assert len(drafts) == 1
    before_revision = drafts[0].revision

    flow = edit
    for step in ("heat_delivery", "safety_timing", "notifications", "diagnostics"):
        form = await _choose(hass, flow, step)
        flow = await hass.config_entries.options.async_configure(form["flow_id"], _defaults(form))
        assert flow["step_id"] == "heating"

    drafts_after = await service.list_drafts()
    assert len(drafts_after) == 1
    assert drafts_after[0].revision == before_revision
    assert active_reference_for_module(entry.data, "heating") == active_before
    assert entry.data == before_data

    abandon = await _choose(hass, flow, "abandon_current")
    aborted = await hass.config_entries.options.async_configure(abandon["flow_id"], {})
    assert aborted["type"] is data_entry_flow.FlowResultType.ABORT
    assert aborted["reason"] == "draft_abandoned"
    assert await service.list_drafts() == ()
    assert active_reference_for_module(entry.data, "heating") == active_before
    assert entry.data == before_data

    reopened = await _open_heating_menu(hass, entry)
    assert "NO DRAFT CHANGES" in reopened["description_placeholders"]["heating_summary"]
