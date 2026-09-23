from __future__ import annotations

import zipfile
from datetime import datetime

import pytest

from ssba.core.parsers.clipboard import ClipboardExportError, export_clipboard
from ssba.core.parsers.html_page import format_time
from tests.clipboard_fixtures import JPEG, PNG, UNKNOWN, build_clipboard_scan_dir
from tests.scan_fixtures import add_category, entry


def _stamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d_%H-%M-%S")


def _export(tmp_path, **kwargs):
    out = tmp_path / "export" / "clipboard"
    return export_clipboard(build_clipboard_scan_dir(tmp_path / "scan", **kwargs), out), out


def test_counts(tmp_path):
    result, _ = _export(tmp_path)
    assert (result.texts, result.images, result.missing_images, result.other_types) == (3, 5, 1, 1)


def test_images_are_written_with_dated_names_and_exact_bytes(tmp_path):
    _, out = _export(tmp_path)
    images = out / "images"
    assert (images / f"{_stamp(1700000004000)}.jpg").read_bytes() == JPEG
    assert (images / f"{_stamp(1690000000000)}.jpg").read_bytes() == JPEG
    assert (images / f"{_stamp(1690000000500)}_2.jpg").read_bytes() == JPEG
    assert (images / f"{_stamp(1695000000000)}.png").read_bytes() == PNG
    assert (images / f"{_stamp(1680000000000)}.bin").read_bytes() == UNKNOWN
    assert len(list(images.iterdir())) == 5


def test_page_lists_entries_in_time_order_with_relative_images(tmp_path):
    _, out = _export(tmp_path)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert f'src="images/{_stamp(1700000004000)}.jpg"' in html
    assert f'href="images/{_stamp(1680000000000)}.bin"' in html
    positions = [html.index(format_time(ms / 1000)) for ms in (1680000000000, 1690000000000, 1700000001000, 1700000006000)]
    assert positions == sorted(positions)


def test_texts_are_escaped_and_html_only_rows_show_their_source(tmp_path):
    _, out = _export(tmp_path)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Ciao &lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script" not in html
    assert "&lt;i&gt;solo html&lt;/i&gt;" in html
    assert "HTML source" in html
    assert "Image missing from the backup" in html
    assert "Type 9" in html


def test_image_folder_that_is_not_a_timestamp_is_undated(tmp_path):
    result, out = _export(tmp_path, rows=[(1, 1700000001000, 1, "x", None)], images={"abc": JPEG})
    assert result.images == 1
    assert (out / "images" / "clip-1.jpg").read_bytes() == JPEG


def test_missing_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(ClipboardExportError, match="CLIPBOARD"):
        export_clipboard(tmp_path, tmp_path / "out")


def test_no_clipboard_archive_raises(tmp_path):
    add_category(tmp_path, "CLIPBOARD", [])
    with pytest.raises(ClipboardExportError, match="no clipboard backup"):
        export_clipboard(tmp_path, tmp_path / "out")


def test_corrupt_database_raises(tmp_path):
    archive = tmp_path / "CLIPBOARD" / "clipboard_backup_keyboard.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("BackupClipItem.db", b"not sqlite")
    add_category(tmp_path, "CLIPBOARD", [entry("clipboard_backup_keyboard.zip")])
    with pytest.raises(ClipboardExportError, match="cannot read"):
        export_clipboard(tmp_path, tmp_path / "out")


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_clipboard_scan_dir(tmp_path / "scan")
    out = tmp_path / "out"
    out.write_text("a file, not a directory", encoding="utf-8")
    with pytest.raises(ClipboardExportError, match="cannot write"):
        export_clipboard(scan_dir, out)
