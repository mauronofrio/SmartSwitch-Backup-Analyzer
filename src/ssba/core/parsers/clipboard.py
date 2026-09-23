"""Export the Samsung Keyboard clipboard - texts and images - as a read-only page."""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from ssba.core.parsers.html_page import esc, format_time, page, write_output
from ssba.core.parsers.scan_report import ScanReportError, category_zip

_DB = "BackupClipItem.db"
_TEXT_TYPES = {1: "Text", 4: "HTML"}
_IMAGE_TYPE = 2
_MAGIC = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"GIF8", "gif"))


class ClipboardExportError(Exception):
    """Raised when the clipboard cannot be exported."""


@dataclass
class ClipboardExportResult:
    texts: int = 0
    images: int = 0
    missing_images: int = 0
    other_types: int = 0


@dataclass
class _Entry:
    ms: int | None
    order: int
    html: str


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _ms(value) -> int | None:
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return ms if ms > 0 else None


def _extension(data: bytes) -> str:
    for magic, extension in _MAGIC:
        if data.startswith(magic):
            return extension
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "bin"


def _file_stamp(ms: int | None) -> str:
    if ms is None:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d_%H-%M-%S")
    except (OverflowError, OSError, ValueError):
        return ""


def _unique_name(ms: int | None, extension: str, used: set[str]) -> str:
    base = _file_stamp(ms) or f"clip-{len(used) + 1}"
    name, n = f"{base}.{extension}", 2
    while name in used:
        name, n = f"{base}_{n}.{extension}", n + 1
    used.add(name)
    return name


def _read_rows(db_bytes: bytes) -> list[sqlite3.Row]:
    with tempfile.TemporaryDirectory() as tmp_name:
        path = Path(tmp_name) / "clip.db"
        path.write_bytes(db_bytes)
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            con.row_factory = sqlite3.Row
            con.text_factory = lambda raw: raw.decode("utf-8", errors="replace")
            return con.execute(
                "SELECT time_stamp, type, text, html FROM clip_table ORDER BY time_stamp, id"
            ).fetchall()
        finally:
            con.close()


def _write_image(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        raise ClipboardExportError(f"cannot write {exc.filename or path}: {exc}") from exc


def export_clipboard(scan_dir: Path, out_dir: Path) -> ClipboardExportResult:
    try:
        archive = category_zip(scan_dir, "CLIPBOARD", _DB)
    except ScanReportError as exc:
        raise ClipboardExportError(str(exc)) from exc
    if archive is None:
        raise ClipboardExportError("no clipboard backup found in the scan output")

    result = ClipboardExportResult()
    entries: list[_Entry] = []
    used: set[str] = set()
    try:
        with zipfile.ZipFile(archive) as zf:
            rows = _read_rows(zf.read(_DB))
            # Every file under clipboard/<folder>/ is real clipboard content and must be
            # exported, not just the first one found per folder.
            image_members: list[tuple[str, str]] = []
            folders_with_images: set[str] = set()
            for name in zf.namelist():
                parts = PurePosixPath(name).parts
                if len(parts) >= 3 and parts[0] == "clipboard" and not name.endswith("/"):
                    image_members.append((parts[1], name))
                    folders_with_images.add(parts[1])
            image_members.sort(key=lambda pair: pair[1])

            for order, row in enumerate(rows):
                ms = _ms(row["time_stamp"])
                kind = row["type"]
                if kind == _IMAGE_TYPE:
                    # The image itself is listed from its folder below.
                    if _text(row["time_stamp"]) not in folders_with_images:
                        result.missing_images += 1
                        entries.append(_Entry(ms, order, '<p class="note">Image missing from the backup</p>'))
                    continue
                text = _text(row["text"])
                if kind in _TEXT_TYPES:
                    result.texts += 1
                    label = _TEXT_TYPES[kind] if text else "HTML source"
                else:
                    result.other_types += 1
                    label = f"Type {kind}"
                body = text or _text(row["html"])
                entries.append(_Entry(ms, order, f"<p><b>{esc(label)}</b></p><pre>{esc(body)}</pre>"))

            for offset, (folder, member) in enumerate(image_members):
                data = zf.read(member)
                ms = _ms(folder)
                extension = _extension(data)
                filename = _unique_name(ms, extension, used)
                _write_image(out_dir / "images" / filename, data)
                result.images += 1
                src = esc(f"images/{filename}")
                html = (
                    f'<a href="{src}">{esc(filename)}</a>'
                    if extension == "bin"
                    else f'<img src="{src}" alt="clipboard image">'
                )
                entries.append(_Entry(ms, len(rows) + offset, html))
    except (OSError, zipfile.BadZipFile, sqlite3.Error, zlib.error, NotImplementedError, RuntimeError) as exc:
        raise ClipboardExportError(f"cannot read {archive}: {exc}") from exc

    entries.sort(key=lambda e: (e.ms is None, e.ms or 0, e.order))
    body = "\n".join(
        f'<div class="entry"><p>{esc(format_time(e.ms / 1000) if e.ms else "") or "Unknown date"}</p>{e.html}</div>'
        for e in entries
    )
    write_output(out_dir / "index.html", page("Clipboard", body), ClipboardExportError)
    return result
