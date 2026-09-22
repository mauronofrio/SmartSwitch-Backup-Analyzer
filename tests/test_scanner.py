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


def test_scan_category_decrypt_to_zip(tmp_path):
    """Test the real-world case: decrypt a file that decrypts to a zip,
    then recursively extract and process entries inside (like Notes sdoc.bk).
    """
    _write_history_xml(tmp_path)

    # Create a small zip with mixed content
    inner_zip = _zip_bytes(
        {
            "nested.xml": b"<?xml version='1.0'?><doc/>",
            "data.json": b'{"key": "value"}',
        }
    )
    # Encrypt the zip bytes
    encrypted_zip = encrypt_iv_prefixed(inner_zip, KEY)

    (tmp_path / "CATEGORY_D").mkdir()
    (tmp_path / "CATEGORY_D" / "sdoc.bk").write_bytes(encrypted_zip)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_D", KEY, out_dir)
    counts = result.counts()

    # Should have: 1 decrypted (sdoc.bk itself, kind=zip) + 2 plaintext (nested entries)
    # No errors!
    assert counts["decrypted"] == 1, f"expected 1 decrypted, got {counts}"
    assert counts["plaintext_passthrough"] == 2, f"expected 2 plaintext, got {counts}"
    assert counts["error"] == 0, f"expected 0 errors, got {counts}"

    # Verify the nested entries exist and are correctly extracted
    assert (out_dir / "CATEGORY_D" / "sdoc.bk" / "nested.xml").exists()
    assert (out_dir / "CATEGORY_D" / "sdoc.bk" / "data.json").exists()
    assert b"doc" in (out_dir / "CATEGORY_D" / "sdoc.bk" / "nested.xml").read_bytes()


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


def test_scan_category_recurses_into_subdirectories(tmp_path):
    """Finding 1: 10 of 67 real categories (e.g. Photo/) store their content
    only in subdirectories, not directly inside the category folder. The
    scanner must walk recursively and preserve the relative path.
    """
    _write_history_xml(tmp_path)
    category_dir = tmp_path / "Photo"
    nested_dir = category_dir / "sub" / "deeper"
    nested_dir.mkdir(parents=True)
    plaintext = b"just some plain ascii text content here"
    (nested_dir / "pic.txt").write_bytes(encrypt_iv_prefixed(plaintext, KEY))

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "Photo", KEY, out_dir)

    assert result.counts()["decrypted"] == 1, f"file in subdirectory was never scanned: {result}"
    paths = [f.relative_path for f in result.files]
    assert paths == ["sub/deeper/pic.txt"]
    assert (out_dir / "Photo" / "sub" / "deeper" / "pic.txt").exists()


def test_scan_category_zip_slip_dotdot_sanitized(tmp_path):
    """Finding 2: a zip entry named with '../' segments must never escape
    out_dir when its path is built.
    """
    _write_history_xml(tmp_path)
    malicious_zip = _zip_bytes({"../../../PWNED.txt": b"pwned content"})
    (tmp_path / "CATEGORY_E").mkdir()
    (tmp_path / "CATEGORY_E" / "wrapper.zip").write_bytes(malicious_zip)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_E", KEY, out_dir)

    # Nothing must ever land outside out_dir.
    assert not (tmp_path / "PWNED.txt").exists()
    assert not (tmp_path.parent / "PWNED.txt").exists()

    written = list(out_dir.rglob("PWNED.txt"))
    assert len(written) == 1, f"expected exactly one PWNED.txt under out_dir, found {written}"
    assert out_dir.resolve() in written[0].resolve().parents
    assert written[0].read_bytes() == b"pwned content"
    assert result.counts()["error"] == 0


def test_scan_category_zip_slip_backslash_sanitized(tmp_path):
    """Zip entry names should be '/'-separated per spec, but a hostile or
    Windows-built zip might use backslashes; those must be normalized and
    sanitized too, not treated as a literal (and harmless-looking, but
    still wrong) filename component.
    """
    _write_history_xml(tmp_path)
    # 3 "up" segments: entry lives at out_dir/CATEGORY_H/wrapper.zip/<entry>,
    # so 3 ".." would reach tmp_path (one level above out_dir) if the
    # backslashes were not normalized/sanitized - a genuine escape, not a
    # coincidental match of directory depth.
    malicious_zip = _zip_bytes({"..\\..\\..\\evil.txt": b"evil content"})
    (tmp_path / "CATEGORY_H").mkdir()
    (tmp_path / "CATEGORY_H" / "wrapper.zip").write_bytes(malicious_zip)

    out_dir = tmp_path / "out"
    scan_category(tmp_path, "CATEGORY_H", KEY, out_dir)

    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path.parent / "evil.txt").exists()
    written = list(out_dir.rglob("evil.txt"))
    assert len(written) == 1
    assert out_dir.resolve() in written[0].resolve().parents


def test_scan_category_unreadable_file_does_not_crash_scan(tmp_path, monkeypatch):
    """Finding 3: a single unreadable source file (permission error, locked
    file, I/O error) must never abort the whole category/scan.
    """
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"

    bad_file = (tmp_path / "CATEGORY_A" / "data.exml").resolve()
    original_read_bytes = Path.read_bytes

    def flaky_read_bytes(self, *args, **kwargs):
        if self.resolve() == bad_file:
            raise PermissionError("simulated unreadable file")
        return original_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", flaky_read_bytes)

    result = scan_category(tmp_path, "CATEGORY_A", KEY, out_dir)

    assert result.counts()["error"] == 1
    assert result.files[0].status == "error"
    assert "data.exml" in result.files[0].relative_path


def _truncated_zip_bytes() -> bytes:
    good = _zip_bytes({"a.txt": b"hello world, this is a real zip entry"})
    # Chop off the back half: this destroys the end-of-central-directory
    # record while leaving the local-file-header zip magic at the start
    # intact, so sniff_kind still calls it a zip but zipfile.ZipFile()
    # cannot open it.
    corrupt = good[: len(good) // 2]
    assert corrupt.startswith(b"PK\x03\x04")
    return corrupt


def test_scan_category_corrupt_raw_zip_single_result_and_fallback_write(tmp_path):
    """Finding 4, scenario 1: a raw file has zip magic bytes but a corrupt
    body. Exactly one FileResult must be recorded for it, and its bytes
    must be written somewhere rather than silently lost.
    """
    _write_history_xml(tmp_path)
    corrupt = _truncated_zip_bytes()
    (tmp_path / "CATEGORY_F").mkdir()
    (tmp_path / "CATEGORY_F" / "broken.zip").write_bytes(corrupt)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_F", KEY, out_dir)

    matching = [f for f in result.files if f.relative_path == "broken.zip"]
    assert len(matching) == 1, f"expected exactly one FileResult, got {matching}"
    written = out_dir / "CATEGORY_F" / "broken.zip"
    assert written.exists(), "corrupt zip's original bytes must be written, not discarded"
    assert written.read_bytes() == corrupt


def test_scan_category_corrupt_decrypted_zip_single_result_and_fallback_write(tmp_path):
    """Finding 4, scenario 2: the file decrypts successfully, and the
    decrypted result is a zip, but that zip is itself corrupt.
    """
    _write_history_xml(tmp_path)
    corrupt_inner = _truncated_zip_bytes()
    encrypted = encrypt_iv_prefixed(corrupt_inner, KEY)
    (tmp_path / "CATEGORY_G").mkdir()
    (tmp_path / "CATEGORY_G" / "sdoc.bk").write_bytes(encrypted)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_G", KEY, out_dir)

    matching = [f for f in result.files if f.relative_path == "sdoc.bk"]
    assert len(matching) == 1, f"expected exactly one FileResult, got {matching}"
    written = out_dir / "CATEGORY_G" / "sdoc.bk"
    assert written.exists(), "corrupt decrypted zip bytes must be written, not discarded"
