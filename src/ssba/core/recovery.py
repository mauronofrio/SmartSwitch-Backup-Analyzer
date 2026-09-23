"""The list of exports, shared by `ssba export all` and the GUI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ssba.core.parsers.apps import AppsExportError, export_apps
from ssba.core.parsers.blocked import BlockedExportError, export_blocked_numbers
from ssba.core.parsers.browser import BrowserExportError, export_browser
from ssba.core.parsers.calls import CallExportError, export_calls
from ssba.core.parsers.clipboard import ClipboardExportError, export_clipboard
from ssba.core.parsers.clock import ClockExportError, export_clock
from ssba.core.parsers.contact import ContactExportError, export_contacts
from ssba.core.parsers.files import (
    ORIGIN_CATEGORIES,
    STORAGE_CATEGORIES,
    FilesExportError,
    export_files,
)
from ssba.core.parsers.messages import MessageExportError, export_messages
from ssba.core.parsers.notes import NotesExportError, export_notes
from ssba.core.parsers.wifi import WifiExportError, export_wifi
from ssba.core.progress import CancelToken, OperationCancelled, ProgressFn


@dataclass(frozen=True)
class Export:
    key: str
    target: str  # name inside the output folder
    categories: tuple[str, ...]  # scan categories that make it available


EXPORTS: tuple[Export, ...] = (
    Export("contacts", "contacts.vcf", ("CONTACT",)),
    Export("messages", "sms.xml", ("GMMESSAGE",)),
    Export("calls", "calls.xml", ("CALLLOG",)),
    Export("wifi", "wifi.html", ("WIFICONFIG",)),
    Export("blocked-numbers", "blocked-numbers.txt", ("CALLOGSETTING",)),
    Export("browser", "browser", ("SBROWSER",)),
    Export("clipboard", "clipboard", ("CLIPBOARD",)),
    Export("clock", "clock.html", ("ALARM", "WORLDCLOCK")),
    Export("notes", "notes", ("SAMSUNGNOTE",)),
    Export("apps", "apps.html", ("APKFILE",)),
    Export("files", "files", STORAGE_CATEGORIES + ORIGIN_CATEGORIES),
)


@dataclass
class ExportOutcome:
    key: str
    ok: bool
    result: object | None
    error: str | None
    path: Path  # what to open


_RUNNERS = {
    "contacts": lambda scan, out, mode, progress, cancel: export_contacts(scan, out),
    "messages": lambda scan, out, mode, progress, cancel: export_messages(scan, out),
    "calls": lambda scan, out, mode, progress, cancel: export_calls(scan, out),
    "wifi": lambda scan, out, mode, progress, cancel: export_wifi(scan, out),
    "blocked-numbers": lambda scan, out, mode, progress, cancel: export_blocked_numbers(scan, out),
    "browser": lambda scan, out, mode, progress, cancel: export_browser(scan, out),
    "clipboard": lambda scan, out, mode, progress, cancel: export_clipboard(scan, out),
    "clock": lambda scan, out, mode, progress, cancel: export_clock(scan, out),
    "notes": lambda scan, out, mode, progress, cancel: export_notes(
        scan, out, progress=progress, cancel=cancel
    ),
    "apps": lambda scan, out, mode, progress, cancel: export_apps(scan, out),
    "files": lambda scan, out, mode, progress, cancel: export_files(
        scan, out, mode, progress=progress, cancel=cancel
    ),
}

_EXPORT_ERRORS = (
    AppsExportError, BlockedExportError, BrowserExportError, CallExportError,
    ClipboardExportError, ClockExportError, ContactExportError, FilesExportError,
    MessageExportError, NotesExportError, WifiExportError,
)


def report_categories(scan_dir: Path) -> set[str]:
    try:
        data = json.loads((scan_dir / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    categories = data.get("categories") if isinstance(data, dict) else None
    if not isinstance(categories, list):
        return set()
    return {c["category"] for c in categories if isinstance(c, dict) and isinstance(c.get("category"), str)}


def available_exports(scan_dir: Path) -> list[Export]:
    found = report_categories(scan_dir)
    return [e for e in EXPORTS if found.intersection(e.categories)]


def run_export(
    export: Export,
    scan_dir: Path,
    out_dir: Path,
    *,
    files_mode: str = "copy",
    progress: ProgressFn | None = None,
    cancel: CancelToken | None = None,
) -> ExportOutcome:
    path = out_dir / export.target
    try:
        result = _RUNNERS[export.key](scan_dir, path, files_mode, progress, cancel)
    except OperationCancelled:
        raise
    except _EXPORT_ERRORS as exc:
        return ExportOutcome(export.key, False, None, str(exc), path)
    except Exception as exc:  # a bug in one exporter must not stop the others
        return ExportOutcome(export.key, False, None, f"unexpected: {type(exc).__name__}: {exc}", path)
    return ExportOutcome(export.key, True, result, None, path)
