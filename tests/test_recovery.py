from __future__ import annotations

import pytest

from ssba.core import recovery
from ssba.core.progress import CancelToken, OperationCancelled
from ssba.core.recovery import EXPORTS, available_exports, run_export
from tests.clock_fixtures import build_clock_scan_dir
from tests.files_fixtures import build_files_scan_dir


def _export(key):
    return next(e for e in EXPORTS if e.key == key)


def test_exports_follow_the_export_all_order():
    assert [e.key for e in EXPORTS] == [
        "contacts", "messages", "calls", "wifi", "blocked-numbers", "browser",
        "clipboard", "clock", "notes", "apps", "files",
    ]
    assert [e.target for e in EXPORTS] == [
        "contacts.vcf", "sms.xml", "calls.xml", "wifi.html", "blocked-numbers.txt", "browser",
        "clipboard", "clock.html", "notes", "apps.html", "files",
    ]


def test_available_exports_come_from_the_report(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    build_clock_scan_dir(scan_dir, timer=None, world=None)
    assert [e.key for e in available_exports(scan_dir)] == ["clock", "files"]


def test_available_exports_without_a_report_is_empty(tmp_path):
    assert available_exports(tmp_path) == []


def test_a_successful_export(tmp_path):
    scan_dir = build_clock_scan_dir(tmp_path / "scan")
    outcome = run_export(_export("clock"), scan_dir, tmp_path / "out")
    assert (outcome.key, outcome.ok, outcome.error) == ("clock", True, None)
    assert outcome.result.alarms == 3
    assert outcome.path == tmp_path / "out" / "clock.html"
    assert outcome.path.is_file()


def test_an_export_error_is_an_outcome_not_an_exception(tmp_path):
    scan_dir = build_clock_scan_dir(tmp_path / "scan")
    outcome = run_export(_export("contacts"), scan_dir, tmp_path / "out")
    assert (outcome.ok, outcome.result) == (False, None)
    assert "CONTACT" in outcome.error


def test_an_unexpected_exception_is_an_outcome(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setitem(recovery._RUNNERS, "clock", boom)
    outcome = run_export(_export("clock"), tmp_path, tmp_path / "out")
    assert (outcome.ok, outcome.error) == (False, "unexpected: RuntimeError: bug")


def test_files_export_uses_the_mode_and_forwards_progress(tmp_path):
    events = []
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    outcome = run_export(_export("files"), scan_dir, tmp_path / "out", files_mode="move", progress=events.append)
    assert outcome.ok and outcome.result.placed == 8
    assert not (scan_dir / "Video").exists()  # moved
    assert events and events[-1].stage == "files"


def test_cancel_propagates(tmp_path):
    token = CancelToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        run_export(_export("files"), build_files_scan_dir(tmp_path / "scan"), tmp_path / "out", cancel=token)
