from datetime import timedelta

import pytest

from controlel.application.configuration.heating_setup_adapter import (
    HEAT_DELIVERY_ACTUATOR_ROLE,
    HEATING_SETUP_SCHEMA_VERSION,
    HeatingSetupAdapter,
)
from controlel.application.setup import (
    BindingSelection,
    DraftRevision,
    InMemorySetupRepository,
    SelectionOrigin,
    SetupConflictError,
    SetupNotFoundError,
)

from .conftest import NOW, complete_draft, provider_reference


def test_incomplete_draft_can_be_saved_reopened_edited_and_deleted() -> None:
    repository = InMemorySetupRepository()
    settings = {"zone_name": "Living room", "nested": {"incomplete": True}}
    first = DraftRevision(
        draft_id="incomplete",
        revision=1,
        environment_id="home",
        module_key="heating",
        module_instance_id="main-heating",
        module_schema_version=HEATING_SETUP_SCHEMA_VERSION,
        created_at=NOW,
        updated_at=NOW,
        settings=settings,
    )
    repository.save_draft(first)
    settings["nested"]["incomplete"] = False

    reopened = repository.get_draft("incomplete")
    assert reopened.settings["nested"]["incomplete"] is True

    second = reopened.next_revision(
        updated_at=NOW + timedelta(minutes=1),
        settings={"zone_name": "Living room", "target_temperature_celsius": 21.0},
    )
    repository.save_draft(second)
    assert repository.get_draft("incomplete").revision == 2
    assert repository.get_draft("incomplete", 1) == first

    repository.delete_draft("incomplete", expected_revision=2)
    with pytest.raises(SetupNotFoundError):
        repository.get_draft("incomplete")


def test_stale_draft_deletion_is_rejected() -> None:
    repository = InMemorySetupRepository()
    first = complete_draft(draft_id="delete-conflict")
    repository.save_draft(first)
    second = first.next_revision(updated_at=NOW + timedelta(minutes=1))
    repository.save_draft(second)

    with pytest.raises(SetupConflictError, match="changed before deletion"):
        repository.delete_draft(first.draft_id, expected_revision=first.revision)

    assert repository.get_draft(first.draft_id) == second


def test_validation_failure_does_not_destroy_or_edit_draft() -> None:
    repository = InMemorySetupRepository()
    draft = DraftRevision(
        draft_id="invalid",
        revision=1,
        environment_id="home",
        module_key="heating",
        module_instance_id="main-heating",
        module_schema_version=HEATING_SETUP_SCHEMA_VERSION,
        created_at=NOW,
        updated_at=NOW,
        settings={"zone_name": "incomplete"},
    )
    repository.save_draft(draft)

    report = HeatingSetupAdapter().validate(draft, report_id="invalid-report", evaluated_at=NOW)

    assert report.activation_ready is False
    assert report.issues
    assert repository.get_draft("invalid") == draft


def test_validation_report_applies_to_one_exact_draft_revision() -> None:
    adapter = HeatingSetupAdapter()
    first = complete_draft()
    report = adapter.validate(first, report_id="report", evaluated_at=NOW)
    second = first.next_revision(updated_at=NOW + timedelta(seconds=1), settings=dict(first.settings))

    assert report.assesses(first)
    assert not report.assesses(second)
    with pytest.raises(ValueError, match="exact draft revision"):
        adapter.canonicalize(
            second,
            report,
            configuration_id="configuration",
            revision_id="revision",
            revision=1,
            provider="home_assistant",
            provider_instance_id="ha-home",
            created_at=NOW,
            actor="user",
            source="setup_api",
            change_kind="CREATE",
            reason="test",
            core_version="0.11.0",
        )


def test_heating_adapter_preserves_arbitrary_service_domain_name_and_target_binding() -> None:
    draft = complete_draft()
    adapter = HeatingSetupAdapter()
    report = adapter.validate(draft, report_id="report", evaluated_at=NOW)
    canonical = adapter.canonicalize(
        draft,
        report,
        configuration_id="configuration",
        revision_id="revision",
        revision=1,
        provider="home_assistant",
        provider_instance_id="ha-home",
        created_at=NOW,
        actor="user",
        source="setup_api",
        change_kind="CREATE",
        reason="test",
        core_version="0.11.0",
    )

    assert canonical.module_payload["source_enable"] == {
        "domain": "vendor_boiler",
        "service": "grant_heat_permission",
        "target_binding_role": "heating.source.enable_target",
    }
    assert canonical.module_payload["source_disable"] == {
        "domain": "script",
        "service": "revoke_heat_permission",
        "target_binding_role": "heating.source.disable_target",
    }


def test_heating_adapter_preserves_optional_heat_delivery_actuator_binding() -> None:
    draft = complete_draft()
    settings = dict(draft.settings)
    settings.update(
        {
            "heat_delivery_mode": "setpoint_assist",
            "heat_delivery_actuator_binding_role": HEAT_DELIVERY_ACTUATOR_ROLE,
            "heat_delivery_ownership": "controlel_owned",
            "heat_delivery_assist_policy": "always_assist_while_heating",
            "heat_delivery_assist_target_celsius": 32.0,
        }
    )
    heat_delivery_binding = BindingSelection(
        role=HEAT_DELIVERY_ACTUATOR_ROLE,
        reference=provider_reference("heat-delivery-actuator", "climate.living_room"),
        selection_origin=SelectionOrigin.MANUAL,
        user_confirmed=True,
    )
    configured = draft.next_revision(
        updated_at=NOW + timedelta(seconds=1),
        settings=settings,
        bindings=(*draft.bindings, heat_delivery_binding),
    )
    adapter = HeatingSetupAdapter()
    report = adapter.validate(configured, report_id="heat-delivery", evaluated_at=NOW + timedelta(seconds=1))
    canonical = adapter.canonicalize(
        configured,
        report,
        configuration_id="configuration",
        revision_id="heat-delivery-revision",
        revision=1,
        provider="home_assistant",
        provider_instance_id="ha-home",
        created_at=NOW + timedelta(seconds=2),
        actor="user",
        source="setup_api",
        change_kind="CREATE",
        reason="heat_delivery",
        core_version="0.11.0",
    )

    assert canonical.module_payload["heat_delivery_actuator_binding_role"] == HEAT_DELIVERY_ACTUATOR_ROLE
    assert canonical.module_payload["heat_delivery_mode"] == "setpoint_assist"
    assert any(binding.role == HEAT_DELIVERY_ACTUATOR_ROLE for binding in canonical.bindings)


def test_heating_adapter_rejects_controlel_service_domain() -> None:
    draft = complete_draft()
    settings = dict(draft.settings)
    settings["source_enable"] = {
        "domain": "controlel",
        "service": "enable_heating",
        "target_binding_role": "heating.source.enable_target",
    }
    changed = draft.next_revision(updated_at=NOW + timedelta(seconds=1), settings=settings)

    report = HeatingSetupAdapter().validate(changed, report_id="recursive-service", evaluated_at=NOW)

    assert report.activation_ready is False
    assert any(issue.code == "heating.invalid_setting" for issue in report.issues)
