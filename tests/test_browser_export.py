from __future__ import annotations

import zipfile
from html.parser import HTMLParser

import pytest

from ssba.core.parsers.browser import BrowserExportError, export_browser
from ssba.core.parsers.html_page import format_time
from tests.browser_fixtures import build_browser_scan_dir
from tests.scan_fixtures import add_category, entry


class _Tree(HTMLParser):
    """Rebuild the folder/link tree of a Netscape bookmark file."""

    def __init__(self):
        super().__init__()
        self.root: list = []
        self.stack = [self.root]
        self.pending = None
        self.tag = None
        self.href = None
        self.text = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("h3", "a"):
            self.tag, self.href, self.text = tag, dict(attrs).get("href"), ""
        elif tag == "dl" and self.pending is not None:
            self.stack.append(self.pending)
            self.pending = None

    def handle_endtag(self, tag):
        if tag == "h3":
            items: list = []
            self.stack[-1].append(("folder", self.text, items))
            self.pending, self.tag = items, None
        elif tag == "a":
            self.stack[-1].append(("link", self.text, self.href))
            self.tag = None
        elif tag == "dl" and len(self.stack) > 1:
            self.stack.pop()

    def handle_data(self, data):
        if self.tag:
            self.text += data


def _tree(html: str) -> list:
    parser = _Tree()
    parser.feed(html)
    return parser.root


def _export(tmp_path, **kwargs):
    out = tmp_path / "export" / "browser"
    return export_browser(build_browser_scan_dir(tmp_path / "scan", **kwargs), out), out


def test_bookmarks_keep_folders_order_and_quick_access(tmp_path):
    result, out = _export(tmp_path)
    html = (out / "bookmarks.html").read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE NETSCAPE-Bookmark-file-1>")
    assert _tree(html) == [
        ("folder", "Bookmarks", [
            ("folder", "Samsung", [
                ("link", "B <tag>", 'https://example.com/b?x=1&y="2"'),
                ("link", "Esempio A", "https://example.com/a"),
            ]),
        ]),
        ("link", "https://example.com/top", "https://example.com/top"),
        ("folder", "Quick access", [
            ("link", "Notizie", "https://news.example"),
            ("link", "Meteo", "https://meteo.example"),
        ]),
    ]
    assert (result.bookmarks, result.folders, result.quick_access, result.skipped) == (3, 2, 2, 2)


def test_bookmark_titles_and_urls_are_escaped(tmp_path):
    _, out = _export(tmp_path)
    html = (out / "bookmarks.html").read_text(encoding="utf-8")
    assert "B &lt;tag&gt;" in html
    assert "y=&quot;2&quot;" in html


def test_folders_caught_in_a_parent_cycle_are_still_exported(tmp_path):
    bookmarks = [
        (1, None, "A", 1, 2, 0, 0),
        (2, None, "B", 1, 1, 1, 0),
        (3, "https://x.example", "X", 0, 1, 0, 0),
    ]
    result, out = _export(tmp_path, bookmarks=bookmarks, quick=None)
    html = (out / "bookmarks.html").read_text(encoding="utf-8")
    assert (result.folders, result.bookmarks) == (2, 1)
    assert "https://x.example" in html


def test_history_lists_visits_newest_first_and_links_only_web_urls(tmp_path):
    result, out = _export(tmp_path)
    html = (out / "history.html").read_text(encoding="utf-8")
    assert (result.history, result.downloads) == (3, 2)
    assert html.index(format_time(1700000100)) < html.index(format_time(1700000000)) < html.index(format_time(1690000000))
    assert '<a href="https://example.com/a">' in html
    assert "javascript:alert(1)" in html
    assert 'href="javascript' not in html
    assert "&lt;b&gt;T&lt;/b&gt;" in html
    assert "<b>T</b>" not in html
    assert "<script" not in html


def test_downloads_show_the_final_url_newest_first(tmp_path):
    _, out = _export(tmp_path)
    html = (out / "history.html").read_text(encoding="utf-8")
    assert "https://cdn.example.com/a.pdf" in html
    assert "https://example.com/redirect" not in html
    assert html.index("a.pdf") < html.index("b.zip")


def test_missing_quick_access_and_history_are_tolerated(tmp_path):
    result, out = _export(tmp_path, quick=None, history=False)
    assert (result.quick_access, result.history, result.downloads) == (0, 0, 0)
    assert "Quick access" not in (out / "bookmarks.html").read_text(encoding="utf-8")
    assert (out / "history.html").is_file()


def test_missing_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(BrowserExportError, match="SBROWSER"):
        export_browser(tmp_path, tmp_path / "out")


def test_no_browser_archive_raises(tmp_path):
    other = tmp_path / "SBROWSER" / "note.txt"
    other.parent.mkdir(parents=True)
    other.write_text("x", encoding="utf-8")
    add_category(tmp_path, "SBROWSER", [entry("note.txt")])
    with pytest.raises(BrowserExportError, match="no Samsung Internet backup"):
        export_browser(tmp_path, tmp_path / "out")


def test_corrupt_database_raises(tmp_path):
    archive = tmp_path / "SBROWSER" / "backup.enc"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("databases/SBrowser.db", b"this is not sqlite")
    add_category(tmp_path, "SBROWSER", [entry("backup.enc")])
    with pytest.raises(BrowserExportError, match="cannot read"):
        export_browser(tmp_path, tmp_path / "out")


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_browser_scan_dir(tmp_path / "scan")
    out = tmp_path / "out"
    out.write_text("a file, not a directory", encoding="utf-8")
    with pytest.raises(BrowserExportError, match="cannot write"):
        export_browser(scan_dir, out)
