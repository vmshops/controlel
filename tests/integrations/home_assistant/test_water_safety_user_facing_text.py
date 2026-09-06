"""Unit coverage for Water Safety Configure user-facing copy."""

from __future__ import annotations

from datetime import UTC, datetime

from controlel.application.configuration.water_safety_setup_adapter import (
    DEFAULT_NOTIFICATION_ROLE,
    WATER_SAFETY_MODULE_KEY,
    WaterSafetySetupPayload,
)
from controlel.application.setup import ActiveReference, DraftRevision
from custom_components.controlel.water_safety_configure_view import (
    WaterSafetyConfigureView,
    water_safety_menu_summary,
    water_safety_section_detail,
)
from custom_components.controlel.water_safety_messages import WATER_SAFETY_MOJIBAKE_FRAGMENTS

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
FINGERPRINT = "a" * 64


def _draft(**settings: object) -> DraftRevision:
    return DraftRevision(
        draft_id="ha-water-draft-secret",
        revision=7,
        environment_id="home",
        module_key=WATER_SAFETY_MODULE_KEY,
        module_instance_id="water-safety-1",
        module_schema_version=1,
        created_at=NOW,
        updated_at=NOW,
        settings=dict(settings),
        bindings=(),
        lineage={},
    )


def _active() -> ActiveReference:
    return ActiveReference(
        environment_id="home",
        module_key=WATER_SAFETY_MODULE_KEY,
        module_instance_id="water-safety-1",
        canonical_revision_id="ha-water-canonical:secret",
        semantic_configuration_fingerprint=FINGERPRINT,
        generation=1,
        committing_operation_id="op-1",
    )


def test_water_menu_summaries_hide_machine_identifiers() -> None:
    incomplete = WaterSafetyConfigureView(
        lifecycle="draft_incomplete",
        draft=_draft(area_id="utility-room"),
        active=_active(),
        active_revision=None,
        payload=None,
        validation=None,
    )
    ready = WaterSafetyConfigureView(
        lifecycle="draft_ready",
        draft=_draft(area_id="utility-room"),
        active=_active(),
        active_revision=None,
        payload=None,
        validation=None,
    )
    configured = WaterSafetyConfigureView(
        lifecycle="configured",
        draft=None,
        active=_active(),
        active_revision=None,
        payload=WaterSafetySetupPayload(
            zone_id="utility-room",
            zone_name="Utility room",
            area_id="utility-room",
            area_name="Utility room",
            sensor_id="binary_sensor.utility_moisture",
            notification_target_roles=(DEFAULT_NOTIFICATION_ROLE,),
        ),
        validation=None,
    )

    for summary in (
        water_safety_menu_summary(incomplete),
        water_safety_menu_summary(ready),
        water_safety_menu_summary(configured),
        water_safety_section_detail(incomplete, "status"),
        water_safety_section_detail(configured, "status"),
    ):
        assert "ha-water-draft-secret" not in summary
        assert "ha-water-canonical:secret" not in summary
        assert "water_safety.notification" not in summary
        assert "revision" not in summary.lower()
        for fragment in WATER_SAFETY_MOJIBAKE_FRAGMENTS:
            assert fragment not in summary

    assert "ACTIVE" in water_safety_menu_summary(configured)
    assert "NO DRAFT CHANGES" in water_safety_menu_summary(configured)
    assert "NEEDS ATTENTION" in water_safety_menu_summary(incomplete)
    assert "READY TO ACTIVATE" in water_safety_menu_summary(ready)
