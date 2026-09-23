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
