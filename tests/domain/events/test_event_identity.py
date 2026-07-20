from uuid import UUID

from controlel.domain.events.event import Event


def test_event_contains_id():
    event = Event(
        event_type="test_event",
    )

    assert isinstance(event.event_id, UUID)
