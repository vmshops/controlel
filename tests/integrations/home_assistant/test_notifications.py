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


def _policy(*, second: bool = False, disabled: bool = False) -> NotificationPolicy:
    recipients = [
        NotificationRecipient(
            "phone",
            "home_assistant_notify",
            "notify.phone",
            enabled=not disabled,
            minimum_level=NotificationLevel.DEBUG,
        )
    ]
    if second:
        recipients.append(
            NotificationRecipient(
                "tablet",
                "home_assistant_notify",
                "notify.tablet",
                minimum_level=NotificationLevel.DEBUG,
            )
        )
    return NotificationPolicy(enabled=True, recipients=tuple(recipients))


def _emit(stream: OperationalEventStream, code: OperationalEventCode, *, correlation: str | None = None) -> None:
    stream.emit(
        timestamp=NOW,
        category=OperationalEventCategory.RUNTIME,
        severity=OperationalEventSeverity.INFO,
        event_code=code,
        correlation_id=correlation,
    )


def test_configured_notify_services_are_called_independently() -> None:
    async def scenario():
        stream = OperationalEventStream()
        _emit(stream, OperationalEventCode.RUNTIME_RECOVERED)
        services = Services()
        policy = _policy(second=True)
        coordinator = HomeAssistantNotificationCoordinator(
            policy,
            stream.snapshot,
            HomeAssistantNotificationTransport(Hass(services), policy),
            logging.getLogger(__name__),
        )
        await coordinator.async_process_new_events()
        return services.calls, coordinator.diagnostics()

    calls, diagnostics = asyncio.run(scenario())
    assert [(call[0], call[1], call[3]) for call in calls] == [
        ("notify", "phone", True),
        ("notify", "tablet", True),
    ]
    assert all(call[2]["message"] == "notification_message_runtime_recovered" for call in calls)
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
        _emit(stream, OperationalEventCode.RUNTIME_FATAL)
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
        _emit(stream, OperationalEventCode.RUNTIME_RECOVERED, correlation="campaign:1")
        await coordinator.async_process_new_events()
        _emit(stream, OperationalEventCode.RUNTIME_FATAL, correlation="campaign:1")
        await coordinator.async_process_new_events()
        return coordinator.diagnostics()

    diagnostics = asyncio.run(scenario())
    assert diagnostics["counters"]["failed"] == 2
    assert diagnostics["counters"]["delivered"] == 2
    assert "arbitrary transport detail" not in str(diagnostics)


def test_close_invalidates_queued_delivery() -> None:
    async def scenario():
        stream = OperationalEventStream()
        _emit(stream, OperationalEventCode.RUNTIME_FATAL)
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
    _emit(stream, OperationalEventCode.RUNTIME_FATAL)
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
