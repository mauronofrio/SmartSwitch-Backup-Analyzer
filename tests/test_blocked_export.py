from __future__ import annotations

from pathlib import Path

import pytest

from ssba.core.parsers.blocked import BlockedExportError, export_blocked_numbers
from tests.scan_fixtures import add_category, entry

NAME = "com.samsung.android.app.telephonyui.callsettings.api.entity.BlockNumberItem.csv"
PHOTO_RING = "com.samsung.android.app.telephonyui.callsettings.api.entity.PhotoRingBlockNumberItem.csv"
CSV = (
    "_id\treject_number\treject_match\n"
    "4\t+393330000004\t0\n"
    "3\tSpamCo\t0\n"
    "2\t\t0\n"
    "1\t+39333\t1\n"
    "0\t+393330000000\t0\n"
)


def build_blocked_scan_dir(scan_dir: Path, csv_text: str = CSV) -> Path:
    folder = scan_dir / "CALLOGSETTING" / "CALLOGSETTING.zip"
    folder.mkdir(parents=True)
    (folder / NAME).write_text(csv_text, encoding="utf-8")
    (folder / PHOTO_RING).write_text("_id\treject_number\n0\t+390000000999\n", encoding="utf-8")
    add_category(scan_dir, "CALLOGSETTING", [
        entry(f"CALLOGSETTING.zip/{NAME}", kind="text"),
        entry(f"CALLOGSETTING.zip/{PHOTO_RING}", kind="text"),
    ])
    return scan_dir


def _export(tmp_path, csv_text=CSV):
    out = tmp_path / "export" / "blocked-numbers.txt"
    return export_blocked_numbers(build_blocked_scan_dir(tmp_path / "scan", csv_text), out), out


def test_numbers_are_written_in_id_order(tmp_path):
    result, out = _export(tmp_path)
    assert out.read_text(encoding="utf-8") == (
        "+393330000000\n+39333\t(match type 1)\nSpamCo\n+393330000004\n"
    )
    assert (result.exported, result.skipped) == (4, 1)


def test_photo_ring_list_is_not_exported(tmp_path):
    _, out = _export(tmp_path)
    assert "+390000000999" not in out.read_text(encoding="utf-8")


def test_non_integer_ids_come_last_in_file_order(tmp_path):
    csv_text = "_id\treject_number\treject_match\nx\tB\t0\n5\tA\t0\ny\tC\t0\n"
    _, out = _export(tmp_path, csv_text)
    assert out.read_text(encoding="utf-8") == "A\nB\nC\n"


def test_missing_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(BlockedExportError, match="CALLOGSETTING"):
        export_blocked_numbers(tmp_path, tmp_path / "b.txt")


def test_no_list_raises(tmp_path):
    add_category(tmp_path, "CALLOGSETTING", [])
    with pytest.raises(BlockedExportError, match="no blocked-number list"):
        export_blocked_numbers(tmp_path, tmp_path / "b.txt")


def test_list_without_numbers_raises(tmp_path):
    with pytest.raises(BlockedExportError, match="no blocked numbers"):
        _export(tmp_path, "_id\treject_number\treject_match\n0\t\t0\n")


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_blocked_scan_dir(tmp_path / "scan")
    out = tmp_path / "b.txt"
    out.mkdir()
    with pytest.raises(BlockedExportError, match="cannot write"):
        export_blocked_numbers(scan_dir, out)
