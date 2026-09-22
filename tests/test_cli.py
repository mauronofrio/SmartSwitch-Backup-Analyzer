from __future__ import annotations

import json

from ssba.cli.main import run
from ssba.core.crypto import derive_key
from tests.contact_fixtures import build_scan_dir
from tests.crypto_helpers import encrypt_dummy_ecb, encrypt_iv_prefixed

FAKE_DUMMY = "AABBCCDDEEFF00112233445566778899AABB"
KEY = derive_key(FAKE_DUMMY)


def _build_minimal_backup(backup_root):
    backup_root.mkdir(parents=True, exist_ok=True)
    ciphertext_hex = encrypt_dummy_ecb(FAKE_DUMMY)
    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<BatchInfomationItem xmlns="Kies.Common.Data">
    <BundleInfo><Dummy>{ciphertext_hex}</Dummy></BundleInfo>
</BatchInfomationItem>"""
    (backup_root / "backupHistoryInfo.xml").write_text(xml, encoding="utf-8")
    (backup_root / "NOTES").mkdir()
    (backup_root / "NOTES" / "data.bin").write_bytes(
        encrypt_iv_prefixed(b'{"title": "fake note"}', KEY)
    )


def _build_multi_category_backup(backup_root):
    _build_minimal_backup(backup_root)
    (backup_root / "CONTACT").mkdir()
    (backup_root / "CONTACT" / "data.bin").write_bytes(
        encrypt_iv_prefixed(b'{"name": "fake contact"}', KEY)
    )


def test_run_scan_success(tmp_path, capsys):
    backup_root = tmp_path / "backup"
    out_dir = tmp_path / "out"
    _build_minimal_backup(backup_root)

    exit_code = run(["scan", str(backup_root), "--out", str(out_dir)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "NOTES:" in captured.out
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["categories"][0]["category"] == "NOTES"


def test_run_scan_with_category_filter(tmp_path, capsys):
    backup_root = tmp_path / "backup"
    out_dir = tmp_path / "out"
    _build_multi_category_backup(backup_root)

    exit_code = run(
        ["scan", str(backup_root), "--out", str(out_dir), "--category", "NOTES"]
    )

    assert exit_code == 0
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    categories = [c["category"] for c in report["categories"]]
    assert categories == ["NOTES"]


def test_run_scan_with_multiple_category_filters(tmp_path, capsys):
    backup_root = tmp_path / "backup"
    out_dir = tmp_path / "out"
    _build_multi_category_backup(backup_root)

    exit_code = run(
        [
            "scan",
            str(backup_root),
            "--out",
            str(out_dir),
            "--category",
            "NOTES",
            "--category",
            "CONTACT",
        ]
    )

    assert exit_code == 0
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    categories = {c["category"] for c in report["categories"]}
    assert categories == {"NOTES", "CONTACT"}


def test_run_scan_without_category_filter_scans_all(tmp_path, capsys):
    backup_root = tmp_path / "backup"
    out_dir = tmp_path / "out"
    _build_multi_category_backup(backup_root)

    exit_code = run(["scan", str(backup_root), "--out", str(out_dir)])

    assert exit_code == 0
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    categories = {c["category"] for c in report["categories"]}
    assert categories == {"NOTES", "CONTACT"}


def test_run_scan_missing_backup_history(tmp_path, capsys):
    backup_root = tmp_path / "backup"
    backup_root.mkdir()
    out_dir = tmp_path / "out"

    exit_code = run(["scan", str(backup_root), "--out", str(out_dir)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "backupHistoryInfo.xml" in captured.err


def test_export_contacts_success(tmp_path, capsys):
    scan_dir = build_scan_dir(tmp_path / "scan")
    out = tmp_path / "contacts.vcf"

    exit_code = run(["export", "contacts", str(scan_dir), "--out", str(out)])

    assert exit_code == 0
    assert out.is_file()
    captured = capsys.readouterr()
    assert "profile.vcf: 1 contacts" in captured.out
    assert "4 contacts written to" in captured.out


def test_export_contacts_unwritable_out_is_an_error_not_a_traceback(tmp_path, capsys):
    scan_dir = build_scan_dir(tmp_path / "scan")
    out = tmp_path / "contacts.vcf"
    out.mkdir()

    exit_code = run(["export", "contacts", str(scan_dir), "--out", str(out)])

    assert exit_code == 1
    assert capsys.readouterr().err.startswith("error: cannot write")


def test_export_contacts_missing_report(tmp_path, capsys):
    exit_code = run(["export", "contacts", str(tmp_path), "--out", str(tmp_path / "c.vcf")])

    assert exit_code == 1
    assert "report.json" in capsys.readouterr().err
