from __future__ import annotations

from datetime import datetime

import pytest

from ssba.core.parsers.html_page import esc, format_time, page, safe_link, write_output


def test_esc_escapes_markup_and_quotes():
    assert esc("<a href=\"x\">'&") == "&lt;a href=&quot;x&quot;&gt;&#x27;&amp;"


@pytest.mark.parametrize("url", ["https://e.example/?a=1&b=2", "HTTP://E.EXAMPLE/"])
def test_safe_link_links_http_urls(url):
    assert safe_link(url, "<t>") == f'<a href="{esc(url)}">&lt;t&gt;</a>'


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,x", ""])
def test_safe_link_never_links_other_schemes(url):
    assert safe_link(url, "<t>") == "&lt;t&gt;"


@pytest.mark.parametrize("value", [None, 0, -5])
def test_format_time_of_unknown_is_empty(value):
    assert format_time(value) == ""


def test_format_time_uses_local_time():
    expected = datetime.fromtimestamp(1700000000).strftime("%Y-%m-%d %H:%M:%S")
    assert format_time(1700000000) == expected


def test_format_time_out_of_range_is_empty():
    assert format_time(1e20) == ""


def test_page_is_a_self_contained_document_with_escaped_title():
    html = page("<T>", "<p>body</p>")
    assert html.startswith("<!DOCTYPE html>")
    assert '<meta charset="utf-8">' in html
    assert "<title>&lt;T&gt;</title>" in html
    assert "<h1>&lt;T&gt;</h1>" in html
    assert "<p>body</p>" in html
    assert "<script" not in html
    assert "http" not in html


def test_write_output_creates_parents_and_writes_utf8(tmp_path):
    target = tmp_path / "a" / "b.html"
    write_output(target, "caff\u00e8", ValueError)
    assert target.read_bytes() == "caff\u00e8".encode("utf-8")


def test_write_output_failure_raises_the_given_error(tmp_path):
    target = tmp_path / "dir"
    target.mkdir()
    with pytest.raises(KeyError, match="cannot write"):
        write_output(target, "x", KeyError)
