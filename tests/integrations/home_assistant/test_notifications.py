"""Tests for the isolated Home Assistant notification transport boundary."""

import asyncio
import logging
from datetime import UTC, datetime

from controlel.application.services.operational_event_stream import OperationalEventStream
from controlel.domain.notifications import NotificationLevel, NotificationPolicy, NotificationRecipient
from controlel.domain.operational_events import (
    OperationalEventCategory,
    OperationalEventCode,
    OperationalEventSeverity,
)
from controlel.domain.user_activities import UserActivityType
from custom_components.controlel.notification_renderer import HomeAssistantNotificationRenderer
from custom_components.controlel.notifications import (
    HomeAssistantNotificationCoordinator,
    HomeAssistantNotificationTransport,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class Services:
    def __init__(self, *, fail_service: str | None = None) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.fail_service = fail_service

    async def async_call(self, domain, service, data, *, blocking):
        self.calls.append((domain, service, data, blocking))
        if service == self.fail_service:
            raise RuntimeError("arbitrary transport detail must not escape")


class Hass:
    def __init__(self, services: Services) -> None:
        self.services = services


def _policy(
    *,
    second: bool = False,
    disabled: bool = False,
    minimum_level: NotificationLevel = NotificationLevel.DEBUG,
) -> NotificationPolicy:
    recipients = [
        NotificationRecipient(
            "phone",
            "home_assistant_notify",
            "notify.phone",
            enabled=not disabled,
            minimum_level=minimum_level,
        )
    ]
    if second:
        recipients.append(
            NotificationRecipient(
                "tablet",
                "home_assistant_notify",
                "notify.tablet",
                minimum_level=minimum_level,
            )
        )
    return NotificationPolicy(enabled=True, recipients=tuple(recipients))


def _emit(
    stream: OperationalEventStream,
    code: OperationalEventCode,
    *,
    activity_id: str | None = None,
    category: OperationalEventCategory = OperationalEventCategory.RUNTIME,
    requested_command: str | None = None,
    command_outcome: str | None = None,
    new_state: str | None = None,
    details: tuple[tuple[str, object], ...] = (),
) -> None:
    stream.emit(
        timestamp=NOW,
        category=category,
        severity=OperationalEventSeverity.INFO,
        event_code=code,
        activity_id=activity_id,
        zone_id="living_room",
        source_id="heat_source",
        requested_command=requested_command,
        command_outcome=command_outcome,
        new_state=new_state,
        details=details,
    )


def _renderer(hass: object) -> HomeAssistantNotificationRenderer:
    async def translations(_language: str) -> dict[str, str]:
        return {f"notification_title_{item.value}": f"Human title for {item.value}" for item in UserActivityType} | {
            f"notification_message_{item.value}": f"Human message for {item.value}" for item in UserActivityType
        }

    return HomeAssistantNotificationRenderer(hass, translations)


def test_configured_notify_services_are_called_independently() -> None:
    async def scenario():
        stream = OperationalEventStream()
        _emit(stream, OperationalEventCode.FAILSAFE_ENTERED, activity_id="supervision:1")
        services = Services()
        hass = Hass(services)
        policy = _policy(second=True)
        coordinator = HomeAssistantNotificationCoordinator(
            policy,
            stream.snapshot,
            HomeAssistantNotificationTransport(hass, policy, renderer=_renderer(hass)),
            logging.getLogger(__name__),
        )
        await coordinator.async_process_new_events()
        return services.calls, coordinator.diagnostics()

    calls, diagnostics = asyncio.run(scenario())
    assert [(call[0], call[1], call[3]) for call in calls] == [
        ("notify", "phone", True),
        ("notify", "tablet", True),
    ]
    assert all(call[2]["message"] == "Human message for runtime_failsafe_entered" for call in calls)
    assert all(not call[2]["title"].startswith("notification_title_") for call in calls)
    assert all(not call[2]["message"].startswith("notification_message_") for call in calls)
    assert diagnostics["counters"]["delivered"] == 2
    assert diagnostics["source_total_observed"] == 1
    assert diagnostics["source_last_processed_sequence"] == 1
    assert diagnostics["source_events_missed"] == 0
    assert diagnostics["source_overflow_occurrences"] == 0
    assert diagnostics["recipients"][0]["target_configured"] is True
    assert "notify.phone" not in str(diagnostics)


def test_disabled_or_absent_recipient_never_calls_ha() -> None:
    async def scenario():
        stream = OperationalEventStream()
        _emit(
            stream,
            OperationalEventCode.MEASUREMENT_BECAME_STALE,
            activity_id="measurement-incident:1",
            category=OperationalEventCategory.MEASUREMENT,
        )
        services = Services()
        policy = _policy(disabled=True)
        coordinator = HomeAssistantNotificationCoordinator(
            policy,
            stream.snapshot,
            HomeAssistantNotificationTransport(Hass(services), policy),
            logging.getLogger(__name__),
        )
        await coordinator.async_process_new_events()
        return services.calls, coordinator.diagnostics()

    calls, diagnostics = asyncio.run(scenario())
    assert calls == []
    assert diagnostics["counters"]["no_recipient"] == 1


def test_service_failure_is_normalized_and_does_not_block_later_events() -> None:
    async def scenario():
        stream = OperationalEventStream()
        services = Services(fail_service="phone")
        policy = _policy(second=True)
        coordinator = HomeAssistantNotificationCoordinator(
            policy,
            stream.snapshot,
            HomeAssistantNotificationTransport(Hass(services), policy),
            logging.getLogger(__name__),
        )
        _emit(
            stream,
            OperationalEventCode.MEASUREMENT_BECAME_STALE,
            activity_id="measurement-incident:1",
            category=OperationalEventCategory.MEASUREMENT,
        )
        await coordinator.async_process_new_events()
        _emit(
            stream,
            OperationalEventCode.MEASUREMENT_RECOVERED,
            activity_id="measurement-incident:1",
            category=OperationalEventCategory.MEASUREMENT,
            new_state="valid",
        )
        await coordinator.async_process_new_events()
        return coordinator.diagnostics()

    diagnostics = asyncio.run(scenario())
    assert diagnostics["counters"]["failed"] == 2
    assert diagnostics["counters"]["delivered"] == 2
    assert "arbitrary transport detail" not in str(diagnostics)


def test_close_invalidates_queued_delivery() -> None:
    async def scenario():
        stream = OperationalEventStream()
        _emit(
            stream,
            OperationalEventCode.MEASUREMENT_BECAME_STALE,
            activity_id="measurement-incident:1",
            category=OperationalEventCategory.MEASUREMENT,
        )
        services = Services()
        policy = _policy()
        coordinator = HomeAssistantNotificationCoordinator(
            policy,
            stream.snapshot,
            HomeAssistantNotificationTransport(Hass(services), policy),
            logging.getLogger(__name__),
        )
        coordinator.close()
        await coordinator.async_process_new_events()
        return services.calls, coordinator.diagnostics()

    calls, diagnostics = asyncio.run(scenario())
    assert calls == []
    assert diagnostics["total_intents_produced"] == 0


def test_diagnostics_refresh_does_not_create_notification_traffic() -> None:
    stream = OperationalEventStream()
    _emit(
        stream,
        OperationalEventCode.MEASUREMENT_BECAME_STALE,
        activity_id="measurement-incident:1",
        category=OperationalEventCategory.MEASUREMENT,
    )
    services = Services()
    policy = _policy()
    coordinator = HomeAssistantNotificationCoordinator(
        policy,
        stream.snapshot,
        HomeAssistantNotificationTransport(Hass(services), policy),
        logging.getLogger(__name__),
    )

    diagnostics = coordinator.diagnostics()

    assert services.calls == []
    assert diagnostics["source_total_observed"] == 0
    assert diagnostics["total_intents_produced"] == 0


def test_renderer_fallback_still_delivers_without_exposing_raw_codes() -> None:
    async def failing(_language: str) -> dict[str, str]:
        raise RuntimeError("renderer secret must not escape")

    async def scenario():
        stream = OperationalEventStream()
        _emit(
            stream,
            OperationalEventCode.MEASUREMENT_BECAME_STALE,
            activity_id="measurement-incident:1",
            category=OperationalEventCategory.MEASUREMENT,
        )
        services = Services()
        hass = Hass(services)
        policy = _policy()
        renderer = HomeAssistantNotificationRenderer(hass, failing)
        coordinator = HomeAssistantNotificationCoordinator(
            policy,
            stream.snapshot,
            HomeAssistantNotificationTransport(hass, policy, renderer=renderer),
            logging.getLogger(__name__),
        )
        await coordinator.async_process_new_events()
        return services.calls, coordinator.diagnostics()

    calls, diagnostics = asyncio.run(scenario())
    payload = calls[0][2]
    assert payload["title"] == "Controlel notification"
    assert payload["message"] == "Controlel generated an operational notification."
    assert payload["data"]["renderer_fallback_code"] == "notification_render_failed"
    assert "notification_title_" not in str(payload)
    assert "notification_message_" not in str(payload)
    assert "renderer secret" not in str(payload)
    assert diagnostics["counters"]["delivered"] == 1


def test_real_world_source_correction_keeps_selection_counts_and_cursor_unchanged() -> None:
    async def scenario():
        stream = OperationalEventStream()
        lifecycle = "source-reconciliation:1"
        _emit(stream, OperationalEventCode.REPORTED_SOURCE_STATE_CHANGED, activity_id=lifecycle)
        _emit(
            stream,
            OperationalEventCode.SOURCE_DRIFT_DETECTED,
            activity_id=lifecycle,
            details=(("api_token", "must-not-leak"), ("desired_state", "disabled")),
        )
        _emit(stream, OperationalEventCode.SOURCE_RECONCILIATION_STARTED, activity_id=lifecycle)
        _emit(
            stream,
            OperationalEventCode.SOURCE_COMMAND_DEFERRED_MINIMUM_ON,
            activity_id=lifecycle,
            requested_command="disable_heating",
            command_outcome="deferred",
        )
        _emit(stream, OperationalEventCode.SOURCE_DISABLE_REQUESTED, activity_id=lifecycle)
        _emit(
            stream,
            OperationalEventCode.SOURCE_COMMAND_DISPATCHED,
            activity_id=lifecycle,
            requested_command="disable_heating",
            command_outcome="dispatched",
        )
        _emit(stream, OperationalEventCode.CORRECTIVE_ACTION_DISPATCHED, activity_id=lifecycle)
        _emit(
            stream,
            OperationalEventCode.REPORTED_SOURCE_STATE_CHANGED,
            activity_id=lifecycle,
            new_state="disabled",
        )
        _emit(
            stream,
            OperationalEventCode.SOURCE_RECONCILIATION_COMPLETED,
            activity_id=lifecycle,
            details=(("completion_outcome", "reported_agreement"),),
        )
        services = Services()
        hass = Hass(services)
        policy = _policy(minimum_level=NotificationLevel.OPERATIONAL)
        coordinator = HomeAssistantNotificationCoordinator(
            policy,
            stream.snapshot,
            HomeAssistantNotificationTransport(hass, policy, renderer=_renderer(hass)),
            logging.getLogger(__name__),
        )
        await coordinator.async_process_new_events()
        return services.calls, coordinator.diagnostics(), coordinator.activity_diagnostics()

    calls, diagnostics, activities = asyncio.run(scenario())
    assert len(calls) == 1
    assert calls[0][2]["data"]["source_activity_id"] == "source-reconciliation:1/source_state_corrected"
    assert calls[0][2]["data"]["activity_type"] == "source_state_corrected"
    assert "source_event_id" not in calls[0][2]["data"]
    assert calls[0][2]["title"] == "Human title for source_state_corrected"
    assert calls[0][2]["message"] == "Human message for source_state_corrected"
    assert calls[0][2]["data"]["parameters"]["activity_parameter_desired_state"] == "disabled"
    assert "api_token" not in str(calls)
    assert "must-not-leak" not in str(calls)
    assert diagnostics["source_total_observed"] == 1
    assert diagnostics["source_last_processed_sequence"] == 1
    assert diagnostics["source_events_missed"] == 0
    assert diagnostics["source_overflow_occurrences"] == 0
    assert diagnostics["total_intents_produced"] == 1
    assert diagnostics["counters"] == {
        "delivered": 1,
        "failed": 0,
        "no_recipient": 0,
        "rate_limited": 0,
        "suppressed_duplicate": 0,
        "suppressed_policy": 0,
    }
    assert activities["schema_version"] == 2
    assert activities["source_total_observed"] == 9
    assert activities["source_last_processed_sequence"] == 9
    assert activities["activities"][0]["activity_type"] == "source_state_corrected"
    assert activities["activities"][0]["parameters"]["desired_state"] == "disabled"
    assert "api_token" not in str(activities)
    assert "must-not-leak" not in str(activities)


def test_measurement_grace_composes_degraded_and_recovered_without_grace_noise() -> None:
    async def scenario():
        stream = OperationalEventStream()
        services = Services()
        hass = Hass(services)
        policy = _policy(minimum_level=NotificationLevel.OPERATIONAL)
        coordinator = HomeAssistantNotificationCoordinator(
            policy,
            stream.snapshot,
            HomeAssistantNotificationTransport(hass, policy, renderer=_renderer(hass)),
            logging.getLogger(__name__),
        )
        lifecycle = "measurement-incident:1"
        _emit(
            stream,
            OperationalEventCode.MEASUREMENT_BECAME_UNAVAILABLE,
            activity_id=lifecycle,
            category=OperationalEventCategory.MEASUREMENT,
            new_state="unavailable",
        )
        _emit(
            stream,
            OperationalEventCode.SAFETY_GRACE_STARTED,
            activity_id=lifecycle,
            category=OperationalEventCategory.SAFETY,
        )
        await coordinator.async_process_new_events()
        _emit(
            stream,
            OperationalEventCode.MEASUREMENT_RECOVERED,
            activity_id=lifecycle,
            category=OperationalEventCategory.MEASUREMENT,
            new_state="valid",
        )
        await coordinator.async_process_new_events()
        return services.calls

    calls = asyncio.run(scenario())
    assert [call[2]["data"]["activity_type"] for call in calls] == [
        "measurement_degraded",
        "measurement_recovered",
    ]
    assert "safety_grace" not in str(calls)


def test_detailed_heating_start_stop_are_not_sent_to_operational_recipient() -> None:
    async def scenario(minimum_level: NotificationLevel):
        stream = OperationalEventStream()
        services = Services()
        hass = Hass(services)
        policy = _policy(minimum_level=minimum_level)
        coordinator = HomeAssistantNotificationCoordinator(
            policy,
            stream.snapshot,
            HomeAssistantNotificationTransport(hass, policy, renderer=_renderer(hass)),
            logging.getLogger(__name__),
        )
        episode = "heating-episode:1"
        _emit(
            stream,
            OperationalEventCode.HEAT_DEMAND_CONFIRMED,
            activity_id=episode,
            category=OperationalEventCategory.DEMAND,
        )
        _emit(
            stream,
            OperationalEventCode.SOURCE_COMMAND_DISPATCHED,
            activity_id=episode,
            category=OperationalEventCategory.SOURCE_CONTROL,
            requested_command="enable_heating",
            command_outcome="dispatched",
        )
        await coordinator.async_process_new_events()
        _emit(
            stream,
            OperationalEventCode.SOURCE_COMMAND_DISPATCHED,
            activity_id=episode,
            category=OperationalEventCategory.SOURCE_CONTROL,
            requested_command="disable_heating",
            command_outcome="dispatched",
        )
        await coordinator.async_process_new_events()
        return services.calls

    detailed = asyncio.run(scenario(NotificationLevel.DETAILED))
    operational = asyncio.run(scenario(NotificationLevel.OPERATIONAL))
    assert [call[2]["data"]["activity_type"] for call in detailed] == ["heating_started", "heating_stopped"]
    assert operational == []
    assert "burner" not in str(detailed).casefold()
