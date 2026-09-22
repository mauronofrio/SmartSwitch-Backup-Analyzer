from __future__ import annotations

import io
import zipfile
from pathlib import Path

from ssba.core.crypto import derive_key
from ssba.core.scanner import list_categories, scan_backup, scan_category
from tests.crypto_helpers import encrypt_dummy_ecb, encrypt_iv_prefixed

FAKE_DUMMY = "AABBCCDDEEFF00112233445566778899AABB"
KEY = derive_key(FAKE_DUMMY)


def _write_history_xml(backup_root: Path) -> None:
    backup_root.mkdir(parents=True, exist_ok=True)
    ciphertext_hex = encrypt_dummy_ecb(FAKE_DUMMY)
    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<BatchInfomationItem xmlns="Kies.Common.Data">
    <BundleInfo><Dummy>{ciphertext_hex}</Dummy></BundleInfo>
</BatchInfomationItem>"""
    (backup_root / "backupHistoryInfo.xml").write_text(xml, encoding="utf-8")


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _build_fake_backup(backup_root: Path) -> None:
    _write_history_xml(backup_root)

    # Category A: a directly-encrypted file (like Notes' sdoc.bk / Calllog's exml)
    plaintext_a = b"<?xml version='1.0'?><FakeCallLogs><entry>fake</entry></FakeCallLogs>"
    (backup_root / "CATEGORY_A").mkdir()
    (backup_root / "CATEGORY_A" / "data.exml").write_bytes(
        encrypt_iv_prefixed(plaintext_a, KEY)
    )

    # Category B: a plain outer zip wrapping one encrypted entry and one
    # already-plaintext entry (like Contact.spbm)
    inner_encrypted = encrypt_iv_prefixed(b'{"contacts": ["fake person"]}', KEY)
    outer_zip = _zip_bytes(
        {
            "Contact.bk": inner_encrypted,
            "readme.txt": b"already plaintext, should pass through untouched",
        }
    )
    (backup_root / "CATEGORY_B").mkdir()
    (backup_root / "CATEGORY_B" / "wrapper.spbm").write_bytes(outer_zip)

    # Category C: data that isn't really encrypted with this scheme at all
    (backup_root / "CATEGORY_C").mkdir()
    (backup_root / "CATEGORY_C" / "mystery.bin").write_bytes(bytes(range(256)) * 4)


def test_list_categories(tmp_path):
    _build_fake_backup(tmp_path)
    assert list_categories(tmp_path) == ["CATEGORY_A", "CATEGORY_B", "CATEGORY_C"]


def test_scan_category_direct_encrypted_file(tmp_path):
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_A", KEY, out_dir)
    assert result.counts()["decrypted"] == 1
    decrypted_path = out_dir / "CATEGORY_A" / "data.exml"
    assert decrypted_path.exists()
    assert b"FakeCallLogs" in decrypted_path.read_bytes()


def test_scan_category_wrapped_zip(tmp_path):
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_B", KEY, out_dir)
    counts = result.counts()
    assert counts["plaintext_passthrough"] == 2  # wrapper.spbm itself + readme.txt
    assert counts["decrypted"] == 1  # Contact.bk
    assert (out_dir / "CATEGORY_B" / "wrapper.spbm" / "Contact.bk").exists()
    assert (out_dir / "CATEGORY_B" / "wrapper.spbm" / "readme.txt").read_bytes() == (
        b"already plaintext, should pass through untouched"
    )


def test_scan_category_undecodable_file(tmp_path):
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_C", KEY, out_dir)
    assert result.counts()["undecoded"] == 1
    assert (out_dir / "CATEGORY_C" / "mystery.bin").read_bytes() == bytes(range(256)) * 4


def test_scan_backup_end_to_end(tmp_path):
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"
    report = scan_backup(tmp_path, out_dir)
    assert [c.category for c in report.categories] == [
        "CATEGORY_A",
        "CATEGORY_B",
        "CATEGORY_C",
    ]
    totals = {"decrypted": 0, "plaintext_passthrough": 0, "undecoded": 0, "error": 0}
    for category in report.categories:
        for status, count in category.counts().items():
            totals[status] += count
    assert totals == {
        "decrypted": 2,
        "plaintext_passthrough": 2,
        "undecoded": 1,
        "error": 0,
    }
