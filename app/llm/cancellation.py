"""Thread-safe cancellation independent of desktop configuration."""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


def _close_resource(resource: Any) -> None:
    close = getattr(resource, 'close', None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.debug('Unable to close resource', exc_info=True)


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._resources: list[Any] = []

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            resources = list(self._resources)
        for resource in resources:
            _close_resource(resource)

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(max(0.0, timeout))

    def add_resource(self, resource: Any) -> None:
        if resource is None:
            return
        with self._lock:
            if not self._event.is_set():
                self._resources.append(resource)
                return
        _close_resource(resource)

    def remove_resource(self, resource: Any) -> None:
        with self._lock:
            if resource in self._resources:
                self._resources.remove(resource)
