"""Fabricated Samsung Internet backup for tests - no real browsing data."""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from pathlib import Path

from tests.scan_fixtures import add_category, entry


def chromium(seconds: float) -> int:
    """Unix seconds -> Chromium time (microseconds since 1601-01-01)."""
    return int((seconds + 11644473600) * 1_000_000)


# (_ID, URL, TITLE, FOLDER, PARENT, POSITION, DELETED)
BOOKMARKS = [
    (-3, None, "Bookmarks", 1, -2, -10, 0),
    (0, None, "Samsung", 1, -3, -10001, 0),
    (73, "https://example.com/a", "Esempio A", 0, 0, -100, 0),
    (74, 'https://example.com/b?x=1&y="2"', "B <tag>", 0, 0, -101, 0),
    (75, "https://example.com/deleted", "Deleted", 0, 0, -99, 1),
    (76, "https://example.com/top", "", 0, 999, 5, 0),
    (77, "", "No url", 0, 0, -98, 0),
]
# (id, title, url, position, deleted)
QUICK = [
    (1, "Meteo", "https://meteo.example", 1, 0),
    (2, "Notizie", "https://news.example", 0, 0),
    (3, "Vecchio", "https://old.example", 2, 1),
    (4, "Vuoto", "", 3, 0),
]
# (id, url, title, visit_count, last_visit_time)
URLS = [
    (1, "https://example.com/a", "A", 3, chromium(1700000000)),
    (2, "javascript:alert(1)", "JS", 1, chromium(1700000100)),
    (3, "http://example.org/<x>", "<b>T</b>", 2, chromium(1690000000)),
]
# (id, target_path, start_time, total_bytes, state)
DOWNLOADS = [
    (1, "/storage/emulated/0/Download/a.pdf", chromium(1700000200), 1234, 1),
    (2, "/storage/emulated/0/Download/b.zip", chromium(1600000000), 99, 1),
]
# (id, chain_index, url)
CHAINS = [
    (1, 0, "https://example.com/redirect"),
    (1, 1, "https://cdn.example.com/a.pdf"),
    (2, 0, "https://example.com/b.zip"),
]


def _db(path: Path, script: str, inserts: list[tuple[str, list[tuple]]]) -> bytes:
    con = sqlite3.connect(path)
    con.executescript(script)
    for sql, rows in inserts:
        con.executemany(sql, rows)
    con.commit()
    con.close()
    return path.read_bytes()


def build_browser_scan_dir(scan_dir: Path, *, bookmarks=BOOKMARKS, quick=QUICK, history=True) -> Path:
    members: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        members["databases/SBrowser.db"] = _db(
            tmp / "b.db",
            "CREATE TABLE BOOKMARKS (_ID INTEGER, URL TEXT, TITLE TEXT, FOLDER INTEGER,"
            " PARENT INTEGER, POSITION INTEGER, DELETED INTEGER);",
            [("INSERT INTO BOOKMARKS VALUES (?,?,?,?,?,?,?)", bookmarks)],
        )
        if quick is not None:
            members["databases/quickaccess.db"] = _db(
                tmp / "q.db",
                "CREATE TABLE quickaccess_item (id INTEGER PRIMARY KEY, title TEXT, url TEXT,"
                " position INTEGER, deleted INTEGER);",
                [("INSERT INTO quickaccess_item VALUES (?,?,?,?,?)", quick)],
            )
        if history:
            members["app_sbrowser/Default/History"] = _db(
                tmp / "h.db",
                "CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT,"
                " visit_count INTEGER, last_visit_time INTEGER);"
                "CREATE TABLE downloads (id INTEGER PRIMARY KEY, target_path TEXT,"
                " start_time INTEGER, total_bytes INTEGER, state INTEGER);"
                "CREATE TABLE downloads_url_chains (id INTEGER, chain_index INTEGER, url TEXT);",
                [
                    ("INSERT INTO urls VALUES (?,?,?,?,?)", URLS),
                    ("INSERT INTO downloads VALUES (?,?,?,?,?)", DOWNLOADS),
                    ("INSERT INTO downloads_url_chains VALUES (?,?,?)", CHAINS),
                ],
            )
    archive = scan_dir / "SBROWSER" / "SBROWSER.zip" / "backup.enc"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    add_category(scan_dir, "SBROWSER", [entry("SBROWSER.zip/backup.enc", kind="zip")])
    return scan_dir
