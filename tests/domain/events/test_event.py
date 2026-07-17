from controlel.domain.events.event import Event


def test_event_creation():
    event = Event(event_type="test_event")

    assert event.event_type == "test_event"
    assert event.id is not None
    assert event.created_at is not None
