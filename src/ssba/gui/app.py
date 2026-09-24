"""Start the SmartSwitch Backup Analyzer window."""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ssba.gui.i18n import set_language
from ssba.gui.wizard import ICON, RecoveryWizard


def _own_taskbar_entry() -> None:
    """On Windows, group the window under its own icon, not Python's."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SmartSwitchBackupAnalyzer")


def main() -> int:
    _own_taskbar_entry()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ICON)))
    set_language("en")  # the wizard's language button switches to Italian
    wizard = RecoveryWizard()
    wizard.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
