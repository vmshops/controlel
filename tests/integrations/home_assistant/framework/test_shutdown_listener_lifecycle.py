"""Focused regressions for Home Assistant stop listener ownership."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STOP

from custom_components.controlel.host import _default_shutdown_subscriber

from .test_state_ingestion import RecordingRuntime, make_host, wait_until


@pytest.mark.asyncio
async def test_unload_before_home_assistant_stop_removes_listener_once(hass, caplog) -> None:
    runtime = RecordingRuntime()
    host = make_host(hass, runtime)
    await host.async_initialize()

    with caplog.at_level(logging.ERROR, logger="homeassistant.core"):
        await host.async_stop()
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await hass.async_block_till_done()

    assert host.stopped is True
    assert [operation for operation, _ in runtime.operations].count("stop") == 1
    assert "Unable to remove unknown job listener" not in caplog.text


@pytest.mark.asyncio
async def test_home_assistant_stop_then_later_cleanup_is_idempotent(hass, caplog) -> None:
    runtime = RecordingRuntime()
    host = make_host(hass, runtime)
    await host.async_initialize()

    with caplog.at_level(logging.ERROR, logger="homeassistant.core"):
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await wait_until(lambda: host.stopped)
        await host.async_stop()
        await hass.async_block_till_done()

    assert host.accepting is False
    assert host._executor.closed is True
    assert [operation for operation, _ in runtime.operations].count("stop") == 1
    assert "Unable to remove unknown job listener" not in caplog.text


@pytest.mark.asyncio
async def test_repeated_setup_unload_does_not_leave_stale_stop_listeners(hass, caplog) -> None:
    first = make_host(hass, RecordingRuntime())
    await first.async_initialize()
    await first.async_stop()

    second = make_host(hass, RecordingRuntime())
    await second.async_initialize()

    with caplog.at_level(logging.ERROR, logger="homeassistant.core"):
        await second.async_stop()
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await hass.async_block_till_done()

    assert first.stopped is True
    assert second.stopped is True
    assert "Unable to remove unknown job listener" not in caplog.text


@pytest.mark.asyncio
async def test_home_assistant_stop_invokes_host_stop_exactly_once(hass) -> None:
    runtime = RecordingRuntime()
    host = make_host(hass, runtime)
    await host.async_initialize()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await wait_until(lambda: host.stopped)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()

    assert [operation for operation, _ in runtime.operations].count("stop") == 1


@pytest.mark.asyncio
async def test_shutdown_subscriber_unsubscribe_after_fire_is_noop(hass, caplog) -> None:
    calls: list[str] = []

    def listener() -> None:
        calls.append("stop")

    unsubscribe = _default_shutdown_subscriber(hass, listener)

    with caplog.at_level(logging.ERROR, logger="homeassistant.core"):
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await hass.async_block_till_done()
        unsubscribe()
        unsubscribe()

    assert calls == ["stop"]
    assert "Unable to remove unknown job listener" not in caplog.text


@pytest.mark.asyncio
async def test_shutdown_subscriber_unsubscribe_before_fire_prevents_callback(hass) -> None:
    calls: list[str] = []
    unsubscribe = _default_shutdown_subscriber(hass, lambda: calls.append("stop"))
    unsubscribe()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert calls == []


def test_shutdown_subscriber_tracks_consumed_listener_without_bus_remove() -> None:
    """Pure ownership model: after fire, stored remove must not be invoked again."""

    remove_calls: list[str] = []
    callbacks: list[object] = []

    class FakeBus:
        def async_listen_once(self, _event_type: str, listener: object):
            callbacks.append(listener)

            def remove() -> None:
                remove_calls.append("remove")
                if listener not in callbacks:
                    raise ValueError("list.remove(x): x not in list")
                callbacks.remove(listener)

            return remove

    hass = MagicMock()
    hass.bus = FakeBus()
    fired: list[str] = []
    unsubscribe = _default_shutdown_subscriber(hass, lambda: fired.append("ok"))

    assert len(callbacks) == 1
    listener = callbacks[0]
    # Simulate HA one-time behavior: remove first, then call.
    callbacks.remove(listener)
    listener(None)
    unsubscribe()

    assert fired == ["ok"]
    assert remove_calls == []
