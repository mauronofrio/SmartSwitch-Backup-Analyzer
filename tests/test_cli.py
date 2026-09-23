from __future__ import annotations

import json

from ssba.cli.main import run
from ssba.core.crypto import derive_key
from tests.blocked_fixtures import build_blocked_scan_dir
from tests.browser_fixtures import build_browser_scan_dir
from tests.call_fixtures import build_call_scan_dir
from tests.clipboard_fixtures import build_clipboard_scan_dir
from tests.clock_fixtures import build_clock_scan_dir
from tests.contact_fixtures import build_scan_dir
from tests.crypto_helpers import encrypt_dummy_ecb, encrypt_iv_prefixed
from tests.message_fixtures import build_message_scan_dir
from tests.notes_fixtures import build_notes_scan_dir
from tests.wifi_fixtures import build_wifi_scan_dir

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


def test_export_messages_success(tmp_path, capsys):
    scan_dir = build_message_scan_dir(tmp_path / "scan")
    out = tmp_path / "sms.xml"

    exit_code = run(["export", "messages", str(scan_dir), "--out", str(out)])

    assert exit_code == 0
    assert out.is_file()
    printed = capsys.readouterr().out
    assert f"3 messages written to {out}" in printed
    assert "1 RCS messages converted to SMS" in printed
    assert "1 system messages skipped" in printed
    assert f"1 messages could not be converted; kept in {tmp_path / 'sms_unsupported.json'}" in printed
    assert "invalid characters" not in printed


def test_export_messages_missing_report(tmp_path, capsys):
    exit_code = run(["export", "messages", str(tmp_path), "--out", str(tmp_path / "s.xml")])
    assert exit_code == 1
    assert capsys.readouterr().err.startswith("error: report.json not found")


def test_export_messages_unwritable_out(tmp_path, capsys):
    scan_dir = build_message_scan_dir(tmp_path / "scan")
    out = tmp_path / "sms.xml"
    out.mkdir()
    exit_code = run(["export", "messages", str(scan_dir), "--out", str(out)])
    assert exit_code == 1
    assert capsys.readouterr().err.startswith("error: cannot write")


def test_export_calls_success(tmp_path, capsys):
    scan_dir = build_call_scan_dir(tmp_path / "scan")
    out = tmp_path / "calls.xml"

    exit_code = run(["export", "calls", str(scan_dir), "--out", str(out)])

    assert exit_code == 0
    assert out.is_file()
    printed = capsys.readouterr().out
    assert f"5 calls written to {out}" in printed
    assert "unknown type" not in printed
    assert "could not be converted" not in printed


def test_export_calls_missing_report(tmp_path, capsys):
    exit_code = run(["export", "calls", str(tmp_path), "--out", str(tmp_path / "c.xml")])
    assert exit_code == 1
    assert capsys.readouterr().err.startswith("error: report.json not found")


def test_export_calls_unwritable_out(tmp_path, capsys):
    scan_dir = build_call_scan_dir(tmp_path / "scan")
    out = tmp_path / "calls.xml"
    out.mkdir()
    exit_code = run(["export", "calls", str(scan_dir), "--out", str(out)])
    assert exit_code == 1
    assert capsys.readouterr().err.startswith("error: cannot write")


def test_export_wifi_success_warns_about_passwords(tmp_path, capsys):
    scan_dir = build_wifi_scan_dir(tmp_path / "scan")
    out = tmp_path / "wifi.html"
    assert run(["export", "wifi", str(scan_dir), "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert f"3 Wi-Fi networks written to {out} (2 with a password)" in captured.out
    assert f"warning: {out} contains Wi-Fi passwords in clear text" in captured.err


def test_export_blocked_numbers_success(tmp_path, capsys):
    scan_dir = build_blocked_scan_dir(tmp_path / "scan")
    out = tmp_path / "blocked.txt"
    assert run(["export", "blocked-numbers", str(scan_dir), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert f"4 blocked numbers written to {out}" in printed
    assert "1 rows without a number skipped" in printed


def test_export_browser_success(tmp_path, capsys):
    scan_dir = build_browser_scan_dir(tmp_path / "scan")
    out = tmp_path / "browser"
    assert run(["export", "browser", str(scan_dir), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert f"3 bookmarks in 2 folders and 2 quick access items written to {out / 'bookmarks.html'}" in printed
    assert f"3 visited sites and 2 downloads written to {out / 'history.html'}" in printed
    assert "2 entries without an address skipped" in printed


def test_export_clipboard_success(tmp_path, capsys):
    scan_dir = build_clipboard_scan_dir(tmp_path / "scan")
    out = tmp_path / "clipboard"
    assert run(["export", "clipboard", str(scan_dir), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert f"3 texts and 5 images written to {out / 'index.html'}" in printed
    assert "1 clipboard images were missing from the backup" in printed
    assert "1 entries of an unknown type included as text" in printed


def test_export_clock_success(tmp_path, capsys):
    scan_dir = build_clock_scan_dir(tmp_path / "scan")
    out = tmp_path / "clock.html"
    assert run(["export", "clock", str(scan_dir), "--out", str(out)]) == 0
    assert f"3 alarms, 2 timers and 2 world clock cities written to {out}" in capsys.readouterr().out


def test_new_exports_report_errors_on_stderr(tmp_path, capsys):
    for kind in ("wifi", "blocked-numbers", "browser", "clipboard", "clock"):
        assert run(["export", kind, str(tmp_path), "--out", str(tmp_path / "x")]) == 1
        assert capsys.readouterr().err.startswith("error: ")


def test_export_all_runs_every_kind_and_continues_past_failures(tmp_path, capsys):
    scan_dir = build_call_scan_dir(tmp_path / "scan")
    build_wifi_scan_dir(scan_dir)
    out = tmp_path / "all"

    assert run(["export", "all", str(scan_dir), "--out", str(out)]) == 0

    captured = capsys.readouterr()
    for kind in ("contacts", "messages", "calls", "wifi", "blocked-numbers", "browser", "clipboard", "clock", "notes"):
        assert f"== {kind} ==" in captured.out
    assert "error: the scan report has no CONTACT category" in captured.err
    assert (out / "calls.xml").is_file()
    assert (out / "wifi.html").is_file()
    assert f"2 of 9 exports written to {out}" in captured.out


def test_export_all_continues_past_an_unexpected_exception(tmp_path, capsys, monkeypatch):
    import ssba.cli.main as main_mod

    scan_dir = build_call_scan_dir(tmp_path / "scan")
    build_wifi_scan_dir(scan_dir)
    out = tmp_path / "all"

    def boom(scan_dir, out):
        raise RuntimeError("kaboom")

    patched = tuple(
        (name, boom if name == "calls" else runner, target)
        for name, runner, target in main_mod._ALL_EXPORTS
    )
    monkeypatch.setattr(main_mod, "_ALL_EXPORTS", patched)

    exit_code = main_mod._run_export_all(scan_dir, out)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "error: calls failed unexpectedly: kaboom" in captured.err
    for kind in ("contacts", "messages", "calls", "wifi", "blocked-numbers", "browser", "clipboard", "clock", "notes"):
        assert f"== {kind} ==" in captured.out
    assert (out / "wifi.html").is_file()
    assert "1 of 9 exports written to" in captured.out


def test_export_all_without_report_runs_nothing(tmp_path, capsys):
    assert run(["export", "all", str(tmp_path), "--out", str(tmp_path / "all")]) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: report.json not found")
    assert "==" not in captured.out


def test_export_all_with_nothing_exportable_fails(tmp_path, capsys):
    (tmp_path / "report.json").write_text('{"categories": []}', encoding="utf-8")
    assert run(["export", "all", str(tmp_path), "--out", str(tmp_path / "all")]) == 1
    assert "0 of 9 exports written" in capsys.readouterr().out


def test_export_notes_success(tmp_path, capsys):
    scan_dir = build_notes_scan_dir(tmp_path / "scan")
    out = tmp_path / "notes"
    assert run(["export", "notes", str(scan_dir), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert f"7 notes written to {out} (4 with text, 3 attachments)" in printed
    assert f"2 notes from the trash in {out / 'Trash'}" in printed
    assert "2 notes only had a text preview (it may be cut short)" in printed
    assert "1 notes contain only handwriting or drawings, which cannot be exported" in printed
    assert "2 notes had handwriting or drawings that are not exported" in printed
    assert "2 notes had no file in the backup (title and saved text only)" in printed


def test_export_notes_error(tmp_path, capsys):
    assert run(["export", "notes", str(tmp_path), "--out", str(tmp_path / "n")]) == 1
    assert capsys.readouterr().err.startswith("error: report.json not found")


def test_export_all_includes_notes(tmp_path, capsys):
    scan_dir = build_notes_scan_dir(tmp_path / "scan")
    out = tmp_path / "all"
    assert run(["export", "all", str(scan_dir), "--out", str(out)]) == 0
    assert (out / "notes" / "Uncategorized" / "Lista spesa.txt").is_file()
    assert f"1 of 9 exports written to {out}" in capsys.readouterr().out
