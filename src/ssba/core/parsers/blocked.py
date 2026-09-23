"""List the numbers the phone blocked, one per line, to re-enter by hand."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from ssba.core.parsers.html_page import write_output
from ssba.core.parsers.scan_report import ScanReportError, category_files

# The call settings backup names each table's CSV after its entity class;
# "...PhotoRingBlockNumberItem.csv" is another list and does not match.
_SOURCE_SUFFIX = ".blocknumberitem.csv"


class BlockedExportError(Exception):
    """Raised when no blocked numbers can be exported from a scan output directory."""


@dataclass
class BlockedExportResult:
    exported: int
    skipped: int = 0


def _find_source(scan_dir: Path) -> Path:
    try:
        paths = category_files(scan_dir, "CALLOGSETTING")
    except ScanReportError as exc:
        raise BlockedExportError(str(exc)) from exc
    for path in paths:
        if path.name.lower().endswith(_SOURCE_SUFFIX):
            return path
    raise BlockedExportError("no blocked-number list found in the scan output")


def _row_order(item: tuple[int, dict]) -> tuple[int, int, int]:
    index, row = item
    try:
        return (0, int(row.get("_id") or ""), index)
    except ValueError:
        return (1, 0, index)


def export_blocked_numbers(scan_dir: Path, out_path: Path) -> BlockedExportResult:
    path = _find_source(scan_dir)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise BlockedExportError(f"cannot read {path}: {exc}") from exc

    rows = list(csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE))
    lines: list[str] = []
    skipped = 0
    for _, row in sorted(enumerate(rows), key=_row_order):
        number = (row.get("reject_number") or "").strip()
        if not number:
            skipped += 1
            continue
        match = (row.get("reject_match") or "0").strip()
        lines.append(number if match == "0" else f"{number}\t(match type {match})")

    if not lines:
        raise BlockedExportError("no blocked numbers found in the list")
    write_output(out_path, "\n".join(lines) + "\n", BlockedExportError)
    return BlockedExportResult(exported=len(lines), skipped=skipped)
