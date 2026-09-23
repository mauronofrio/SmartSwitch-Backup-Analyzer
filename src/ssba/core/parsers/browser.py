"""Export Samsung Internet bookmarks (importable) and history (read-only)."""

from __future__ import annotations

import html
import sqlite3
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from ssba.core.parsers.html_page import esc, format_time, page, safe_link, write_output
from ssba.core.parsers.scan_report import ScanReportError, category_zip

_BOOKMARKS_DB = "databases/SBrowser.db"
_QUICK_ACCESS_DB = "databases/quickaccess.db"
_HISTORY_DB = "app_sbrowser/Default/History"
# Chromium stores times as microseconds since 1601-01-01 UTC.
_CHROMIUM_EPOCH_OFFSET = 11644473600
_TOP = object()  # key of the top-level entries in the bookmark tree
_NETSCAPE_HEAD = (
    "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n"
    '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n'
    "<TITLE>Bookmarks</TITLE>\n<H1>Bookmarks</H1>\n<DL><p>\n"
)


class BrowserExportError(Exception):
    """Raised when the Samsung Internet data cannot be exported."""


@dataclass
class BrowserExportResult:
    bookmarks: int = 0
    folders: int = 0
    quick_access: int = 0
    history: int = 0
    downloads: int = 0
    skipped: int = 0


def _bookmark_esc(text: str) -> str:
    """Escape for bookmarks.html: Chrome's importer decodes only &lt; &gt;
    &amp; &quot; &#39; and reads the file line by line, so line breaks must
    become spaces and quotes must use the numeric &#39; form, not &#x27;."""
    text = text.replace("\r", " ").replace("\n", " ")
    text = html.escape(text, quote=False)
    return text.replace('"', "&quot;").replace("'", "&#39;")


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _chromium_seconds(value) -> float | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return value / 1_000_000 - _CHROMIUM_EPOCH_OFFSET


def _extract(archive: Path, member: str, tmp: Path) -> Path | None:
    with zipfile.ZipFile(archive) as zf:
        if member not in zf.namelist():
            return None
        target = tmp / member.replace("/", "_")
        target.write_bytes(zf.read(member))
        return target


def _with_db(path: Path, read):
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        con.text_factory = lambda raw: raw.decode("utf-8", errors="replace")
        return read(con)
    finally:
        con.close()


def _position(row) -> tuple:
    position = row["POSITION"]
    return (position if isinstance(position, (int, float)) else 0, row["_ID"])


def _render(children: dict, parent, depth: int, visited: set, result: BrowserExportResult) -> list[str]:
    pad = "    " * depth
    lines: list[str] = []
    for row in children.get(parent, []):
        if row["_ID"] in visited:
            continue
        visited.add(row["_ID"])
        if row["FOLDER"] == 1:
            result.folders += 1
            lines.append(f"{pad}<DT><H3>{_bookmark_esc(_text(row['TITLE']) or 'Untitled folder')}</H3>")
            lines.append(f"{pad}<DL><p>")
            lines += _render(children, row["_ID"], depth + 1, visited, result)
            lines.append(f"{pad}</DL><p>")
            continue
        url = _text(row["URL"])
        if not url:
            result.skipped += 1
            continue
        result.bookmarks += 1
        lines.append(
            f'{pad}<DT><A HREF="{_bookmark_esc(url)}">{_bookmark_esc(_text(row["TITLE"]) or url)}</A>'
        )
    return lines


def _bookmark_lines(con: sqlite3.Connection, result: BrowserExportResult) -> list[str]:
    rows = [
        row
        for row in con.execute(
            "SELECT _ID, URL, TITLE, FOLDER, PARENT, POSITION, DELETED FROM BOOKMARKS"
        )
        if not row["DELETED"]
    ]
    folder_ids = {row["_ID"] for row in rows if row["FOLDER"] == 1}
    children: dict = {}
    for row in rows:
        parent = row["PARENT"]
        key = parent if parent in folder_ids and parent != row["_ID"] else _TOP
        children.setdefault(key, []).append(row)
    for siblings in children.values():
        siblings.sort(key=_position)

    visited: set = set()
    lines = _render(children, _TOP, 1, visited, result)
    for row in sorted(rows, key=_position):
        if row["_ID"] not in visited:  # a folder caught in a PARENT cycle
            lines += _render({**children, _TOP: [row]}, _TOP, 1, visited, result)
    return lines


def _quick_access_lines(con: sqlite3.Connection, result: BrowserExportResult) -> list[str]:
    lines = []
    for row in con.execute(
        "SELECT title, url, deleted FROM quickaccess_item ORDER BY position, id"
    ):
        if row["deleted"]:
            continue
        url = _text(row["url"])
        if not url:
            result.skipped += 1
            continue
        result.quick_access += 1
        lines.append(
            f'        <DT><A HREF="{_bookmark_esc(url)}">{_bookmark_esc(_text(row["title"]) or url)}</A>'
        )
    if not lines:
        return []
    return ["    <DT><H3>Quick access</H3>", "    <DL><p>", *lines, "    </DL><p>"]


def _read_history(con: sqlite3.Connection) -> tuple[list, list]:
    urls = con.execute(
        "SELECT url, title, visit_count, last_visit_time FROM urls"
        " ORDER BY last_visit_time DESC, id DESC"
    ).fetchall()
    downloads = con.execute(
        "SELECT d.target_path, d.start_time, d.total_bytes,"
        " (SELECT c.url FROM downloads_url_chains c WHERE c.id = d.id"
        "  ORDER BY c.chain_index DESC LIMIT 1) AS url"
        " FROM downloads d ORDER BY d.start_time DESC, d.id DESC"
    ).fetchall()
    return urls, downloads


def _history_body(urls: list, downloads: list) -> str:
    visit_rows = "".join(
        "<tr>"
        f"<td>{esc(format_time(_chromium_seconds(row['last_visit_time'])))}</td>"
        f"<td>{esc(_text(row['title']))}</td>"
        f"<td>{safe_link(_text(row['url']), _text(row['url']))}</td>"
        f"<td>{esc(_text(row['visit_count']))}</td>"
        "</tr>\n"
        for row in urls
    )
    download_rows = "".join(
        "<tr>"
        f"<td>{esc(format_time(_chromium_seconds(row['start_time'])))}</td>"
        f"<td>{esc(_text(row['target_path']))}</td>"
        f"<td>{safe_link(_text(row['url']), _text(row['url']))}</td>"
        f"<td>{esc(_text(row['total_bytes']))}</td>"
        "</tr>\n"
        for row in downloads
    )
    return (
        f"<h2>Visited sites ({len(urls)})</h2>\n<table>\n"
        "<tr><th>Last visit</th><th>Title</th><th>Address</th><th>Visits</th></tr>\n"
        f"{visit_rows}</table>\n"
        f"<h2>Downloads ({len(downloads)})</h2>\n<table>\n"
        "<tr><th>Started</th><th>File</th><th>Source</th><th>Size (bytes)</th></tr>\n"
        f"{download_rows}</table>"
    )


def export_browser(scan_dir: Path, out_dir: Path) -> BrowserExportResult:
    try:
        archive = category_zip(scan_dir, "SBROWSER", _BOOKMARKS_DB)
    except ScanReportError as exc:
        raise BrowserExportError(str(exc)) from exc
    if archive is None:
        raise BrowserExportError("no Samsung Internet backup found in the scan output")

    result = BrowserExportResult()
    try:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            bookmarks_db = _extract(archive, _BOOKMARKS_DB, tmp)
            if bookmarks_db is None:
                raise BrowserExportError("no Samsung Internet backup found in the scan output")
            tree = _with_db(bookmarks_db, lambda con: _bookmark_lines(con, result))
            quick_db = _extract(archive, _QUICK_ACCESS_DB, tmp)
            quick = _with_db(quick_db, lambda con: _quick_access_lines(con, result)) if quick_db else []
            history_db = _extract(archive, _HISTORY_DB, tmp)
            urls, downloads = _with_db(history_db, _read_history) if history_db else ([], [])
    except (OSError, zipfile.BadZipFile, sqlite3.Error, zlib.error, NotImplementedError, RuntimeError) as exc:
        raise BrowserExportError(f"cannot read {archive}: {exc}") from exc

    result.history = len(urls)
    result.downloads = len(downloads)
    write_output(
        out_dir / "bookmarks.html",
        _NETSCAPE_HEAD + "\n".join(tree + quick) + "\n</DL><p>\n",
        BrowserExportError,
    )
    write_output(
        out_dir / "history.html",
        page("Samsung Internet history", _history_body(urls, downloads)),
        BrowserExportError,
    )
    return result
