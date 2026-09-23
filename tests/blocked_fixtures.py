"""Fabricated blocked-number list backup for tests - no real numbers."""

from __future__ import annotations

from pathlib import Path

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
