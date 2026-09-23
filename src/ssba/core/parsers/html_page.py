"""Helpers for the self-contained, read-only pages the exporters write."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

_STYLE = (
    "body{font-family:system-ui,sans-serif;margin:2em;color:#222}"
    "table{border-collapse:collapse}"
    "th,td{border:1px solid #ccc;padding:.3em .6em;text-align:left;vertical-align:top}"
    "pre{white-space:pre-wrap;word-break:break-word;margin:0}"
    ".note{background:#fff4ce;padding:.5em 1em}"
    ".entry{border-bottom:1px solid #ddd;padding:.5em 0}"
    "img{max-width:32em}"
)


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def page(title: str, body: str) -> str:
    """A complete HTML document: no scripts, no external resources."""
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{esc(title)}</title>\n<style>{_STYLE}</style>\n</head>\n<body>\n"
        f"<h1>{esc(title)}</h1>\n{body}\n</body>\n</html>\n"
    )


def format_time(seconds: float | None) -> str:
    """Local time as YYYY-MM-DD HH:MM:SS; empty when unknown or out of range."""
    if seconds is None or seconds <= 0:
        return ""
    try:
        return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def safe_link(url: str, text: str) -> str:
    """Link only web addresses; anything else (javascript:, file:, ...) stays text."""
    if url.lower().startswith(("http://", "https://")):
        return f'<a href="{esc(url)}">{esc(text)}</a>'
    return esc(text)


def write_output(path: Path, text: str, error: type[Exception]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise error(f"cannot write {exc.filename or path}: {exc}") from exc
