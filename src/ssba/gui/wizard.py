"""The recovery wizard: shared state, dialogs and page wiring."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWizard

from ssba.core.discovery import BackupInfo
from ssba.gui.i18n import language, set_language, tr

PAGE_BACKUP, PAGE_SCAN, PAGE_CHOOSE, PAGE_RUN, PAGE_SUMMARY = range(5)
LOG_NAME = "ssba-gui.log"


@dataclass
class WizardState:
    backup: BackupInfo | None = None
    existing_scan: Path | None = None  # an already decrypted folder picked by hand
    dest: Path | None = None
    scan_dir: Path | None = None
    reuse_scan: bool = False
    selected: list[str] = field(default_factory=list)
    files_mode: str = "copy"  # "keep", "copy" or "move"
    files_available: bool = False
    outcomes: list = field(default_factory=list)  # ssba.core.recovery.ExportOutcome


class RecoveryWizard(QWizard):
    def __init__(self, roots: list[Path] | None = None, parent=None) -> None:
        super().__init__(parent)
        from ssba.gui.pages.backup_page import BackupPage
        from ssba.gui.pages.scan_page import ScanPage

        self.roots = roots
        self.state = WizardState()
        self.log_path: Path | None = None
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.HaveCustomButton1, True)
        self.customButtonClicked.connect(self._on_custom_button)
        self.setPage(PAGE_BACKUP, BackupPage(self))
        self.setPage(PAGE_SCAN, ScanPage(self))
        self._add_later_pages()
        self.resize(760, 560)
        self.retranslate()

    def _add_later_pages(self) -> None:
        """Pages added by later tasks; missing modules are simply skipped."""
        try:
            from ssba.gui.pages.choose_page import ChoosePage
            from ssba.gui.pages.run_page import RunPage
            from ssba.gui.pages.summary_page import SummaryPage
        except ImportError:
            return
        self.setPage(PAGE_CHOOSE, ChoosePage(self))
        self.setPage(PAGE_RUN, RunPage(self))
        self.setPage(PAGE_SUMMARY, SummaryPage(self))

    def done(self, result: int) -> None:
        logger = logging.getLogger("ssba.gui")
        for handler in list(logger.handlers):
            if getattr(handler, "_ssba", False):
                logger.removeHandler(handler)
                handler.close()
        super().done(result)

    def _on_custom_button(self, _which: int) -> None:
        # The only custom button is the language switch.
        set_language("en" if language() == "it" else "it")
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(tr("app_title"))
        self.setButtonText(QWizard.CustomButton1, tr("lang_button"))
        self.setButtonText(QWizard.BackButton, tr("back"))
        self.setButtonText(QWizard.NextButton, tr("next"))
        self.setButtonText(QWizard.CancelButton, tr("cancel"))
        self.setButtonText(QWizard.FinishButton, tr("finish"))
        for page_id in self.pageIds():
            self.page(page_id).retranslate()

    # Dialogs and desktop actions: small methods so tests can replace them.
    def ask(self, text: str) -> bool:
        return QMessageBox.question(self, tr("app_title"), text) == QMessageBox.Yes

    def warn(self, text: str) -> None:
        QMessageBox.warning(self, tr("app_title"), text)

    def info(self, text: str) -> None:
        QMessageBox.information(self, tr("app_title"), text)

    def show_error(self, details: str) -> None:
        box = QMessageBox(QMessageBox.Critical, tr("error_title"), tr("error_text", log=self.log_path or "-"), parent=self)
        box.setDetailedText(details)
        box.exec()

    def choose_folder(self, title: str) -> Path | None:
        folder = QFileDialog.getExistingDirectory(self, title)
        return Path(folder) if folder else None

    def open_path(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def start_log(self, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / LOG_NAME
        logger = logging.getLogger("ssba.gui")
        logger.setLevel(logging.INFO)
        if self.log_path != path:
            for handler in list(logger.handlers):
                if getattr(handler, "_ssba", False):
                    logger.removeHandler(handler)
                    handler.close()
            handler = logging.FileHandler(path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            handler._ssba = True
            logger.addHandler(handler)
            self.log_path = path
        logger.info("destination %s", dest)
