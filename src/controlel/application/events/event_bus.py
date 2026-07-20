class EventBus:
    def __init__(self):
        self._handlers = {}

    def subscribe(self, event_type, handler):
        if event_type not in self._handlers:
            self._handlers[event_type] = []

        self._handlers[event_type].append(handler)

    def publish(self, event):
        if isinstance(event, dict):
            event_type = event.get("event_type")
        else:
            event_type = type(event)

        handlers = self._handlers.get(event_type, [])

        results = []

        for handler in handlers:
            results.append(handler(event))

        if len(results) == 1:
            return results[0]

        return results
