class EventBus:
    """
    Simple in-memory event bus.
    """

    def __init__(self):
        self._handlers = {}

    def subscribe(self, event_type, handler):
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event):
        if isinstance(event, dict):
            event_type = event.get("event_type")
        else:
            event_type = type(event)

        for handler in self._handlers.get(event_type, []):
            handler(event)
