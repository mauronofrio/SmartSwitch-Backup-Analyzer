"""Export Samsung Notes: text as .txt, attachments as files, folders as folders."""

from __future__ import annotations

import os
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
