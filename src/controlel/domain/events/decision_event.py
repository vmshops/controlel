from controlel.domain.decisions.decision import Decision
from controlel.domain.events.event import Event


class DecisionCreatedEvent(Event):
    """
    Event raised when a new decision is created.
    """

    event_type: str = "decision_created"

    decision: Decision
