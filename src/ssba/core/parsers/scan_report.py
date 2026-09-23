"""Read the report.json `ssba scan` writes and list a category's files safely."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

EXPORTABLE_STATUSES = frozenset({"decrypted", "plaintext_passthrough"})


class ScanReportError(Exception):
    """Raised when report.json is missing, unreadable, or lacks the category."""


class MissingCategoryError(ScanReportError):
    """Raised when report.json has no entry for the requested category."""


def category_files(scan_dir: Path, category: str) -> list[Path]:
    """Return, in report order, the recovered files of ``category`` on disk.

    Only entries Phase 1 decrypted or passed through are kept, and only when
    they resolve to a file inside ``scan_dir / category``.
    """
    report_path = scan_dir / "report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScanReportError(f"report.json not found in {scan_dir}") from exc
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ScanReportError(f"report.json is not readable: {exc}") from exc

    if not isinstance(report, dict):
        raise ScanReportError("report.json is not readable: top level is not an object")
    categories = report.get("categories", [])
    if not isinstance(categories, list):
        raise ScanReportError("report.json is not readable: categories is not a list")

    entry = next(
        (c for c in categories if isinstance(c, dict) and c.get("category") == category),
        None,
    )
    if entry is None:
        raise MissingCategoryError(f"the scan report has no {category} category")

    files = entry.get("files", [])
    if not isinstance(files, list):
        return []

    root = scan_dir / category
    try:
        root_resolved = root.resolve()
    except (OSError, ValueError):
        root_resolved = root

    paths: list[Path] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        rel = item.get("path")
        if not isinstance(rel, str) or not rel:
            continue
        if item.get("status") not in EXPORTABLE_STATUSES:
            continue
        path = root / rel
        # Defense against path traversal: the file must stay inside the category.
        try:
            if not path.resolve().is_relative_to(root_resolved):
                continue
        except (OSError, ValueError):
            continue
        if path.is_file():
            paths.append(path)
    return paths


def category_zip(scan_dir: Path, category: str, member: str) -> Path | None:
    """Return the first recovered file of ``category`` that is a ZIP holding ``member``."""
    for path in category_files(scan_dir, category):
        try:
            if not zipfile.is_zipfile(path):
                continue
            with zipfile.ZipFile(path) as archive:
                if member in archive.namelist():
                    return path
        except (OSError, zipfile.BadZipFile):
            continue
    return None
