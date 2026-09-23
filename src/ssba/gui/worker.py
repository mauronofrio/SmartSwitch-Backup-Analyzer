"""Run engine work off the GUI thread."""

from __future__ import annotations

import logging
import traceback

from PySide6.QtCore import QThread, Signal

from ssba.core.progress import CancelToken, OperationCancelled

log = logging.getLogger("ssba.gui")


class Worker(QThread):
    """Runs ``job(progress, cancel)`` in a thread; results come back as signals."""

    progressed = Signal(object)  # ssba.core.progress.Progress
    succeeded = Signal(object)
    failed = Signal(str)  # traceback text
    cancelled = Signal()

    def __init__(self, job, parent=None) -> None:
        super().__init__(parent)
        self._job = job
        self.token = CancelToken()

    def run(self) -> None:
        try:
            result = self._job(self.progressed.emit, self.token)
        except OperationCancelled:
            log.info("cancelled by the user")
            self.cancelled.emit()
            return
        except Exception:  # shown to the user and logged, never lost
            details = traceback.format_exc()
            log.error("background job failed:\n%s", details)
            self.failed.emit(details)
            return
        self.succeeded.emit(result)
