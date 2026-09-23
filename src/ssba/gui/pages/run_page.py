"""Page 4: run the ticked exports in the background, one row each."""

from __future__ import annotations

import functools
import logging

from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWizardPage

from ssba.core.progress import Progress
from ssba.core.recovery import EXPORTS, ExportOutcome, run_export
from ssba.gui.i18n import tr
from ssba.gui.worker import Worker

log = logging.getLogger("ssba.gui")


def _run_all(exports, scan_dir, dest, files_mode, outcomes, progress, cancel):
    total = len(exports)
    for index, export in enumerate(exports):
        cancel.check()
        progress(Progress("export", index, total, export.key))
        outcome = run_export(
            export, scan_dir, dest, files_mode=files_mode, progress=progress, cancel=cancel,
        )
        log.info("%s: %s", export.key, "ok" if outcome.ok else outcome.error)
        outcomes.append(outcome)
    progress(Progress("export", total, total, ""))
    return outcomes


class RunPage(QWizardPage):
    def __init__(self, wizard) -> None:
        super().__init__()
        self.w = wizard
        self.worker: Worker | None = None
        self._done = False
        self._exports = []
        self._running = ""
        self._cancelled_row = ""
        self._status_key = ""
        self.labels: dict[str, QLabel] = {}
        self.rows_layout = QVBoxLayout()
        self.bar = QProgressBar()
        self.status = QLabel()
        self.stop = QPushButton()
        layout = QVBoxLayout(self)
        layout.addLayout(self.rows_layout)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addWidget(self.stop)
        layout.addStretch(1)
        self.stop.clicked.connect(self._stop)

    def retranslate(self) -> None:
        self.setTitle(tr("p4_title"))
        self.setSubTitle(tr("p4_subtitle"))
        self.stop.setText(tr("p4_stop"))
        self.status.setText(tr(self._status_key) if self._status_key else "")
        self._refresh_rows()

    def initializePage(self) -> None:
        state = self.w.state
        state.outcomes = []
        self._done = False
        self._running = ""
        self._cancelled_row = ""
        self._status_key = ""
        if self.worker is not None and not self.worker.isRunning():
            for signal in (
                self.worker.progressed, self.worker.succeeded, self.worker.failed, self.worker.cancelled,
            ):
                signal.disconnect()
            self.worker.deleteLater()
            self.worker = None
        keys = list(state.selected) + (["files"] if state.files_mode in ("copy", "move") else [])
        self._exports = [e for e in EXPORTS if e.key in keys]
        while (child := self.rows_layout.takeAt(0)) is not None:
            if child.widget() is not None:
                child.widget().deleteLater()
        self.labels = {}
        for export in self._exports:
            label = QLabel()
            self.labels[export.key] = label
            self.rows_layout.addWidget(label)
        self._refresh_rows()
        self.status.setText("")
        self.stop.setEnabled(True)
        self.bar.setRange(0, 0)
        job = functools.partial(
            _run_all, self._exports, state.scan_dir, state.dest,
            state.files_mode if state.files_mode in ("copy", "move") else "copy", state.outcomes,
        )
        self.worker = Worker(job, self)
        self.worker.progressed.connect(self._on_progress)
        self.worker.succeeded.connect(lambda _outcomes: self._finish("p4_done"))
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(lambda: self._finish("p4_cancelled"))
        self.worker.start()

    def _refresh_rows(self) -> None:
        done = {o.key: o for o in self.w.state.outcomes}
        for export in self._exports:
            name = tr(f"export_{export.key}")
            if export.key in done:
                key = "p4_row_ok" if done[export.key].ok else "p4_row_error"
            elif export.key == self._running:
                key = "p4_row_running"
            elif export.key == self._cancelled_row:
                key = "p4_row_cancelled"
            else:
                key = "p4_row_waiting"
            self.labels[export.key].setText(tr(key, name=name))

    def _on_progress(self, event) -> None:
        if event.stage == "export":
            self._running = event.item
            self.bar.setRange(0, 0)
            self._refresh_rows()
        elif event.total:
            self.bar.setRange(0, event.total)
            self.bar.setValue(event.done)

    def _finish(self, key: str) -> None:
        state = self.w.state
        if key == "p4_cancelled" and self._running:
            self._cancelled_row = self._running
        if state.files_mode == "keep" and state.files_available:
            state.outcomes.append(ExportOutcome("files", True, None, None, state.scan_dir))
        self._running = ""
        self._refresh_rows()
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.stop.setEnabled(False)
        self._status_key = key
        self.status.setText(tr(key))
        self._done = True
        self.completeChanged.emit()

    def _on_failed(self, details: str) -> None:
        self._finish("p4_failed")
        self.w.show_error(details)

    def _stop(self) -> None:
        if self.worker is not None and self.worker.isRunning() and self.w.ask(tr("p4_confirm_stop")):
            self.worker.token.cancel()

    def cleanupPage(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.token.cancel()
            self.worker.wait()

    def isComplete(self) -> bool:
        return self._done
