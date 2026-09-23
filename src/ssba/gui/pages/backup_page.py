"""Page 1: pick the backup (or an already decrypted folder) and the destination."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWizardPage,
)

from ssba.core.discovery import BackupInfo, find_backups, format_size, read_backup
from ssba.core.errors import UnsupportedBackupError
from ssba.gui.i18n import tr


def free_space(path: Path) -> int | None:
    """Free bytes on the disk that will hold ``path`` (its nearest existing folder)."""
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def default_destination(info: BackupInfo, documents: Path | None = None) -> Path:
    if documents is None:
        location = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        documents = Path(location) if location else Path.home() / "Documents"
    day = info.saved_at.strftime("%Y-%m-%d") if info.saved_at else "backup"
    return documents / "SmartSwitch Recovery" / f"{info.model}_{day}"


def _inside(path: Path, folder: Path) -> bool:
    return path.resolve().is_relative_to(folder.resolve())


def _dest_has_foreign_files(dest: Path) -> bool:
    """True if ``dest`` exists, is non-empty and holds no previous SSBA run."""
    if not dest.is_dir():
        return False
    from ssba.gui.wizard import LOG_NAME

    if (dest / "scan" / "report.json").is_file() or (dest / LOG_NAME).is_file():
        return False
    return any(dest.iterdir())


class BackupPage(QWizardPage):
    def __init__(self, wizard) -> None:
        super().__init__()
        self.w = wizard
        self._infos: list[BackupInfo] = []
        self._dest_edited = False
        self.found = QLabel()
        self.backups = QListWidget()
        self.browse_backup = QPushButton()
        self.scan_note = QLabel()
        self.save_label = QLabel()
        self.dest = QLineEdit()
        self.browse_dest = QPushButton()

        layout = QVBoxLayout(self)
        layout.addWidget(self.found)
        layout.addWidget(self.backups)
        row = QHBoxLayout()
        row.addWidget(self.scan_note, 1)
        row.addWidget(self.browse_backup)
        layout.addLayout(row)
        dest_row = QHBoxLayout()
        dest_row.addWidget(self.save_label)
        dest_row.addWidget(self.dest, 1)
        dest_row.addWidget(self.browse_dest)
        layout.addLayout(dest_row)

        self.backups.currentRowChanged.connect(self._on_backup_selected)
        self.dest.textChanged.connect(self.completeChanged)
        self.dest.textEdited.connect(self._on_dest_edited)
        self.browse_backup.clicked.connect(self._pick_backup)
        self.browse_dest.clicked.connect(self._pick_dest)

        self._infos = find_backups(self.w.roots)
        self._refresh_list()
        if self._infos:
            self.backups.setCurrentRow(0)

    def retranslate(self) -> None:
        self.setTitle(tr("p1_title"))
        self.setSubTitle(tr("p1_subtitle"))
        self.found.setText(tr("p1_found") if self._infos else tr("p1_none"))
        self.browse_backup.setText(tr("p1_browse_backup"))
        self.save_label.setText(tr("p1_save_to"))
        self.browse_dest.setText(tr("p1_browse_dest"))
        scan = self.w.state.existing_scan
        self.scan_note.setText(tr("p1_scan_folder", path=scan) if scan else "")
        self._refresh_list()

    def _refresh_list(self) -> None:
        row = self.backups.currentRow()
        self.backups.blockSignals(True)
        self.backups.clear()
        for info in self._infos:
            date = info.saved_at.strftime("%Y-%m-%d %H:%M") if info.saved_at else "?"
            size = format_size(info.size)
            if info.device_name:
                text = tr("p1_backup_line", name=info.device_name, model=info.model, date=date, size=size)
            else:
                text = tr("p1_backup_line_no_name", model=info.model, date=date, size=size)
            self.backups.addItem(text)
        self.backups.setCurrentRow(row)
        self.backups.blockSignals(False)

    def _on_dest_edited(self, _text: str) -> None:
        self._dest_edited = True

    def _on_backup_selected(self, row: int) -> None:
        if row < 0:
            return
        info = self._infos[row]
        self.w.state.backup = info
        self.w.state.existing_scan = None
        self.scan_note.setText("")
        if not self._dest_edited:
            self.dest.setText(str(default_destination(info)))
        self.completeChanged.emit()

    def _pick_backup(self) -> None:
        folder = self.w.choose_folder(tr("p1_pick_backup"))
        if folder is None:
            return
        if (folder / "report.json").is_file():
            self.w.state.existing_scan = folder
            self.w.state.backup = None
            self.backups.setCurrentRow(-1)
            self.scan_note.setText(tr("p1_scan_folder", path=folder))
            if not self._dest_edited:
                self.dest.setText(str(folder.parent))
            self.completeChanged.emit()
            return
        try:
            info = read_backup(folder)
        except UnsupportedBackupError:
            self.w.warn(tr("p1_not_backup"))
            return
        resolved = info.path.resolve()
        for row, existing in enumerate(self._infos):
            if existing.path.resolve() == resolved:
                self.backups.setCurrentRow(row)
                return
        self._infos.insert(0, info)
        self._refresh_list()
        self.found.setText(tr("p1_found"))
        self.backups.setCurrentRow(0)

    def _pick_dest(self) -> None:
        folder = self.w.choose_folder(tr("p1_pick_dest"))
        if folder is not None:
            self._dest_edited = True
            self.dest.setText(str(folder))

    def isComplete(self) -> bool:
        state = self.w.state
        return bool(self.dest.text().strip()) and (state.backup is not None or state.existing_scan is not None)

    def validatePage(self) -> bool:
        state = self.w.state
        dest = Path(self.dest.text().strip()).expanduser()
        if not dest.is_absolute():
            self.w.warn(tr("p1_dest_relative"))
            return False
        if _dest_has_foreign_files(dest) and not self.w.ask(tr("p1_dest_not_empty")):
            return False
        if state.backup is not None:
            if _inside(dest, state.backup.path):
                self.w.warn(tr("p1_dest_inside"))
                return False
            if state.backup.size:
                needed = 2 * state.backup.size
                free = free_space(dest)
                if free is not None and free < needed and not self.w.ask(
                    tr("p1_low_space", free=format_size(free), needed=format_size(needed))
                ):
                    return False
            scan_dir = dest / "scan"
            state.reuse_scan = (scan_dir / "report.json").is_file() and self.w.ask(tr("p1_reuse"))
        else:
            scan_dir = state.existing_scan
            state.reuse_scan = True
        try:
            self.w.start_log(dest)
        except OSError as error:
            self.w.warn(tr("p1_dest_unusable", error=error))
            return False
        state.dest = dest
        state.scan_dir = scan_dir
        return True

    def nextId(self) -> int:
        from ssba.gui.wizard import PAGE_CHOOSE, PAGE_SCAN

        return PAGE_CHOOSE if self.w.state.reuse_scan else PAGE_SCAN
