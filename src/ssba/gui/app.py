"""Start the SmartSwitch Backup Analyzer window."""

from __future__ import annotations

import sys

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from ssba.gui.i18n import set_language, system_language
from ssba.gui.wizard import RecoveryWizard


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    set_language(system_language(QLocale.system().name()))
    wizard = RecoveryWizard()
    wizard.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
