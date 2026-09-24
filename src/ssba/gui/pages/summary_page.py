"""Page 5: what was recovered, with buttons to open it."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWizardPage

from ssba.gui.i18n import tr
from ssba.gui.summary import describe

_ICONS = {"ok": "\u2714", "warn": "\u26a0", "error": "\u2716"}


@dataclass
class SummaryRow:
    icon: QLabel
    name: QLabel
    text: QLabel
    open_button: QPushButton


class SummaryPage(QWizardPage):
    def __init__(self, wizard) -> None:
        super().__init__()
        self.w = wizard
        self.rows: list[SummaryRow] = []
        self.grid = QGridLayout()
        self.grid.setColumnStretch(2, 1)  # the result text takes the spare width
        self.open_results = QPushButton()
        self.guide = QPushButton()
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_results)
        buttons.addWidget(self.guide)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(self.grid)
        layout.addLayout(buttons)
        layout.addStretch(1)
        self.open_results.clicked.connect(lambda: self.w.open_path(self.w.state.dest))
        self.guide.clicked.connect(lambda: self.w.info(tr("p5_guide_text")))
        self.setFinalPage(True)

    def initializePage(self) -> None:
        while (child := self.grid.takeAt(0)) is not None:
            if child.widget() is not None:
                child.widget().deleteLater()
        self.rows = []
        for index, outcome in enumerate(self.w.state.outcomes):
            row = SummaryRow(QLabel(), QLabel(), QLabel(), QPushButton())
            row.text.setWordWrap(True)
            row.open_button.setEnabled(outcome.path.exists())
            row.open_button.clicked.connect(lambda _checked=False, p=outcome.path: self.w.open_path(p))
            for column, widget in enumerate((row.icon, row.name, row.text, row.open_button)):
                self.grid.addWidget(widget, index, column)
            self.rows.append(row)
        self.retranslate()

    def retranslate(self) -> None:
        self.setTitle(tr("p5_title"))
        self.setSubTitle(tr("p5_subtitle"))
        self.open_results.setText(tr("p5_open_results"))
        self.guide.setText(tr("p5_guide_button"))
        for row, outcome in zip(self.rows, self.w.state.outcomes):
            level, text = describe(outcome)
            row.icon.setText(_ICONS[level])
            row.name.setText(tr(f"export_{outcome.key}"))
            row.text.setText(text)
            row.open_button.setText(tr("p5_open"))
