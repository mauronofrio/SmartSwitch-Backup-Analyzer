"""Optional progress reporting and cancellation for long engine operations.

Every engine function that accepts ``progress`` and ``cancel`` works exactly
as before when they are omitted. ``cancel`` is only checked between items, so
whatever was written before a cancellation stays valid.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Progress:
    stage: str  # "scan", "files", "notes", "export"
    done: int
    total: int | None
    item: str = ""


ProgressFn = Callable[[Progress], None]


class OperationCancelled(Exception):
    """Raised when the user cancelled; work done so far stays valid."""


class CancelToken:
    """Thread-safe cancellation flag, set from the GUI thread."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise OperationCancelled("operation cancelled")


def emit(progress: ProgressFn | None, stage: str, done: int, total: int | None, item: str = "") -> None:
    if progress is not None:
        progress(Progress(stage, done, total, item))


def check_cancel(cancel: CancelToken | None) -> None:
    if cancel is not None:
        cancel.check()
