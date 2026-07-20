from controlel.application.events.event_bus import EventBus


def test_event_bus_registers_handler():
    bus = EventBus()

    called = False

    def handler(event):
        nonlocal called
        called = True

    bus.subscribe("test_event", handler)

    bus.publish({"event_type": "test_event"})

    assert called is True
