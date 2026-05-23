from __future__ import annotations

from collections import defaultdict
from typing import Callable, Type


class EventBus:
    """Simple synchronous in-process event dispatcher."""

    def __init__(self) -> None:
        self._handlers: dict[Type, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: Type, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: Type, handler: Callable) -> None:
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def publish(self, event: object) -> None:
        for handler in list(self._handlers[type(event)]):
            handler(event)

    def publish_all(self, events: list) -> None:
        for event in events:
            self.publish(event)
