from __future__ import annotations

from collections.abc import Callable

from domain.download.events import DownloadCompleted, DownloadFailed, DownloadProgressUpdated
from infrastructure.event_bus import EventBus


class DownloadEventBridge:
    """Subscribes to domain events and exposes application-level callbacks.

    Lives in the application layer so gui/ never needs to import domain events.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._progress_cbs: list[Callable[[], None]] = []
        self._completed_cbs: list[Callable[[], None]] = []
        self._failed_cbs: list[Callable[[str], None]] = []

        event_bus.subscribe(DownloadProgressUpdated, self._on_progress)
        event_bus.subscribe(DownloadCompleted, self._on_completed)
        event_bus.subscribe(DownloadFailed, self._on_failed)

    def add_progress_listener(self, cb: Callable[[], None]) -> None:
        self._progress_cbs.append(cb)

    def add_completed_listener(self, cb: Callable[[], None]) -> None:
        self._completed_cbs.append(cb)

    def add_failed_listener(self, cb: Callable[[str], None]) -> None:
        self._failed_cbs.append(cb)

    def _on_progress(self, event: DownloadProgressUpdated) -> None:
        for cb in self._progress_cbs:
            cb()

    def _on_completed(self, event: DownloadCompleted) -> None:
        for cb in self._completed_cbs:
            cb()

    def _on_failed(self, event: DownloadFailed) -> None:
        for cb in self._failed_cbs:
            cb(event.error)
