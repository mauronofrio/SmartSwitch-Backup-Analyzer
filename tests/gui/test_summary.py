from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ssba.core.recovery import ExportOutcome
from ssba.gui import i18n
from ssba.gui.summary import describe


@pytest.fixture(autouse=True)
def _english():
    i18n.set_language("en")


def _ok(key, **fields):
    return ExportOutcome(key, True, SimpleNamespace(**fields), None, Path("x"))


def test_ok_line():
    assert describe(_ok("contacts", exported=798, unparsed=0)) == ("ok", "798 contacts")


def test_warning_line():
    level, text = describe(_ok("notes", notes=10, attachments=4, handwriting_only=1, with_drawings=2))
    assert level == "warn"
    assert text == "10 notes, 4 attachments \u2014 3 to check"


def test_error_line():
    outcome = ExportOutcome("wifi", False, None, "no Wi-Fi configuration found", Path("x"))
    assert describe(outcome) == ("error", "Failed: no Wi-Fi configuration found")


def test_files_left_in_their_folders():
    outcome = ExportOutcome("files", True, None, None, Path("scan"))
    assert describe(outcome) == ("ok", "Left in their category folders")


def test_every_export_key_has_a_line():
    fields = dict(
        exported=1, unparsed=0, unsupported=0, networks=1, with_password=1, bookmarks=1, history=1,
        texts=1, images=1, missing_images=0, alarms=1, timers=1, cities=1, notes=1, attachments=1,
        handwriting_only=0, with_drawings=0, apps=1, placed=1, merged=0, conflicts=0, missing=0,
    )
    for key in ("contacts", "messages", "calls", "wifi", "blocked-numbers", "browser",
                "clipboard", "clock", "notes", "apps", "files"):
        level, text = describe(_ok(key, **fields))
        assert level == "ok" and text
