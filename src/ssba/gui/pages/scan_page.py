"""Page 2: decrypt the backup into <destination>/scan."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWizardPage

from ssba.core.scanner import scan_backup, write_report
from ssba.gui.i18n import tr
from ssba.gui.worker import Worker

log = logging.getLogger("ssba.gui")


def _decrypt(backup_path, scan_dir, progress, cancel):
    (scan_dir / "report.json").unlink(missing_ok=True)
    report = scan_backup(backup_path, scan_dir, progress=progress, cancel=cancel)
    write_report(report, scan_dir)
    return report


class ScanPage(QWizardPage):
    confirm_key = "p2_confirm_stop"

    def __init__(self, wizard) -> None:
        super().__init__()
        self.w = wizard
        self.worker: Worker | None = None
        self._done = False
        self.status = QLabel()
        self.bar = QProgressBar()
        self.item = QLabel()
        self.stop = QPushButton()
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.bar)
        layout.addWidget(self.item)
        layout.addWidget(self.stop)
        layout.addStretch(1)
        self.stop.clicked.connect(self._stop)

    def retranslate(self) -> None:
        self.setTitle(tr("p2_title"))
        self.setSubTitle(tr("p2_subtitle"))
        self.stop.setText(tr("p2_stop"))

    def initializePage(self) -> None:
        state = self.w.state
        backup_path = state.backup.path
        scan_dir = state.scan_dir
        self._done = False
        self.bar.setRange(0, 0)
        self.status.setText("")
        self.item.setText("")
        self.stop.setEnabled(True)
        log.info("decrypting %s into %s", backup_path, scan_dir)
        self.worker = Worker(lambda progress, cancel: _decrypt(backup_path, scan_dir, progress, cancel), self)
        self.worker.progressed.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()

    def _on_progress(self, event) -> None:
        if event.total:
            self.bar.setRange(0, event.total)
            self.bar.setValue(event.done)
            self.status.setText(tr("p2_progress", done=event.done, total=event.total))
        self.item.setText(event.item)

    def _finish(self, text: str) -> None:
        self.stop.setEnabled(False)
        self.status.setText(text)

    def _on_done(self, _report) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self._done = True
        self._finish(tr("p2_done"))
        log.info("decryption finished")
        self.completeChanged.emit()

    def _on_failed(self, details: str) -> None:
        self._finish(tr("p2_failed"))
        self.w.show_error(details)

    def _on_cancelled(self) -> None:
        self._finish(tr("p2_cancelled"))

    def _stop(self) -> None:
        if self.worker is not None and self.worker.isRunning() and self.w.ask(tr("p2_confirm_stop")):
            self.worker.token.cancel()

    def cleanupPage(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.token.cancel()
            self.worker.wait()

    def isComplete(self) -> bool:
        return self._done
