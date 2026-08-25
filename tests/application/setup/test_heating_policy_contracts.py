"""Canonical Heating diagnostics and notification policy contracts."""

from __future__ import annotations

from copy import deepcopy
from math import inf, nan

import pytest
from pydantic import ValidationError

from controlel.application.configuration.heating_setup_adapter import (
    HEATING_SETUP_SCHEMA_VERSION,
    POLICY_LESS_HEATING_SETUP_SCHEMA_VERSION,
    SOURCE_DISABLE_TARGET_ROLE,
    SOURCE_ENABLE_TARGET_ROLE,
    HeatingDiagnosticPolicy,
    HeatingNotificationPolicy,
    HeatingNotificationRecipient,
    HeatingSetupAdapter,
    HeatingSetupPayload,
)
from controlel.application.setup import (
    CanonicalConfigurationImporter,
    CanonicalConfigurationRevision,
    DraftRevision,
    InMemorySetupRepository,
)
from controlel.application.setup.json_data import normalize_json
from controlel.domain.commands.heating_action import HeatingAction

from .conftest import NOW, complete_draft


def _settings() -> dict[str, object]:
    normalized = normalize_json(complete_draft().settings)
    assert isinstance(normalized, dict)
    return normalized


def _draft(settings: dict[str, object]) -> DraftRevision:
    document = complete_draft().model_dump(mode="python")
    document["settings"] = settings
    return DraftRevision.model_validate(document)


def _canonicalize(draft: DraftRevision) -> CanonicalConfigurationRevision:
    adapter = HeatingSetupAdapter()
    report = adapter.validate(draft, report_id="policy-report", evaluated_at=NOW)
    assert report.activation_ready is True
    return adapter.canonicalize(
        draft,
        report,
        configuration_id="policy-configuration",
        revision_id="policy-revision",
        revision=1,
        provider="home_assistant",
        provider_instance_id="ha-home",
        created_at=NOW,
        actor="user:owner",
        source="setup_api",
        change_kind="CREATE",
        reason="policy_test",
        core_version="0.13.0",
        integration_version="0.13.0",
    )


def test_policy_models_are_frozen_forbid_extra_fields_and_validate_current_contract() -> None:
    diagnostic = HeatingDiagnosticPolicy()
    recipient = HeatingNotificationRecipient(recipient_id="phone", target="notify.phone")
    notification = HeatingNotificationPolicy(recipients=(recipient,))

    with pytest.raises(ValidationError, match="frozen"):
        diagnostic.debug_until_changed = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        HeatingDiagnosticPolicy.model_validate({"unknown": True})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        HeatingNotificationRecipient.model_validate(
            {"recipient_id": "phone", "target": "notify.phone", "unknown": True}
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        HeatingNotificationPolicy.model_validate({"unknown": True})
    assert recipient.target_configured is True
    assert notification.recipients == (recipient,)


@pytest.mark.parametrize("duration", [0, -1, True, "60", inf, nan])
def test_diagnostic_duration_requires_positive_finite_canonical_seconds(duration: object) -> None:
    with pytest.raises(ValidationError):
        HeatingDiagnosticPolicy(configured_debug_duration_seconds=duration)  # type: ignore[arg-type]


def test_duration_values_normalize_to_seconds_and_round_trip_as_floats() -> None:
    diagnostic = HeatingDiagnosticPolicy(configured_debug_duration_seconds=1800)
    notification = HeatingNotificationPolicy(
        rate_window_seconds=120,
        critical_rate_window_seconds=180,
    )

    assert diagnostic.configured_debug_duration_seconds == 1800.0
    assert notification.rate_window_seconds == 120.0
    assert notification.critical_rate_window_seconds == 180.0
    assert diagnostic.model_dump(mode="json")["configured_debug_duration_seconds"] == 1800.0
    assert notification.model_dump(mode="json")["rate_window_seconds"] == 120.0


def test_debug_until_changed_preserves_configured_duration_without_an_expiry_duration() -> None:
    expiring = HeatingDiagnosticPolicy(configured_debug_duration_seconds=900, debug_until_changed=False)
    until_changed = HeatingDiagnosticPolicy(configured_debug_duration_seconds=900, debug_until_changed=True)

    assert expiring.debug_duration_seconds == 900.0
    assert until_changed.debug_duration_seconds is None
    assert until_changed.configured_debug_duration_seconds == 900.0
    assert until_changed.model_dump(mode="json")["debug_until_changed"] is True


def test_recipient_order_is_preserved_category_sets_normalize_and_duplicate_recipients_fail() -> None:
    first = HeatingNotificationRecipient.model_validate(
        {
            "recipient_id": "wall_panel",
            "target": "notify.wall_panel",
            "categories": ["supervision", "runtime", "supervision"],
        }
    )
    second = HeatingNotificationRecipient.model_validate(
        {
            "recipient_id": "family_phone",
            "target": "notify.family_phone",
            "categories": ["source_control", "safety"],
        }
    )
    forward = HeatingNotificationPolicy(recipients=(first, second))
    reverse = HeatingNotificationPolicy(recipients=(second, first))

    assert forward != reverse
    assert tuple(recipient.recipient_id for recipient in forward.recipients) == ("wall_panel", "family_phone")
    assert tuple(recipient.recipient_id for recipient in reverse.recipients) == ("family_phone", "wall_panel")
    assert tuple(category.value for category in first.categories) == ("runtime", "supervision")

    with pytest.raises(ValidationError, match="recipient IDs must be unique"):
        HeatingNotificationPolicy(
            recipients=(
                first,
                first.model_copy(update={"target": "notify.another_panel"}),
            )
        )
    with pytest.raises(ValidationError, match="transport and target bindings must be unique"):
        HeatingNotificationPolicy(
            recipients=(
                first,
                second.model_copy(update={"target": first.target}),
            )
        )


@pytest.mark.parametrize(
    ("policy", "error"),
    [
        ({"diagnostic_profile": "verbose"}, "diagnostic_profile"),
        ({"diagnostic_profile_before_debug": "debug"}, "diagnostic_profile_before_debug"),
        ({"debug_until_changed": "yes"}, "debug_until_changed"),
    ],
)
def test_diagnostic_policy_rejects_invalid_semantics(policy: dict[str, object], error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        HeatingDiagnosticPolicy.model_validate(policy)


@pytest.mark.parametrize(
    "recipient",
    [
        {"recipient_id": "Family Phone", "target": "notify.phone"},
        {"recipient_id": "phone", "transport": "email", "target": "notify.phone"},
        {"recipient_id": "phone", "target": "switch.boiler"},
        {"recipient_id": "phone", "target": "notify.phone", "enabled": "yes"},
        {"recipient_id": "phone", "target": "notify.phone", "minimum_level": "unknown"},
        {"recipient_id": "phone", "target": "notify.phone", "categories": ["unknown"]},
    ],
)
def test_notification_recipient_rejects_unsupported_runtime_semantics(recipient: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        HeatingNotificationRecipient.model_validate(recipient)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("maximum_per_window", 0),
        ("maximum_per_window", 101),
        ("rate_window_seconds", 0),
        ("rate_window_seconds", 86_401),
        ("critical_maximum_per_window", 0),
        ("critical_maximum_per_window", 201),
        ("critical_rate_window_seconds", 0),
        ("critical_rate_window_seconds", 86_401),
        ("history_capacity", 0),
        ("history_capacity", 1_001),
    ],
)
def test_notification_policy_rejects_values_outside_current_runtime_bounds(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        HeatingNotificationPolicy.model_validate({field: value})


def test_complete_heating_payload_serializes_and_deserializes_losslessly() -> None:
    settings = _settings()
    notification = settings["notification_policy"]
    assert isinstance(notification, dict)
    recipients = notification["recipients"]
    assert isinstance(recipients, list)
    recipients.insert(
        0,
        {
            "recipient_id": "wall_panel",
            "transport": "home_assistant_notify",
            "target": "notify.wall_panel",
            "enabled": False,
            "minimum_level": "critical",
            "categories": ["safety", "runtime"],
        },
    )
    payload = HeatingSetupPayload.model_validate(settings)
    serialized = payload.model_dump_json()
    reconstructed = HeatingSetupPayload.model_validate_json(serialized)
    canonical = _canonicalize(_draft(settings))
    reconstructed_canonical = CanonicalConfigurationRevision.model_validate_json(canonical.canonical_json())
    reconstructed_canonical_payload = normalize_json(reconstructed_canonical.module_payload)
    assert isinstance(reconstructed_canonical_payload, dict)
    reconstructed_canonical_policy = reconstructed_canonical_payload["notification_policy"]
    assert isinstance(reconstructed_canonical_policy, dict)
    reconstructed_canonical_recipients = reconstructed_canonical_policy["recipients"]
    assert isinstance(reconstructed_canonical_recipients, list)

    assert reconstructed == payload
    assert reconstructed.diagnostic_policy.diagnostic_profile == "debug"
    assert reconstructed.diagnostic_policy.debug_until_changed is True
    assert reconstructed.diagnostic_policy.configured_debug_duration_seconds == 1800.0
    assert reconstructed.diagnostic_policy.diagnostic_profile_before_debug == "basic"
    assert reconstructed.notification_policy.enabled is True
    assert reconstructed.notification_policy.maximum_per_window == 4
    assert reconstructed.notification_policy.rate_window_seconds == 120.0
    assert reconstructed.notification_policy.critical_maximum_per_window == 30
    assert reconstructed.notification_policy.critical_rate_window_seconds == 180.0
    assert reconstructed.notification_policy.history_capacity == 250
    assert tuple(recipient.recipient_id for recipient in reconstructed.notification_policy.recipients) == (
        "wall_panel",
        "family_phone",
    )
    assert tuple(category.value for category in reconstructed.notification_policy.recipients[0].categories) == (
        "runtime",
        "safety",
    )
    assert [recipient["recipient_id"] for recipient in reconstructed_canonical_recipients] == [
        "wall_panel",
        "family_phone",
    ]


def test_representative_complete_heating_configuration_includes_both_policies_in_canonical_payload() -> None:
    draft = complete_draft()
    normalized = HeatingSetupPayload.model_validate(draft.settings)
    canonical = _canonicalize(draft)
    canonical_payload = normalize_json(canonical.module_payload)
    assert isinstance(canonical_payload, dict)

    assert canonical_payload == normalized.model_dump(mode="json")
    assert canonical_payload["diagnostic_policy"] == {
        "diagnostic_profile": "debug",
        "configured_debug_duration_seconds": 1800.0,
        "debug_until_changed": True,
        "diagnostic_profile_before_debug": "basic",
    }
    assert canonical_payload["notification_policy"] == {
        "enabled": True,
        "recipients": [
            {
                "recipient_id": "family_phone",
                "transport": "home_assistant_notify",
                "target": "notify.family_phone",
                "enabled": True,
                "minimum_level": "detailed",
                "categories": ["runtime", "supervision"],
            }
        ],
        "maximum_per_window": 4,
        "rate_window_seconds": 120.0,
        "critical_maximum_per_window": 30,
        "critical_rate_window_seconds": 180.0,
        "history_capacity": 250,
    }


def test_existing_setup_drafts_materialize_current_new_entry_policy_defaults() -> None:
    settings = _settings()
    settings.pop("diagnostic_policy")
    settings.pop("notification_policy")

    payload = HeatingSetupPayload.model_validate(settings)
    dumped = payload.model_dump(mode="json")

    assert dumped["diagnostic_policy"] == {
        "diagnostic_profile": "basic",
        "configured_debug_duration_seconds": 3600.0,
        "debug_until_changed": False,
        "diagnostic_profile_before_debug": "detailed",
    }
    assert dumped["notification_policy"] == {
        "enabled": False,
        "recipients": [],
        "maximum_per_window": 10,
        "rate_window_seconds": 60.0,
        "critical_maximum_per_window": 20,
        "critical_rate_window_seconds": 60.0,
        "history_capacity": 100,
    }


def test_heating_schema_and_validator_policy_versions_identify_policy_contract() -> None:
    adapter = HeatingSetupAdapter()
    draft = complete_draft()
    report = adapter.validate(draft, report_id="versioned-policy-report", evaluated_at=NOW)

    assert POLICY_LESS_HEATING_SETUP_SCHEMA_VERSION == 1
    assert HEATING_SETUP_SCHEMA_VERSION == 2
    assert draft.module_schema_version == 2
    assert adapter.module_schema_version == 2
    assert adapter.validator_policy_version == 3
    assert report.validator_policy_version == 3


def test_canonicalization_rejects_outdated_validator_policy_report() -> None:
    adapter = HeatingSetupAdapter()
    draft = complete_draft()
    current = adapter.validate(draft, report_id="current-policy-report", evaluated_at=NOW)
    outdated_document = current.model_dump(mode="python")
    outdated_document["validator_policy_version"] = 2
    outdated = type(current).model_validate(outdated_document)

    with pytest.raises(ValueError, match="requires validator policy version 3"):
        adapter.canonicalize(
            draft,
            outdated,
            configuration_id="outdated-policy-configuration",
            revision_id="outdated-policy-revision",
            revision=1,
            provider="home_assistant",
            provider_instance_id="ha-home",
            created_at=NOW,
            actor="user:owner",
            source="setup_api",
            change_kind="CREATE",
            reason="outdated_policy_test",
            core_version="0.13.0",
            integration_version="0.13.0",
        )


@pytest.mark.parametrize("action", tuple(HeatingAction))
def test_timeout_action_accepts_current_runtime_domain(action: HeatingAction) -> None:
    settings = _settings()
    settings["indeterminate_timeout_action"] = action.value

    payload = HeatingSetupPayload.model_validate(settings)
    report = HeatingSetupAdapter().validate(_draft(settings), report_id=f"timeout-{action.value}", evaluated_at=NOW)

    assert payload.indeterminate_timeout_action is action
    assert payload.model_dump(mode="json")["indeterminate_timeout_action"] == action.value
    assert report.activation_ready is True


@pytest.mark.parametrize("action", ["hold", "unknown", "ENABLE_HEATING", ""])
def test_timeout_action_rejects_values_outside_current_runtime_domain(action: str) -> None:
    settings = _settings()
    settings["indeterminate_timeout_action"] = action

    report = HeatingSetupAdapter().validate(_draft(settings), report_id="invalid-timeout", evaluated_at=NOW)

    assert report.activation_ready is False
    assert "heating.invalid_setting" in {issue.code for issue in report.issues}


def test_simple_source_control_accepts_current_switch_service_contract() -> None:
    settings = _settings()
    settings.update(
        {
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
        }
    )

    report = HeatingSetupAdapter().validate(_draft(settings), report_id="simple-switch", evaluated_at=NOW)

    assert report.activation_ready is True


@pytest.mark.parametrize(
    ("setting", "domain", "service"),
    [
        ("source_enable", "vendor_boiler", "grant_heat_permission"),
        ("source_enable", "switch", "toggle"),
        ("source_disable", "script", "revoke_heat_permission"),
        ("source_disable", "switch", "turn_on"),
    ],
)
def test_simple_source_control_rejects_services_outside_current_switch_contract(
    setting: str,
    domain: str,
    service: str,
) -> None:
    settings = _settings()
    settings.update(
        {
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
        }
    )
    source_call = settings[setting]
    assert isinstance(source_call, dict)
    source_call.update({"domain": domain, "service": service})

    report = HeatingSetupAdapter().validate(_draft(settings), report_id="invalid-simple-source", evaluated_at=NOW)

    assert report.activation_ready is False
    assert "heating.invalid_setting" in {issue.code for issue in report.issues}


def test_policy_less_schema_v1_revision_imports_only_to_blocked_draft() -> None:
    current = _canonicalize(complete_draft())
    document = normalize_json(current.canonical_data())
    assert isinstance(document, dict)
    document.pop("document_hash")
    document.pop("semantic_configuration_fingerprint")
    document["module_schema_version"] = POLICY_LESS_HEATING_SETUP_SCHEMA_VERSION
    payload = document["module_payload"]
    assert isinstance(payload, dict)
    payload.pop("diagnostic_policy")
    payload.pop("notification_policy")
    old_revision = CanonicalConfigurationRevision.model_validate(document)
    repository = InMemorySetupRepository()
    imported = CanonicalConfigurationImporter(repository).import_to_draft(
        old_revision.canonical_json(),
        draft_id="policy-less-schema-v1",
        imported_at=NOW,
        target_environment_id="home",
    )

    adapter = HeatingSetupAdapter()
    report = adapter.validate(imported.draft, report_id="schema-v1-report", evaluated_at=NOW)
    issue = next(
        issue for issue in report.issues if issue.code == "heating.policy_less_schema_v1_requires_recanonicalization"
    )

    assert imported.activated is False
    assert imported.draft.module_schema_version == 1
    assert report.activation_ready is False
    assert "heating.invalid_setting" not in {item.code for item in report.issues}
    assert issue.parameters == {
        "actual_module_schema_version": 1,
        "required_module_schema_version": 2,
    }
    assert issue.suggested_action == "create_explicit_policy_bearing_schema_v2_draft"
    assert repository.get_active_reference(("home", "heating", "main-heating")) is None
    with pytest.raises(
        ValueError,
        match="policy-less Heating schema version 1 requires explicit migration or recanonicalization",
    ):
        adapter.canonicalize(
            imported.draft,
            report,
            configuration_id="schema-v1-configuration",
            revision_id="schema-v1-revision",
            revision=1,
            provider="home_assistant",
            provider_instance_id="ha-home",
            created_at=NOW,
            actor="system:migration",
            source="setup_import",
            change_kind="MIGRATE",
            reason="explicit_policy_upgrade_required",
            core_version="0.13.0",
            integration_version="0.13.0",
        )


def test_source_converter_must_materialize_legacy_detailed_profile_instead_of_using_canonical_default() -> None:
    default_settings = _settings()
    default_settings.pop("diagnostic_policy")
    explicit_legacy_settings = deepcopy(default_settings)
    explicit_legacy_settings["diagnostic_policy"] = {
        "diagnostic_profile": "detailed",
        "configured_debug_duration_seconds": 3600.0,
        "debug_until_changed": False,
        "diagnostic_profile_before_debug": "detailed",
    }

    canonical_default = _canonicalize(_draft(default_settings))
    explicit_legacy = _canonicalize(_draft(explicit_legacy_settings))
    canonical_default_payload = normalize_json(canonical_default.module_payload)
    explicit_legacy_payload = normalize_json(explicit_legacy.module_payload)
    assert isinstance(canonical_default_payload, dict)
    assert isinstance(explicit_legacy_payload, dict)
    canonical_default_diagnostic = canonical_default_payload["diagnostic_policy"]
    explicit_legacy_diagnostic = explicit_legacy_payload["diagnostic_policy"]
    assert isinstance(canonical_default_diagnostic, dict)
    assert isinstance(explicit_legacy_diagnostic, dict)

    assert canonical_default_diagnostic["diagnostic_profile"] == "basic"
    assert explicit_legacy_diagnostic["diagnostic_profile"] == "detailed"
    assert canonical_default.semantic_configuration_fingerprint != explicit_legacy.semantic_configuration_fingerprint


def test_reversing_recipient_order_changes_canonical_payload_and_semantic_fingerprint() -> None:
    forward_settings = _settings()
    notification = deepcopy(forward_settings["notification_policy"])
    assert isinstance(notification, dict)
    recipients = notification["recipients"]
    assert isinstance(recipients, list)
    recipients.append(
        {
            "recipient_id": "alarm_panel",
            "transport": "home_assistant_notify",
            "target": "notify.alarm_panel",
            "enabled": False,
            "minimum_level": "critical",
            "categories": ["safety", "runtime"],
        }
    )
    forward_settings["notification_policy"] = notification
    reverse_settings = deepcopy(forward_settings)
    reverse_notification = reverse_settings["notification_policy"]
    assert isinstance(reverse_notification, dict)
    reverse_recipients = reverse_notification["recipients"]
    assert isinstance(reverse_recipients, list)
    reverse_recipients.reverse()
    for recipient in reverse_recipients:
        assert isinstance(recipient, dict)
        categories = recipient["categories"]
        assert isinstance(categories, list)
        categories.reverse()

    forward = _canonicalize(_draft(forward_settings))
    reverse = _canonicalize(_draft(reverse_settings))

    forward_policy = normalize_json(forward.module_payload["notification_policy"])
    reverse_policy = normalize_json(reverse.module_payload["notification_policy"])
    assert isinstance(forward_policy, dict)
    assert isinstance(reverse_policy, dict)
    forward_recipients = forward_policy["recipients"]
    reverse_recipients = reverse_policy["recipients"]
    assert isinstance(forward_recipients, list)
    assert isinstance(reverse_recipients, list)
    assert [recipient["recipient_id"] for recipient in forward_recipients] == [
        "family_phone",
        "alarm_panel",
    ]
    assert [recipient["recipient_id"] for recipient in reverse_recipients] == [
        "alarm_panel",
        "family_phone",
    ]
    assert forward.module_payload != reverse.module_payload
    assert forward.semantic_configuration_fingerprint != reverse.semantic_configuration_fingerprint
    assert forward.canonical_json() != reverse.canonical_json()


def test_both_policies_are_behavior_affecting_semantic_fingerprint_content() -> None:
    baseline_settings = _settings()
    diagnostic_settings = deepcopy(baseline_settings)
    diagnostic_policy = diagnostic_settings["diagnostic_policy"]
    assert isinstance(diagnostic_policy, dict)
    diagnostic_policy["configured_debug_duration_seconds"] = 2400.0
    notification_settings = deepcopy(baseline_settings)
    notification_policy = notification_settings["notification_policy"]
    assert isinstance(notification_policy, dict)
    notification_policy["history_capacity"] = 251

    baseline = _canonicalize(_draft(baseline_settings))
    diagnostic_changed = _canonicalize(_draft(diagnostic_settings))
    notification_changed = _canonicalize(_draft(notification_settings))

    assert baseline.semantic_configuration_fingerprint != diagnostic_changed.semantic_configuration_fingerprint
    assert baseline.semantic_configuration_fingerprint != notification_changed.semantic_configuration_fingerprint
    assert baseline.module_payload["diagnostic_policy"] != diagnostic_changed.module_payload["diagnostic_policy"]
    assert baseline.module_payload["notification_policy"] != notification_changed.module_payload["notification_policy"]
