"""Page 3: tick what to recover; choose how photos and files are handled."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QGroupBox, QLabel, QRadioButton, QVBoxLayout, QWizardPage,
)

from ssba.core.recovery import available_exports
from ssba.gui.i18n import tr


class ChoosePage(QWizardPage):
    def __init__(self, wizard) -> None:
        super().__init__()
        self.w = wizard
        self.checks: dict[str, QCheckBox] = {}
        self._exports = []
        self.nothing = QLabel()
        self.list_layout = QVBoxLayout()
        self.files_box = QGroupBox()
        self.files_keep = QRadioButton()
        self.files_copy = QRadioButton()
        self.files_move = QRadioButton()
        self.move_help = QLabel()
        self.move_help.setWordWrap(True)
        group = QButtonGroup(self)
        for button in (self.files_keep, self.files_copy, self.files_move):
            group.addButton(button)
        box_layout = QVBoxLayout(self.files_box)
        for widget in (self.files_keep, self.files_copy, self.files_move, self.move_help):
            box_layout.addWidget(widget)
        layout = QVBoxLayout(self)
        layout.addWidget(self.nothing)
        layout.addLayout(self.list_layout)
        layout.addWidget(self.files_box)
        layout.addStretch(1)
        self.files_keep.toggled.connect(self.completeChanged)
        self.files_copy.toggled.connect(self.completeChanged)
        self.files_move.toggled.connect(self.completeChanged)
        self.setCommitPage(True)

    def initializePage(self) -> None:
        while (child := self.list_layout.takeAt(0)) is not None:
            if child.widget() is not None:
                child.widget().deleteLater()
        self.checks = {}
        self._exports = available_exports(self.w.state.scan_dir)
        for export in self._exports:
            if export.key == "files":
                continue
            box = QCheckBox()
            box.setChecked(True)
            box.toggled.connect(self.completeChanged)
            self.checks[export.key] = box
            self.list_layout.addWidget(box)
        self.w.state.files_available = any(e.key == "files" for e in self._exports)
        self.files_box.setVisible(self.w.state.files_available)
        self.files_copy.setChecked(True)
        self.retranslate()

    def _count(self, export) -> str:
        backup = self.w.state.backup
        n = sum(backup.items.get(c, 0) for c in export.categories) if backup else 0
        return tr("p3_count", n=n) if n else ""

    def retranslate(self) -> None:
        self.setTitle(tr("p3_title"))
        self.setSubTitle(tr("p3_subtitle"))
        self.nothing.setText("" if self._exports else tr("p3_nothing"))
        for export in self._exports:
            if export.key in self.checks:
                text = tr(f"export_{export.key}") + self._count(export)
                if export.key == "wifi":
                    text += tr("p3_wifi_warning")
                self.checks[export.key].setText(text)
        self.files_box.setTitle(tr("p3_files"))
        self.files_keep.setText(tr("p3_files_keep"))
        self.files_copy.setText(tr("p3_files_copy"))
        self.files_move.setText(tr("p3_files_move"))
        self.move_help.setText(tr("p3_files_move_help"))

    def validatePage(self) -> bool:
        state = self.w.state
        state.selected = [key for key, box in self.checks.items() if box.isChecked()]
        if not state.files_available or self.files_keep.isChecked():
            state.files_mode = "keep"
        else:
            state.files_mode = "move" if self.files_move.isChecked() else "copy"
        return True

    def isComplete(self) -> bool:
        if any(box.isChecked() for box in self.checks.values()):
            return True
        return self.w.state.files_available and not self.files_keep.isChecked()
