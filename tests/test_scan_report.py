from __future__ import annotations

import json
import zipfile

import pytest

from ssba.core.parsers.scan_report import MissingCategoryError, ScanReportError, category_files, category_zip


def _write_report(scan_dir, files, category="CALLLOG"):
    scan_dir.mkdir(parents=True, exist_ok=True)
    report = {"categories": [
        {"category": "OTHER", "counts": {}, "files": []},
        {"category": category, "counts": {}, "files": files},
    ]}
    (scan_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_returns_exportable_files_in_report_order(tmp_path):
    b = _touch(tmp_path / "CALLLOG" / "CALLLOG.zip" / "b.exml")
    a = _touch(tmp_path / "CALLLOG" / "a.exml")
    _write_report(tmp_path, [
        {"path": "CALLLOG.zip", "status": "plaintext_passthrough"},  # a directory
        {"path": "CALLLOG.zip/b.exml", "status": "decrypted"},
        {"path": "a.exml", "status": "plaintext_passthrough"},
    ])
    assert category_files(tmp_path, "CALLLOG") == [b, a]


def test_skips_bad_status_malformed_missing_and_escaping_entries(tmp_path):
    good = _touch(tmp_path / "CALLLOG" / "good.exml")
    _touch(tmp_path / "CALLLOG" / "undecoded.exml")
    _touch(tmp_path / "outside.exml")
    _write_report(tmp_path, [
        "not a dict",
        {"path": None, "status": "decrypted"},
        {"status": "decrypted"},
        {"path": "", "status": "decrypted"},
        {"path": "undecoded.exml", "status": "undecoded"},
        {"path": "error.exml", "status": "error"},
        {"path": "missing.exml", "status": "decrypted"},
        {"path": "../outside.exml", "status": "decrypted"},
        {"path": str(tmp_path / "outside.exml"), "status": "decrypted"},
        {"path": "good.exml", "status": "decrypted"},
    ])
    assert category_files(tmp_path, "CALLLOG") == [good]


def test_files_that_is_not_a_list_gives_no_files(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    report = {"categories": [{"category": "CALLLOG", "files": "nope"}]}
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    assert category_files(tmp_path, "CALLLOG") == []


def test_missing_report_raises(tmp_path):
    with pytest.raises(ScanReportError, match="report.json not found"):
        category_files(tmp_path, "CALLLOG")


@pytest.mark.parametrize("content", [b"{not json", b"\xff\xfe{", b"[]", b'{"categories": {}}'])
def test_unreadable_report_raises(tmp_path, content):
    (tmp_path / "report.json").write_bytes(content)
    with pytest.raises(ScanReportError, match="report.json is not readable"):
        category_files(tmp_path, "CALLLOG")


def test_missing_category_raises_naming_it(tmp_path):
    _write_report(tmp_path, [], category="CONTACT")
    with pytest.raises(ScanReportError, match="the scan report has no GMMESSAGE category"):
        category_files(tmp_path, "GMMESSAGE")


def test_missing_category_error_is_a_scan_report_error(tmp_path):
    _write_report(tmp_path, [], category="CONTACT")
    with pytest.raises(MissingCategoryError, match="the scan report has no WIFICONFIG category"):
        category_files(tmp_path, "WIFICONFIG")
    assert issubclass(MissingCategoryError, ScanReportError)


def test_missing_report_is_not_a_missing_category(tmp_path):
    with pytest.raises(ScanReportError) as info:
        category_files(tmp_path, "CALLLOG")
    assert not isinstance(info.value, MissingCategoryError)


def _zip(path, members):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def test_category_zip_returns_the_first_zip_holding_the_member(tmp_path):
    _touch(tmp_path / "CALLLOG" / "not-a-zip.bin")
    _zip(tmp_path / "CALLLOG" / "other.zip", {"x.txt": b"x"})
    wanted = _zip(tmp_path / "CALLLOG" / "backup.enc", {"databases/SBrowser.db": b"db"})
    _zip(tmp_path / "CALLLOG" / "later.zip", {"databases/SBrowser.db": b"db"})
    _write_report(tmp_path, [
        {"path": "not-a-zip.bin", "status": "decrypted"},
        {"path": "other.zip", "status": "decrypted"},
        {"path": "backup.enc", "status": "decrypted"},
        {"path": "later.zip", "status": "decrypted"},
    ])
    assert category_zip(tmp_path, "CALLLOG", "databases/SBrowser.db") == wanted


def test_category_zip_without_a_match_returns_none(tmp_path):
    _zip(tmp_path / "CALLLOG" / "other.zip", {"x.txt": b"x"})
    _write_report(tmp_path, [{"path": "other.zip", "status": "decrypted"}])
    assert category_zip(tmp_path, "CALLLOG", "databases/SBrowser.db") is None
