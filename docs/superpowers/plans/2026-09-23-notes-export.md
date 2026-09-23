# Samsung Notes Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ssba export notes`, writing each Samsung Note as a `.txt` and/or its attachment files inside folders that mirror Samsung Notes' folders, and add it to `ssba export all`.

**Architecture:** One module, `src/ssba/core/parsers/notes.py`: `read_notes` copies `sdoc.db` (plus its WAL) to a temporary directory, reads notes, folders and indexed text, and locates each note's unpacked `b_<stem>.sdocx/media/`; `export_notes` turns every `Note` into safely named files. The CLI adds `notes` to its export table.

**Tech Stack:** Python 3.10+ stdlib (`sqlite3`, `shutil`, `tempfile`, `os`, `re`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-23-notes-export-design.md`

## Global Constraints

- Python 3.10+, no new dependency. `core/` never prints; only `cli/` does.
- No real personal data in the repository, tests or fixtures.
- No attribution lines in commit messages; nothing pushed; work directly on `master`.
- The original scan output is never modified (the database is read from a copy).
- Run tests with `python -m pytest` from `D:/SmartSwitch-Backup-Analyzer`; pass paths to Python as `D:/...`.
- Create/edit files with editor tools, never through scripts or heredocs; escape sequences in Python literals (`\xff`, `\n`, `\r`, `\x00`…) must stay escape text in the files.

---

### Task 1: Reading notes

**Files:**
- Create: `src/ssba/core/parsers/notes.py` (reading part)
- Create: `tests/notes_fixtures.py`
- Create: `tests/test_notes_read.py`

**Interfaces:**
- Consumes: `category_files`, `ScanReportError` (`ssba.core.parsers.scan_report`); `format_time` (`ssba.core.parsers.html_page`); `add_category`, `entry` (`tests/scan_fixtures.py`).
- Produces:
  - `ssba.core.parsers.notes.NotesExportError(Exception)`
  - `ssba.core.parsers.notes.Note` dataclass (`title: str`, `folder: tuple[str, ...]`, `text: str | None`, `text_source: str | None`, `attachments: list[Path]`, `created: float | None`, `modified: float | None`, `deleted: bool`, `file_missing: bool`, `has_drawings: bool`)
  - `ssba.core.parsers.notes.read_notes(scan_dir: Path) -> list[Note]`
  - `tests.notes_fixtures.build_notes_scan_dir(scan_dir: Path, *, notes=NOTES, categories=CATEGORIES, index=INDEX, media=MEDIA, wal_notes=()) -> Path` and constants `T0`, `PDF`, `JPEG`, `PNG`, `UNCAT`, `WORK`, `SUB`, `OLDCHILD`, `TRASH`, `NOTES`, `INDEX`, `MEDIA`, `CATEGORIES`.

- [ ] **Step 1: Write the fixtures** — `tests/notes_fixtures.py`:

```python
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
```

- [ ] **Step 2: Write the failing tests** — `tests/test_notes_read.py`:

```python
from __future__ import annotations

import sqlite3

import pytest

from ssba.core.parsers.html_page import format_time
from ssba.core.parsers.notes import NotesExportError, read_notes
from tests.notes_fixtures import T0, UNCAT, build_notes_scan_dir
from tests.scan_fixtures import add_category

DB = ("SAMSUNGNOTE", "sdoc.snmm", "sdoc.bk", "SmartSwitchRestoreDB", "sdoc.db")


def _read(tmp_path, **kwargs):
    return {n.title: n for n in read_notes(build_notes_scan_dir(tmp_path / "scan", **kwargs))}


def test_notes_are_read_in_creation_order_with_title_fallbacks(tmp_path):
    notes = read_notes(build_notes_scan_dir(tmp_path / "scan"))
    untitled = f"Untitled {format_time((T0 + 13000) / 1000)[:10]}"
    assert [n.title for n in notes] == [
        "Lista spesa", "Contratto", "Verbale", "Schizzo", "Solo anteprima", "Vecchia", untitled,
    ]


def test_folders_follow_the_category_tree(tmp_path):
    notes = _read(tmp_path)
    assert notes["Lista spesa"].folder == ("Uncategorized",)
    assert notes["Contratto"].folder == ("Lavoro",)
    assert notes["Verbale"].folder == ("Lavoro", "Progetti")
    assert notes["Schizzo"].folder == ("Old notebooks", "Quaderno 2019")
    assert notes["Vecchia"].folder == ("Trash",)


def test_unknown_category_goes_to_uncategorized(tmp_path):
    note = ("n", "Orfana", None, b"x", "no-such-category", "1", 0, T0, T0)
    notes = _read(tmp_path, notes=[note], index=[], media={})
    assert notes["Orfana"].folder == ("Uncategorized",)


def test_parent_cycle_and_empty_folder_name_do_not_hang(tmp_path):
    categories = [("a", "b", "", "x"), ("b", "a", "B", "x")]
    note = ("n", "Nota", None, b"x", "a", "1", 0, T0, T0)
    notes = _read(tmp_path, notes=[note], categories=categories, index=[], media={})
    assert notes["Nota"].folder == ("B", "Untitled folder")


def test_text_comes_from_the_index_then_the_preview(tmp_path):
    notes = _read(tmp_path)
    assert (notes["Lista spesa"].text, notes["Lista spesa"].text_source) == ("Latte\nPane\nUova", "index")
    assert (notes["Solo anteprima"].text, notes["Solo anteprima"].text_source) == ("Anteprima tronc", "preview")
    assert (notes["Contratto"].text, notes["Contratto"].text_source) == (None, None)


def test_attachments_are_ordered_and_exclude_media_info_and_drawings(tmp_path):
    notes = _read(tmp_path)
    assert [p.name for p in notes["Verbale"].attachments] == ["0@paste_1.jpg", "1@paste_2.png"]
    assert [p.name for p in notes["Contratto"].attachments] == ["0@pdf_1.pdf"]
    assert notes["Lista spesa"].attachments == []
    assert notes["Contratto"].has_drawings is True
    assert notes["Schizzo"].has_drawings is True
    assert notes["Verbale"].has_drawings is False


def test_media_without_an_index_prefix_comes_last(tmp_path):
    note = ("n", "Nota", None, None, UNCAT, "1", 0, T0, T0)
    media = {"1": {"cover.jpg": b"c", "2@b.jpg": b"b", "10@a.jpg": b"a"}}
    notes = _read(tmp_path, notes=[note], index=[], media=media)
    assert [p.name for p in notes["Nota"].attachments] == ["2@b.jpg", "10@a.jpg", "cover.jpg"]


def test_missing_note_folder_is_flagged(tmp_path):
    notes = _read(tmp_path)
    assert notes["Vecchia"].file_missing is True
    assert notes["Vecchia"].deleted is True
    assert notes["Solo anteprima"].file_missing is False


def test_unsafe_file_path_stem_is_never_followed(tmp_path):
    note = ("n", "Nota", None, b"x", UNCAT, "y z", 0, T0, T0)
    notes = _read(tmp_path, notes=[note], index=[], media={"y z": {"0@pdf_1.pdf": b"%PDF"}})
    assert notes["Nota"].file_missing is True
    assert notes["Nota"].attachments == []


def test_rows_only_in_the_wal_are_read_and_the_original_is_untouched(tmp_path):
    wal_note = ("n-wal", "Solo nel WAL", None, b"x", UNCAT, "1700000000009", 0, T0 + 20000, T0 + 21000)
    scan_dir = build_notes_scan_dir(tmp_path / "scan", wal_notes=[wal_note])
    db_dir = scan_dir.joinpath(*DB).parent
    before = {p.name: p.read_bytes() for p in db_dir.iterdir()}
    assert "Solo nel WAL" in [n.title for n in read_notes(scan_dir)]
    assert {p.name: p.read_bytes() for p in db_dir.iterdir()} == before


def test_a_file_that_is_not_a_wal_is_ignored(tmp_path):
    scan_dir = build_notes_scan_dir(tmp_path / "scan")
    scan_dir.joinpath(*DB).with_name("sdoc.db-wal").write_bytes(b"garbage")
    assert len(read_notes(scan_dir)) == 7


def test_missing_table_raises(tmp_path):
    scan_dir = build_notes_scan_dir(tmp_path / "scan")
    con = sqlite3.connect(scan_dir.joinpath(*DB))
    con.execute("DROP TABLE category_tree")
    con.commit()
    con.close()
    with pytest.raises(NotesExportError, match="category_tree"):
        read_notes(scan_dir)


def test_corrupt_database_raises(tmp_path):
    scan_dir = build_notes_scan_dir(tmp_path / "scan")
    scan_dir.joinpath(*DB).write_bytes(b"not a database at all" * 100)
    with pytest.raises(NotesExportError, match="cannot read"):
        read_notes(scan_dir)


def test_no_database_raises(tmp_path):
    add_category(tmp_path, "SAMSUNGNOTE", [])
    with pytest.raises(NotesExportError, match="no Samsung Notes database"):
        read_notes(tmp_path)


def test_missing_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(NotesExportError, match="SAMSUNGNOTE"):
        read_notes(tmp_path)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_notes_read.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'ssba.core.parsers.notes'`.

- [ ] **Step 4: Implement** — `src/ssba/core/parsers/notes.py`:

```python
"""Export Samsung Notes: text as .txt, attachments as files, folders as folders."""

from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ssba.core.parsers.html_page import format_time
from ssba.core.parsers.scan_report import ScanReportError, category_files

_DB_NAME = "sdoc.db"
_DB_FOLDER = "SmartSwitchRestoreDB"
_WAL_MAGIC = (b"\x37\x7f\x06\x82", b"\x37\x7f\x06\x83")
_UNCATEGORIZED_PATH = "uncategorized:///"
_UNCATEGORIZED = "Uncategorized"
_TRASH = "Trash"
# A note folder is b_<stem>.sdocx; anything else in filePath is never followed.
_SAFE_STEM = re.compile(r"[0-9A-Za-z_.-]+")
_MEDIA_INFO = "mediainfo.dat"
_DRAWING_SUFFIX = ".spi"


class NotesExportError(Exception):
    """Raised when the Samsung Notes cannot be exported."""


@dataclass
class Note:
    title: str
    folder: tuple[str, ...]
    text: str | None
    text_source: str | None  # "index", "preview" or None
    attachments: list[Path]
    created: float | None  # Unix seconds
    modified: float | None
    deleted: bool
    file_missing: bool
    has_drawings: bool


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _seconds(ms) -> float | None:
    return ms / 1000 if isinstance(ms, (int, float)) and ms > 0 else None


def _is_set(value) -> bool:
    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return False


def _find_database(scan_dir: Path) -> Path:
    try:
        paths = category_files(scan_dir, "SAMSUNGNOTE")
    except ScanReportError as exc:
        raise NotesExportError(str(exc)) from exc
    for path in paths:
        if path.name == _DB_NAME and path.parent.name == _DB_FOLDER:
            return path
    raise NotesExportError("no Samsung Notes database found in the scan output")


def _copy_database(db: Path, tmp: Path) -> Path:
    """Copy the database and, if valid, its WAL (Phase 1 reports it as undecoded)."""
    copy = tmp / _DB_NAME
    shutil.copyfile(db, copy)
    wal = db.with_name(_DB_NAME + "-wal")
    if wal.is_file():
        with wal.open("rb") as fh:
            if fh.read(4) in _WAL_MAGIC:
                shutil.copyfile(wal, tmp / (_DB_NAME + "-wal"))
    return copy


def _folders(con: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    rows = {
        row["UUID"]: row
        for row in con.execute("SELECT UUID, parentUUID, displayName, path FROM category_tree")
    }

    def resolve(uuid: str) -> tuple[str, ...]:
        chain, seen, current = [], set(), uuid
        while current in rows and current not in seen:
            seen.add(current)
            chain.append(rows[current])
            current = rows[current]["parentUUID"]
        chain.reverse()  # root first
        names = [_text(row["displayName"]).strip() or "Untitled folder" for row in chain]
        if len(chain) > 1 and _text(chain[0]["path"]) == _UNCATEGORIZED_PATH:
            names = names[1:]  # user folders sit at the top level
        return tuple(names)

    return {uuid: resolve(uuid) for uuid in rows}


def _note_folder(root: Path, file_path) -> Path | None:
    name = _text(file_path).replace("\\", "/").rsplit("/", 1)[-1]
    stem = name[: -len(".sdocx")] if name.lower().endswith(".sdocx") else name
    if not _SAFE_STEM.fullmatch(stem):
        return None
    folder = root / f"b_{stem}.sdocx"
    return folder if folder.is_dir() else None


def _media_order(path: Path) -> tuple:
    prefix, at, _ = path.name.partition("@")
    return (0, int(prefix), path.name) if at and prefix.isdigit() else (1, 0, path.name)


def _media(folder: Path) -> tuple[list[Path], bool]:
    media = folder / "media"
    files = [p for p in media.iterdir() if p.is_file()] if media.is_dir() else []
    drawings = any(p.suffix.lower() == _DRAWING_SUFFIX for p in files)
    attachments = [
        p for p in files
        if p.name.lower() != _MEDIA_INFO and p.suffix.lower() != _DRAWING_SUFFIX
    ]
    return sorted(attachments, key=_media_order), drawings


def _read(con: sqlite3.Connection, root: Path) -> list[Note]:
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("sdoc", "category_tree"):
        if table not in tables:
            raise NotesExportError(f"the Samsung Notes database has no {table} table")
    folders = _folders(con)
    index: dict[str, str] = {}
    if "text_search" in tables:
        for row in con.execute("SELECT sdocUUID, strippedContent FROM text_search"):
            text = _text(row["strippedContent"])
            if text.strip():
                index.setdefault(row["sdocUUID"], text)

    notes = []
    for row in con.execute(
        "SELECT UUID, title, displayTitle, content, categoryUUID, filePath, isDeleted,"
        " createdAt, lastModifiedAt FROM sdoc ORDER BY createdAt, _id"
    ):
        created = _seconds(row["createdAt"])
        title = " ".join(_text(row["title"]).split()) or " ".join(_text(row["displayTitle"]).split())
        if not title:
            day = format_time(created)[:10]
            title = f"Untitled {day}" if day else "Untitled note"
        if row["UUID"] in index:
            text, source = index[row["UUID"]], "index"
        else:
            preview = _text(row["content"])
            text, source = (preview, "preview") if preview.strip() else (None, None)
        note_folder = _note_folder(root, row["filePath"])
        attachments, drawings = _media(note_folder) if note_folder else ([], False)
        deleted = _is_set(row["isDeleted"])
        folder = (_TRASH,) if deleted else folders.get(row["categoryUUID"], (_UNCATEGORIZED,))
        notes.append(Note(
            title=title,
            folder=folder,
            text=text,
            text_source=source,
            attachments=attachments,
            created=created,
            modified=_seconds(row["lastModifiedAt"]),
            deleted=deleted,
            file_missing=note_folder is None,
            has_drawings=drawings,
        ))
    return notes


def read_notes(scan_dir: Path) -> list[Note]:
    db = _find_database(scan_dir)
    root = db.parent.parent
    try:
        with tempfile.TemporaryDirectory() as tmp_name:
            con = sqlite3.connect(_copy_database(db, Path(tmp_name)))
            try:
                con.row_factory = sqlite3.Row
                return _read(con, root)
            finally:
                con.close()
    except (OSError, sqlite3.Error) as exc:
        raise NotesExportError(f"cannot read {db}: {exc}") from exc
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_notes_read.py -v`, then `python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ssba/core/parsers/notes.py tests/notes_fixtures.py tests/test_notes_read.py
git commit -m "feat: read Samsung Notes, their folders, text and attachments"
```

---

### Task 2: Writing notes

**Files:**
- Modify: `src/ssba/core/parsers/notes.py` (append the writing part; add `import os`)
- Create: `tests/test_notes_export.py`

**Interfaces:**
- Consumes: `Note`, `read_notes`, `NotesExportError` (Task 1); fixtures from `tests/notes_fixtures.py`.
- Produces:
  - `ssba.core.parsers.notes.safe_name(text: str) -> str`
  - `ssba.core.parsers.notes.NotesExportResult` dataclass (`notes`, `text_notes`, `preview_only`, `attachments`, `handwriting_only`, `missing_files`, `with_drawings`, `trashed`, all `int = 0`)
  - `ssba.core.parsers.notes.export_notes(scan_dir: Path, out_dir: Path) -> NotesExportResult`

- [ ] **Step 1: Write the failing tests** — `tests/test_notes_export.py`:

```python
from __future__ import annotations

import os

import pytest

from ssba.core.parsers.html_page import format_time
from ssba.core.parsers.notes import NotesExportError, export_notes, safe_name
from tests.notes_fixtures import JPEG, PDF, PNG, T0, UNCAT, build_notes_scan_dir

PREVIEW = "Only a preview of this note's text was kept; it may be cut short."
TRASHED = "Deleted note from the Samsung Notes trash; its file is not in the backup."


def _export(tmp_path, **kwargs):
    out = tmp_path / "notes"
    result = export_notes(build_notes_scan_dir(tmp_path / "scan", **kwargs), out)
    return result, out


def _files(out):
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())


def test_every_note_becomes_files_in_its_folder(tmp_path):
    _, out = _export(tmp_path)
    untitled = f"Untitled {format_time((T0 + 13000) / 1000)[:10]}"
    assert _files(out) == sorted([
        "Uncategorized/Lista spesa.txt",
        "Uncategorized/Solo anteprima.txt",
        "Lavoro/Contratto.pdf",
        "Lavoro/Progetti/Verbale.txt",
        "Lavoro/Progetti/Verbale.jpg",
        "Lavoro/Progetti/Verbale_2.png",
        "Old notebooks/Quaderno 2019/Schizzo.txt",
        "Trash/Vecchia.txt",
        f"Trash/{untitled}.txt",
    ])


def test_text_files_hold_the_full_text(tmp_path):
    _, out = _export(tmp_path)
    assert (out / "Uncategorized/Lista spesa.txt").read_bytes() == b"Latte\nPane\nUova\n"
    assert (out / "Lavoro/Progetti/Verbale.txt").read_bytes() == b"Riunione\ncompleta\n"


def test_placeholders_and_headers(tmp_path):
    _, out = _export(tmp_path)
    read = lambda rel: (out / rel).read_text(encoding="utf-8")
    assert read("Old notebooks/Quaderno 2019/Schizzo.txt") == (
        "(This note contains only handwriting or drawings, which cannot be exported.)\n"
    )
    assert read("Uncategorized/Solo anteprima.txt") == f"{PREVIEW}\n\nAnteprima tronc\n"
    assert read("Trash/Vecchia.txt") == (
        f"{TRASHED}\nCreated: {format_time((T0 + 11000) / 1000)}\n"
        f"Modified: {format_time((T0 + 12000) / 1000)}\n{PREVIEW}\n\nTesto cestinato\n"
    )
    untitled = f"Untitled {format_time((T0 + 13000) / 1000)[:10]}"
    assert read(f"Trash/{untitled}.txt").endswith("\n\n(no text)\n")


def test_attachments_are_byte_identical(tmp_path):
    _, out = _export(tmp_path)
    assert (out / "Lavoro/Contratto.pdf").read_bytes() == PDF
    assert (out / "Lavoro/Progetti/Verbale.jpg").read_bytes() == JPEG
    assert (out / "Lavoro/Progetti/Verbale_2.png").read_bytes() == PNG


def test_files_carry_the_note_modification_time(tmp_path):
    _, out = _export(tmp_path)
    assert abs(os.path.getmtime(out / "Uncategorized/Lista spesa.txt") - (T0 + 2000) / 1000) < 1
    assert abs(os.path.getmtime(out / "Lavoro/Contratto.pdf") - (T0 + 4000) / 1000) < 1


def test_counts(tmp_path):
    result, _ = _export(tmp_path)
    assert (result.notes, result.text_notes, result.preview_only, result.attachments) == (7, 4, 2, 3)
    assert (result.handwriting_only, result.missing_files, result.with_drawings, result.trashed) == (1, 2, 2, 2)


def test_same_titles_in_one_folder_do_not_overwrite_each_other(tmp_path):
    notes = [
        ("a", "Doppio", None, b"primo", UNCAT, "1", 0, T0, T0),
        ("b", "Doppio", None, None, UNCAT, "2", 0, T0 + 1, T0),
        ("c", "doppio", None, b"terzo", UNCAT, "3", 0, T0 + 2, T0),
    ]
    _, out = _export(tmp_path, notes=notes, index=[], media={"2": {"0@pdf_1.pdf": PDF}})
    assert _files(out) == sorted([
        "Uncategorized/Doppio.txt", "Uncategorized/Doppio (2).pdf", "Uncategorized/doppio (3).txt",
    ])


def test_attachment_named_like_the_text_file_gets_its_own_name(tmp_path):
    notes = [("a", "Nota", None, b"testo", UNCAT, "1", 0, T0, T0)]
    _, out = _export(tmp_path, notes=notes, index=[], media={"1": {"0@files_1.txt": b"allegato"}})
    assert _files(out) == ["Uncategorized/Nota.txt", "Uncategorized/Nota_attachment.txt"]
    assert (out / "Uncategorized/Nota_attachment.txt").read_bytes() == b"allegato"


def test_line_breaks_are_normalized(tmp_path):
    notes = [("a", "Nota", None, None, UNCAT, "1", 0, T0, T0)]
    _, out = _export(tmp_path, notes=notes, index=[("a", "uno\r\ndue\rtre")], media={})
    assert (out / "Uncategorized/Nota.txt").read_bytes() == b"uno\ndue\ntre\n"


@pytest.mark.parametrize("raw, safe", [
    ('a<b>c:d"e/f\\g|h?i*j', "a_b_c_d_e_f_g_h_i_j"),
    ("  Nota.  ", "Nota"),
    ("", "Untitled"),
    ("...", "Untitled"),
    ("a\x01b", "a_b"),
    ("CON", "_CON"),
    ("con.txt", "_con.txt"),
    ("Lpt9", "_Lpt9"),
    ("x" * 150, "x" * 100),
])
def test_safe_name(raw, safe):
    assert safe_name(raw) == safe


def test_unsafe_titles_and_folders_are_made_safe(tmp_path):
    categories = [(UNCAT, None, "Uncategorized", "uncategorized:///"), ("w", UNCAT, "A/B", "x")]
    notes = [("a", "Q: 1/2?", None, b"x", "w", "1", 0, T0, T0)]
    _, out = _export(tmp_path, notes=notes, categories=categories, index=[], media={})
    assert _files(out) == ["A_B/Q_ 1_2_.txt"]


def test_no_notes_raises(tmp_path):
    with pytest.raises(NotesExportError, match="has no notes"):
        _export(tmp_path, notes=[], index=[], media={})


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_notes_scan_dir(tmp_path / "scan")
    out = tmp_path / "notes"
    out.write_text("a file, not a directory", encoding="utf-8")
    with pytest.raises(NotesExportError, match="cannot export"):
        export_notes(scan_dir, out)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_notes_export.py -v`
Expected: collection error `ImportError: cannot import name 'export_notes'`.

- [ ] **Step 3: Implement.** Add `import os` to the imports of `src/ssba/core/parsers/notes.py` and append:

```python
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_NAME = 100
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_PREVIEW_NOTE = "Only a preview of this note's text was kept; it may be cut short."
_MISSING_DELETED = "Deleted note from the Samsung Notes trash; its file is not in the backup."
_MISSING = "This note's file is not in the backup."
_NO_TEXT = "(no text)"
_HANDWRITING = "(This note contains only handwriting or drawings, which cannot be exported.)"


@dataclass
class NotesExportResult:
    notes: int = 0
    text_notes: int = 0
    preview_only: int = 0
    attachments: int = 0
    handwriting_only: int = 0
    missing_files: int = 0
    with_drawings: int = 0
    trashed: int = 0


def safe_name(text: str) -> str:
    """A file or folder name every common file system (Windows included) accepts."""
    name = _UNSAFE_CHARS.sub("_", text).strip().rstrip(". ")
    name = name[:_MAX_NAME].rstrip(". ")
    if not name:
        return "Untitled"
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    return name


def _plan(note: Note, taken: set[str]) -> tuple[str | None, list[tuple[str, Path]]]:
    """File names for ``note`` that no other note in the folder uses yet.

    Each note also claims its base name (stored as "<base>/", which no file
    name can equal), so two notes never look like one: "Doppio.txt" and
    "Doppio (2).pdf", not "Doppio.txt" and "Doppio.pdf".
    """
    base = safe_name(note.title)
    n = 1
    while True:
        stem = base if n == 1 else f"{base} ({n})"
        marker = stem.lower() + "/"
        txt = f"{stem}.txt" if note.text is not None or not note.attachments else None
        files = []
        for i, source in enumerate(note.attachments):
            ext = source.suffix.lower()
            name = f"{stem}{'' if i == 0 else f'_{i + 1}'}{ext}"
            if txt is not None and name.lower() == txt.lower():
                name = f"{stem}_attachment{ext}"
            files.append((name, source))
        wanted = ([txt] if txt else []) + [name for name, _ in files]
        if marker not in taken and not any(name.lower() in taken for name in wanted):
            taken.add(marker)
            taken.update(name.lower() for name in wanted)
            return txt, files
        n += 1


def _txt_body(note: Note) -> str:
    header = []
    if note.file_missing:
        header.append(_MISSING_DELETED if note.deleted else _MISSING)
        header.append(f"Created: {format_time(note.created) or 'unknown'}")
        header.append(f"Modified: {format_time(note.modified) or 'unknown'}")
    if note.text_source == "preview":
        header.append(_PREVIEW_NOTE)
    if note.text is not None:
        text = note.text.replace("\r\n", "\n").replace("\r", "\n")
    else:
        text = _NO_TEXT if note.file_missing else _HANDWRITING
    body = text if text.endswith("\n") else text + "\n"
    return "\n".join(header) + "\n\n" + body if header else body


def _set_mtime(path: Path, seconds: float | None) -> None:
    if seconds:
        try:
            os.utime(path, (seconds, seconds))
        except (OverflowError, ValueError):
            pass


def export_notes(scan_dir: Path, out_dir: Path) -> NotesExportResult:
    notes = read_notes(scan_dir)
    if not notes:
        raise NotesExportError("the Samsung Notes database has no notes")

    result = NotesExportResult()
    taken_by_folder: dict[tuple[str, ...], set[str]] = {}
    for note in notes:
        parts = tuple(safe_name(part) for part in note.folder)
        folder = out_dir.joinpath(*parts)
        # Windows folders are case-insensitive: share the used names.
        taken = taken_by_folder.setdefault(tuple(p.lower() for p in parts), set())
        txt, files = _plan(note, taken)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if txt is not None:
                (folder / txt).write_text(_txt_body(note), encoding="utf-8", newline="\n")
                _set_mtime(folder / txt, note.modified)
            for name, source in files:
                shutil.copyfile(source, folder / name)
                _set_mtime(folder / name, note.modified)
        except OSError as exc:
            raise NotesExportError(f"cannot export {note.title!r}: {exc}") from exc

        result.notes += 1
        result.text_notes += note.text is not None
        result.preview_only += note.text_source == "preview"
        result.attachments += len(files)
        result.handwriting_only += (
            not note.file_missing and note.text is None and not note.attachments
        )
        result.missing_files += note.file_missing
        result.with_drawings += note.has_drawings
        result.trashed += note.deleted
    return result
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_notes_export.py -v`, then `python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ssba/core/parsers/notes.py tests/test_notes_export.py
git commit -m "feat: export Samsung Notes as text files and attachments in folders"
```

---

### Task 3: CLI

**Files:**
- Modify: `src/ssba/cli/main.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `export_notes`, `NotesExportError` (Tasks 1-2); `build_notes_scan_dir` (`tests/notes_fixtures.py`).
- Produces: `ssba export notes <scan_dir> --out <dir>`; `export all` runs 9 kinds.

- [ ] **Step 1: Write the failing tests.** In `tests/test_cli.py` add the import `from tests.notes_fixtures import build_notes_scan_dir`, then:

- in `test_export_all_runs_every_kind_and_continues_past_failures` and in the monkeypatched `export all` test, add `"notes"` at the end of the `for kind in (...)` tuples;
- change `"2 of 8 exports written to"` → `"2 of 9 exports written to"`, `"1 of 8 exports written to"` → `"1 of 9 exports written to"`, and `"0 of 8 exports written"` → `"0 of 9 exports written"`;

and append:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: the new and edited tests FAIL (`invalid choice: 'notes'`, `of 8` printed); others PASS.

- [ ] **Step 3: Implement** — in `src/ssba/cli/main.py`:

Import (alphabetical among the parser imports):

```python
from ssba.core.parsers.notes import NotesExportError, export_notes
```

In `build_arg_parser`'s `exports` tuple, insert before the `("all", …)` entry:

```python
        ("notes", "export Samsung Notes as text files and attachments in folders", "the directory to write"),
```

After `_run_export_clock`, add:

```python
def _run_export_notes(scan_dir: Path, out: Path) -> int:
    try:
        result = export_notes(scan_dir, out)
    except NotesExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"{result.notes} notes written to {out} "
        f"({result.text_notes} with text, {result.attachments} attachments)"
    )
    if result.trashed:
        print(f"{result.trashed} notes from the trash in {out / 'Trash'}")
    if result.preview_only:
        print(f"{result.preview_only} notes only had a text preview (it may be cut short)")
    if result.handwriting_only:
        print(
            f"{result.handwriting_only} notes contain only handwriting or drawings, "
            "which cannot be exported"
        )
    if result.with_drawings:
        print(f"{result.with_drawings} notes had handwriting or drawings that are not exported")
    if result.missing_files:
        print(
            f"{result.missing_files} notes had no file in the backup "
            "(title and saved text only)"
        )
    return 0
```

In `_ALL_EXPORTS`, add as the last entry:

```python
    ("notes", _run_export_notes, "notes"),
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ssba/cli/main.py tests/test_cli.py
git commit -m "feat: add ssba export notes and include notes in export all"
```

---

## After the tasks (controller, not a subagent task)

Local-only validation on the real scan (outputs under the git-ignored `out/`):

```bash
python -c "from ssba.cli.main import main; import sys; sys.argv=['ssba','export','notes','D:/SmartSwitch-Backup-Analyzer/out/real-scan-v4','--out','D:/SmartSwitch-Backup-Analyzer/out/notes']; main()"
```

Check: 2386 notes (520 trashed); every file of every `b_*.sdocx/media/` except `mediaInfo.dat`/`*.spi` present byte-identical (multiset of hashes); every non-blank `text_search.strippedContent` found whole in a `.txt`; top-level folder names match `category_tree`.
