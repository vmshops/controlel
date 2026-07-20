class EventBus:
    def __init__(self):
        self._handlers = {}

    def subscribe(self, event_type, handler):
        if event_type not in self._handlers:
            self._handlers[event_type] = []

        self._handlers[event_type].append(handler)

    def publish(self, event):
        event_type = event["event_type"]

        handlers = self._handlers.get(event_type, [])

        for handler in handlers:
            handler(event)
