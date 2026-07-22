import pytest

from controlel.application.events.event_bus import EventBus


def test_publish_returns_none_without_subscribers():
    bus = EventBus()

    result = bus.publish({"event_type": "test_event"})

    assert result is None


def test_dictionary_event_notifies_all_subscribers_in_registration_order():
    bus = EventBus()
    calls = []

    def first_handler(event):
        calls.append(("first", event))
        return "first result"

    def second_handler(event):
        calls.append(("second", event))
        return "second result"

    event = {"event_type": "test_event"}
    bus.subscribe("test_event", first_handler)
    bus.subscribe("test_event", second_handler)

    result = bus.publish(event)

    assert result is None
    assert calls == [("first", event), ("second", event)]


def test_subscriber_exception_propagates_unchanged():
    bus = EventBus()
    error = RuntimeError("observer failed")

    def failing_handler(event):
        raise error

    bus.subscribe("test_event", failing_handler)

    with pytest.raises(RuntimeError) as raised:
        bus.publish({"event_type": "test_event"})

    assert raised.value is error
