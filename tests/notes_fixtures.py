"""Fabricated Samsung Notes backup for tests - no real notes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.scan_fixtures import add_category, entry

SCHEMA = """
CREATE TABLE sdoc (_id INTEGER PRIMARY KEY, UUID TEXT, title TEXT, displayTitle BLOB,
    content BLOB, categoryUUID TEXT, filePath TEXT, isDeleted INTEGER,
    createdAt INTEGER, lastModifiedAt INTEGER);
CREATE TABLE category_tree (UUID TEXT, parentUUID TEXT, displayName TEXT, path TEXT);
CREATE TABLE text_search (sdocUUID TEXT, strippedContent TEXT);
"""

UNCAT, WORK, SUB, OLD, OLDCHILD, TRASH = (
    "cat-uncat", "cat-work", "cat-sub", "cat-old", "cat-oldchild", "cat-trash",
)
# (UUID, parentUUID, displayName, path)
CATEGORIES = [
    (UNCAT, None, "Uncategorized", "uncategorized:///"),
    (WORK, UNCAT, "Lavoro", "x"),
    (SUB, WORK, "Progetti", "x"),
    (OLD, None, "Old notebooks", "old:///"),
    (OLDCHILD, OLD, "Quaderno 2019", "x"),
    (TRASH, None, "Trash", "trash:///"),
]

PDF = b"%PDF-1.4 fake pdf"
JPEG = b"\xff\xd8\xff\xe0 fake jpeg"
PNG = b"\x89PNG\r\n\x1a\n fake png"
T0 = 1700000000000

# (UUID, title, displayTitle, content, categoryUUID, stem, isDeleted, createdAt, lastModifiedAt)
NOTES = [
    ("n-text", "Lista spesa", None, b"Latte\nPane", UNCAT, "1700000000001", 0, T0 + 1000, T0 + 2000),
    ("n-pdf", "Contratto", None, None, WORK, "1700000000002", 0, T0 + 3000, T0 + 4000),
    ("n-mixed", "Verbale", None, b"Riunione", SUB, "1700000000003", 0, T0 + 5000, T0 + 6000),
    ("n-hand", "Schizzo", None, None, OLDCHILD, "1700000000004", 0, T0 + 7000, T0 + 8000),
    ("n-preview", "", b"Solo anteprima", b"Anteprima tronc", UNCAT, "1700000000005", 0, T0 + 9000, T0 + 10000),
    ("n-trash", "Vecchia", None, b"Testo cestinato", TRASH, "1700000000006", 1, T0 + 11000, T0 + 12000),
    ("n-trash-empty", "", None, None, TRASH, "1700000000007", 1, T0 + 13000, T0 + 14000),
]
# (sdocUUID, strippedContent)
INDEX = [("n-text", "Latte\nPane\nUova"), ("n-mixed", "Riunione\ncompleta")]
# stem -> {media file name: bytes}; a stem missing here has no note folder
MEDIA = {
    "1700000000001": {"mediaInfo.dat": b"hash"},
    "1700000000002": {"0@pdf_1.pdf": PDF, "1@page_1000002.spi": b"pen", "mediaInfo.dat": b"hash"},
    "1700000000003": {"1@paste_2.png": PNG, "0@paste_1.jpg": JPEG, "mediaInfo.dat": b"hash"},
    "1700000000004": {"0@page_1000002.spi": b"pen"},
    "1700000000005": {},
}


def _insert(con: sqlite3.Connection, notes) -> None:
    con.executemany(
        "INSERT INTO sdoc (UUID, title, displayTitle, content, categoryUUID, filePath,"
        " isDeleted, createdAt, lastModifiedAt) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (uuid, title, display, content, category,
             f"/data/user/0/com.samsung.android.app.notes/SDocData/{stem}.sdocx",
             deleted, created, modified)
            for uuid, title, display, content, category, stem, deleted, created, modified in notes
        ],
    )


def build_notes_scan_dir(scan_dir: Path, *, notes=NOTES, categories=CATEGORIES, index=INDEX,
                         media=MEDIA, wal_notes=()) -> Path:
    """Write a fake scan output with a Samsung Notes backup.

    ``wal_notes`` are inserted after a checkpoint, so they exist only in
    ``sdoc.db-wal`` (as in the real backup's most recent changes).
    """
    root = scan_dir / "SAMSUNGNOTE" / "sdoc.snmm" / "sdoc.bk"
    db_dir = root / "SmartSwitchRestoreDB"
    db_dir.mkdir(parents=True)
    con = sqlite3.connect(db_dir / "sdoc.db")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO category_tree VALUES (?,?,?,?)", categories)
    _insert(con, notes)
    con.executemany("INSERT INTO text_search VALUES (?,?)", index)
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    saved = {}
    if wal_notes:
        _insert(con, wal_notes)
        con.commit()
        # Closing would checkpoint the WAL away: keep the files as they are now.
        saved = {name: (db_dir / name).read_bytes() for name in ("sdoc.db", "sdoc.db-wal")}
    con.close()
    for name, data in saved.items():
        (db_dir / name).write_bytes(data)
    (db_dir / "sdoc.db-shm").unlink(missing_ok=True)

    for stem, files in media.items():
        folder = root / f"b_{stem}.sdocx" / "media"
        folder.mkdir(parents=True)
        for name, data in files.items():
            (folder / name).write_bytes(data)

    add_category(scan_dir, "SAMSUNGNOTE", [
        entry("sdoc.snmm/sdoc.bk/SmartSwitchRestoreDB/sdoc.db", status="plaintext_passthrough", kind="sqlite"),
        entry("sdoc.snmm/sdoc.bk/SmartSwitchRestoreDB/sdoc.db-wal", status="undecoded"),
    ])
    return scan_dir
