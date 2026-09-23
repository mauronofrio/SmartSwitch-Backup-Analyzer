from __future__ import annotations

import json

import pytest

from ssba.core.crypto import derive_key
from ssba.core.progress import CancelToken, OperationCancelled, Progress
from ssba.core.scanner import scan_backup, write_report
from tests.crypto_helpers import encrypt_dummy_ecb, encrypt_iv_prefixed

FAKE_DUMMY = "AABBCCDDEEFF00112233445566778899AABB"
KEY = derive_key(FAKE_DUMMY)


def _backup(root):
    root.mkdir(parents=True)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" ?>'
        '<BatchInfomationItem xmlns="Kies.Common.Data">'
        f"<BundleInfo><Dummy>{encrypt_dummy_ecb(FAKE_DUMMY)}</Dummy></BundleInfo>"
        "</BatchInfomationItem>"
    )
    (root / "backupHistoryInfo.xml").write_text(xml, encoding="utf-8")
    for category, names in {"CAT_A": ["one.exml", "two.exml"], "CAT_B": ["three.exml"]}.items():
        (root / category).mkdir()
        for name in names:
            data = f"<?xml version='1.0'?><Root>{name}</Root>".encode()
            (root / category / name).write_bytes(encrypt_iv_prefixed(data, KEY))
    return root


def test_cancel_token():
    token = CancelToken()
    assert token.cancelled is False
    token.check()
    token.cancel()
    assert token.cancelled is True
    with pytest.raises(OperationCancelled):
        token.check()


def test_scan_reports_one_event_per_file_then_the_end(tmp_path):
    events: list[Progress] = []
    scan_backup(_backup(tmp_path / "backup"), tmp_path / "scan", progress=events.append)
    assert [(e.stage, e.done, e.total, e.item) for e in events] == [
        ("scan", 0, 2, "CAT_A/one.exml"),
        ("scan", 0, 2, "CAT_A/two.exml"),
        ("scan", 1, 2, "CAT_B/three.exml"),
        ("scan", 2, 2, ""),
    ]


def test_scan_without_hooks_is_unchanged(tmp_path):
    report = scan_backup(_backup(tmp_path / "backup"), tmp_path / "scan")
    assert [c.category for c in report.categories] == ["CAT_A", "CAT_B"]
    assert (tmp_path / "scan" / "CAT_B" / "three.exml").is_file()


def test_scan_cancel_stops_between_files_and_keeps_what_was_written(tmp_path):
    token = CancelToken()

    def progress(event):
        if event.item == "CAT_A/one.exml":
            token.cancel()

    with pytest.raises(OperationCancelled):
        scan_backup(_backup(tmp_path / "backup"), tmp_path / "scan", progress=progress, cancel=token)
    assert (tmp_path / "scan" / "CAT_A" / "one.exml").read_bytes().startswith(b"<?xml")
    assert not (tmp_path / "scan" / "CAT_A" / "two.exml").exists()
    assert not (tmp_path / "scan" / "CAT_B").exists()


def test_write_report_writes_the_cli_report(tmp_path):
    report = scan_backup(_backup(tmp_path / "backup"), tmp_path / "scan")
    path = write_report(report, tmp_path / "scan")
    assert path == tmp_path / "scan" / "report.json"
    assert path.read_text(encoding="utf-8") == json.dumps(report.to_dict(), indent=2)
