from __future__ import annotations

import struct

from ssba.gui.wizard import ICON, RecoveryWizard


def test_icon_file_holds_the_sizes_windows_uses():
    data = ICON.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind) == (0, 1)
    sizes = set()
    for i in range(count):
        width = data[6 + 16 * i] or 256
        sizes.add(width)
    assert {16, 24, 32, 48, 256} <= sizes


def test_wizard_window_has_the_icon(qtbot, tmp_path):
    wizard = RecoveryWizard(roots=[tmp_path])
    qtbot.addWidget(wizard)
    assert not wizard.windowIcon().isNull()
