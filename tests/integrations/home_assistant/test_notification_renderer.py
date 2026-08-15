"""Tests for localized, fail-safe Home Assistant notification rendering."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from controlel.domain.notifications import (
    NotificationIntent,
    NotificationLevel,
    NotificationParameter,
)
from controlel.domain.operational_events import OperationalEventCategory
from controlel.domain.user_activities import UserActivityType
from custom_components.controlel.notification_renderer import (
    FALLBACK_MESSAGE,
    FALLBACK_TITLE,
    HomeAssistantNotificationRenderer,
)

COMPONENT = Path(__file__).parents[3] / "custom_components" / "controlel"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _intent(
    *,
    title_code: str = "notification_title_source_state_corrected",
    message_code: str = "notification_message_source_state_corrected",
    parameters: tuple[NotificationParameter, ...] = (),
) -> NotificationIntent:
    return NotificationIntent(
        "notification:00000001",
        NOW,
        NotificationLevel.OPERATIONAL,
        OperationalEventCategory.SOURCE_RESILIENCE,
        title_code,
        message_code,
        "activity:00000001",
        UserActivityType.SOURCE_STATE_CORRECTED,
        "phone",
        correlation_id="source-reconciliation:00000001",
        zone_ids=("living_room",),
        source_ids=("heat_source",),
        parameters=parameters,
    )


def _catalog(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))["common"]


def test_every_reachable_notification_code_has_matching_english_translation() -> None:
    source = _catalog(COMPONENT / "strings.json")
    english = _catalog(COMPONENT / "translations" / "en.json")
    expected = {f"notification_{kind}_{item.value}" for item in UserActivityType for kind in ("title", "message")}

    assert set(source) == expected
    assert english == source
    assert all(value.strip() and "notification_" not in value for value in english.values())


def test_renderer_returns_human_text_and_interpolates_only_safe_scalars() -> None:
    async def translations(_language: str) -> dict[str, str]:
        return {
            "notification_title_source_state_corrected": "Correction for {source_ids}",
            "notification_message_source_state_corrected": (
                "Requested {requested_action}; outcome {command_outcome}; zones {zone_ids}; "
                "deadline {activity_parameter_deadline}; ignored {secret}; missing {activity_parameter_attempt}."
            ),
        }

    parameters = (
        NotificationParameter("activity_parameter_deadline", "2026-01-01T00:10:00+00:00"),
        NotificationParameter("command_outcome", "dispatched"),
        NotificationParameter("requested_action", "disable_heating"),
        NotificationParameter("secret", "must-not-leak"),
    )
    rendered = asyncio.run(
        HomeAssistantNotificationRenderer(object(), translations).async_render(_intent(parameters=parameters))
    )

    assert rendered.title == "Correction for heat_source"
    assert rendered.message == (
        "Requested disable_heating; outcome dispatched; zones living_room; "
        "deadline 2026-01-01T00:10:00+00:00; ignored unknown; missing unknown."
    )
    assert "must-not-leak" not in rendered.message
    assert rendered.fallback_code is None


def test_nested_or_untrusted_parameter_values_are_not_rendered() -> None:
    async def translations(_language: str) -> dict[str, str]:
        return {
            "notification_title_source_state_corrected": "Correction",
            "notification_message_source_state_corrected": "Outcome: {command_outcome}",
        }

    intent = _intent(parameters=(NotificationParameter("command_outcome", "safe"),))
    object.__setattr__(intent.parameters[0], "value", {"token": "must-not-leak"})

    rendered = asyncio.run(HomeAssistantNotificationRenderer(object(), translations).async_render(intent))

    assert rendered.message == "Outcome: unknown"
    assert "must-not-leak" not in rendered.message


def test_missing_translation_and_renderer_exception_use_generic_fallback() -> None:
    async def missing(_language: str) -> dict[str, str]:
        return {}

    async def failing(_language: str) -> dict[str, str]:
        raise RuntimeError("arbitrary renderer detail must not escape")

    missing_result = asyncio.run(HomeAssistantNotificationRenderer(object(), missing).async_render(_intent()))
    failed_result = asyncio.run(HomeAssistantNotificationRenderer(object(), failing).async_render(_intent()))

    assert (missing_result.title, missing_result.message, missing_result.fallback_code) == (
        FALLBACK_TITLE,
        FALLBACK_MESSAGE,
        "notification_translation_missing",
    )
    assert (failed_result.title, failed_result.message, failed_result.fallback_code) == (
        FALLBACK_TITLE,
        FALLBACK_MESSAGE,
        "notification_render_failed",
    )
    assert "notification_title_" not in str((missing_result, failed_result))
    assert "arbitrary renderer detail" not in str((missing_result, failed_result))
