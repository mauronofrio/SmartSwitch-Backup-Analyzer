"""GUI tests run without a screen; they are skipped where PySide6 is not installed."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PySide6  # noqa: F401
    import pytestqt  # noqa: F401
except ImportError:
    collect_ignore_glob = ["test_*.py"]
