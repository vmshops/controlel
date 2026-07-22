class EventBus:
    def __init__(self):
        self._handlers = {}

    def subscribe(self, event_type, handler):
        self._handlers.setdefault(event_type, [])
        self._handlers[event_type].append(handler)

    def publish(self, event) -> None:
        if isinstance(event, dict):
            event_type = event.get("event_type")
        else:
            event_type = type(event)

        handlers = self._handlers.get(event_type, [])

        for handler in handlers:
            handler(event)
