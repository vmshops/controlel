"""Canonical Heating diagnostics and notification policy contracts."""

from __future__ import annotations

from copy import deepcopy
from math import inf, nan

import pytest
from pydantic import ValidationError

from controlel.application.configuration.heating_setup_adapter import (
    HeatingDiagnosticPolicy,
    HeatingNotificationPolicy,
    HeatingNotificationRecipient,
    HeatingSetupAdapter,
    HeatingSetupPayload,
)
from controlel.application.setup import CanonicalConfigurationRevision, DraftRevision
from controlel.application.setup.json_data import normalize_json

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


def test_recipient_order_is_canonical_category_sets_normalize_and_duplicate_recipients_fail() -> None:
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

    assert forward == reverse
    assert tuple(recipient.recipient_id for recipient in forward.recipients) == ("family_phone", "wall_panel")
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
    payload = HeatingSetupPayload.model_validate(_settings())
    serialized = payload.model_dump_json()
    reconstructed = HeatingSetupPayload.model_validate_json(serialized)

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
    assert reconstructed.notification_policy.recipients[0].target == "notify.family_phone"


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


def test_canonicalization_and_fingerprint_are_independent_of_policy_input_order() -> None:
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

    assert forward.module_payload == reverse.module_payload
    assert forward.semantic_configuration_fingerprint == reverse.semantic_configuration_fingerprint
    assert forward.canonical_json() == reverse.canonical_json()


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
