from datetime import UTC, datetime, timedelta, timezone
from threading import get_ident

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed_exact

from custom_components.controlel.event_loop_bridge import HomeAssistantEventLoopBridge
from custom_components.controlel.scheduler import HomeAssistantScheduler

from .test_state_ingestion import RecordingRuntime, make_host

NOW = datetime(2026, 7, 24, 10, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_real_ha_one_shot_timer_submits_late_callback_to_host_worker(hass) -> None:
    now = datetime.now(UTC)
    runtime = RecordingRuntime()
    host = make_host(hass, runtime)
    await host.async_initialize()
    loop_thread = get_ident()
    callback_threads: list[int] = []
    scheduler = HomeAssistantScheduler(
        hass=hass,
        bridge=HomeAssistantEventLoopBridge(hass.loop),
        submit_runtime_callback=host.submit_scheduled_callback,
    )
    non_utc_deadline = (now + timedelta(minutes=1)).astimezone(timezone(timedelta(hours=2)))

    await host._executor.async_submit(
        scheduler.schedule_at,
        non_utc_deadline,
        lambda: callback_threads.append(get_ident()),
    )
    async_fire_time_changed_exact(hass, now + timedelta(minutes=1, seconds=5))
    await hass.async_block_till_done()

    assert len(callback_threads) == 1
    assert callback_threads[0] != loop_thread
    assert callback_threads[0] == runtime.threads[0]

    async_fire_time_changed_exact(hass, now + timedelta(minutes=2))
    await hass.async_block_till_done()
    assert len(callback_threads) == 1
    await host.async_stop()


@pytest.mark.asyncio
async def test_real_ha_timer_cancellation_prevents_execution(hass) -> None:
    now = datetime.now(UTC)
    runtime = RecordingRuntime()
    host = make_host(hass, runtime)
    await host.async_initialize()
    callbacks: list[None] = []
    scheduler = HomeAssistantScheduler(
        hass=hass,
        bridge=HomeAssistantEventLoopBridge(hass.loop),
        submit_runtime_callback=host.submit_scheduled_callback,
    )
    handle = await host._executor.async_submit(
        scheduler.schedule_at,
        now + timedelta(minutes=1),
        lambda: callbacks.append(None),
    )

    await host._executor.async_submit(handle.cancel)
    await host._executor.async_submit(handle.cancel)
    async_fire_time_changed_exact(hass, now + timedelta(minutes=2))
    await hass.async_block_till_done()

    assert callbacks == []
    await host.async_stop()


@pytest.mark.asyncio
async def test_real_timer_callback_after_unload_is_rejected_by_host(hass) -> None:
    now = datetime.now(UTC)
    runtime = RecordingRuntime()
    host = make_host(hass, runtime)
    await host.async_initialize()
    callbacks: list[None] = []
    scheduler = HomeAssistantScheduler(
        hass=hass,
        bridge=HomeAssistantEventLoopBridge(hass.loop),
        submit_runtime_callback=host.submit_scheduled_callback,
    )
    await host._executor.async_submit(
        scheduler.schedule_at,
        now + timedelta(minutes=1),
        lambda: callbacks.append(None),
    )

    await host.async_stop()
    async_fire_time_changed_exact(hass, now + timedelta(minutes=2))
    await hass.async_block_till_done()

    assert callbacks == []


@pytest.mark.asyncio
async def test_scheduler_rejects_naive_deadline_before_installing_real_timer(hass) -> None:
    runtime = RecordingRuntime()
    host = make_host(hass, runtime)
    await host.async_initialize()
    scheduler = HomeAssistantScheduler(
        hass=hass,
        bridge=HomeAssistantEventLoopBridge(hass.loop),
        submit_runtime_callback=host.submit_scheduled_callback,
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        await host._executor.async_submit(
            scheduler.schedule_at,
            NOW.replace(tzinfo=None),
            lambda: None,
        )

    await host.async_stop()
