"""
Minimal thread-safe signal used by the service layer.

Replaces PyQt5's pyqtSignal so the pywebview app does not need to load Qt.
Slots run synchronously on the emitting thread.
"""

import threading
from typing import Callable, List

from .logger import setup_logger

logger = setup_logger(__name__)


class Signal:
    """Connect callables and call them all on emit()."""

    def __init__(self):
        self._slots: List[Callable] = []
        self._lock = threading.Lock()

    def connect(self, slot: Callable):
        with self._lock:
            self._slots.append(slot)

    def disconnect(self, slot: Callable):
        with self._lock:
            self._slots.remove(slot)

    def emit(self, *args):
        with self._lock:
            slots = list(self._slots)
        for slot in slots:
            try:
                slot(*args)
            except Exception:
                logger.exception("Signal slot %r raised", slot)
