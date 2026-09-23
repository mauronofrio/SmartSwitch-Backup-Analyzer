"""Fabricated Samsung Keyboard clipboard backup for tests - no real data."""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from pathlib import Path

from tests.scan_fixtures import add_category, entry

JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png"
UNKNOWN = b"\x00\x01not-an-image"

# (id, time_stamp ms, type, text, html)
ROWS = [
    (1, 1700000001000, 1, "Ciao <script>alert(1)</script>", None),
    (2, 1700000002000, 4, "testo html", "<b>testo html</b>"),
    (3, 1700000003000, 4, "", "<i>solo html</i>"),
    (4, 1700000004000, 2, None, None),
    (5, 1700000005000, 2, None, None),
    (6, 1700000006000, 9, "strano", None),
]
# clipboard/<folder>/clip -> bytes
IMAGES = {
    "1700000004000": JPEG,
    "1690000000000": JPEG,
    "1690000000500": JPEG,  # same second and type as the one above: name collision
    "1695000000000": PNG,
    "1680000000000": UNKNOWN,
}


def build_clipboard_scan_dir(scan_dir: Path, *, rows=ROWS, images=IMAGES) -> Path:
    with tempfile.TemporaryDirectory() as tmp_name:
        db = Path(tmp_name) / "c.db"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE clip_table (id INTEGER PRIMARY KEY, time_stamp INTEGER,"
            " type INTEGER, text TEXT, html TEXT)"
        )
        con.executemany("INSERT INTO clip_table VALUES (?,?,?,?,?)", rows)
        con.commit()
        con.close()
        db_bytes = db.read_bytes()
    archive = scan_dir / "CLIPBOARD" / "CLIPBOARD.zip" / "clipboard_backup_keyboard.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("BackupClipItem.db", db_bytes)
        for folder, data in images.items():
            zf.writestr(f"clipboard/{folder}/clip", data)
    add_category(scan_dir, "CLIPBOARD", [
        entry("CLIPBOARD.zip/clipboard_backup_keyboard.zip", status="plaintext_passthrough", kind="zip"),
    ])
    return scan_dir
