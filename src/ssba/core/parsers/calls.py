"""Convert the Samsung call log Phase 1 recovered into SMS Backup & Restore XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from ssba.core.parsers.sbr_xml import TextCleaner, write_document
from ssba.core.parsers.scan_report import ScanReportError, category_files

# Android call types: incoming, outgoing, missed, voicemail, rejected,
# blocked, answered externally.
_KNOWN_TYPES = range(1, 8)


class CallExportError(Exception):
    """Raised when no calls can be exported from a scan output directory."""


@dataclass
class CallExportResult:
    exported: int
    unknown_types: int = 0
    unsupported: int = 0
    unsupported_path: Path | None = None
    replaced_chars: int = 0


def _find_sources(scan_dir: Path) -> list[Path]:
    try:
        paths = category_files(scan_dir, "CALLLOG")
    except ScanReportError as exc:
        raise CallExportError(str(exc)) from exc
    sources = [p for p in paths if p.name.lower().endswith(".exml")]
    if not sources:
        raise CallExportError("no call log (.exml) found in the scan output")
    return sources


def _read_entries(path: Path) -> list[ET.Element]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise CallExportError(f"cannot read {path}: {exc}") from exc
    if root.tag != "CallLogs":
        raise CallExportError(f"{path} is not a call log (root <{root.tag}>)")
    return root.findall("CallLog")


def _integer(entry: ET.Element, tag: str, default: int | None = None) -> int:
    value = (entry.findtext(tag) or "").strip()
    if not value:
        if default is None:
            raise ValueError(f"missing {tag}")
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{tag} is not an integer") from None


def export_calls(scan_dir: Path, out_path: Path) -> CallExportResult:
    clean = TextCleaner()
    rows: list[tuple[int, int, dict[str, str]]] = []
    unsupported: list[dict] = []
    unknown_types = 0

    for path in _find_sources(scan_dir):
        for entry in _read_entries(path):
            try:
                date = _integer(entry, "date")
                call_type = _integer(entry, "type")
                duration = _integer(entry, "duration", 0)
            except ValueError as exc:
                unsupported.append({
                    "reason": str(exc),
                    "source": path.name,
                    "fields": {child.tag: child.text or "" for child in entry},
                })
                continue
            try:
                presentation = _integer(entry, "presentation", 1)
            except ValueError:
                # An unreadable presentation is cosmetic (caller-ID display
                # hint), unlike date/type/duration: fall back rather than
                # lose the whole call.
                presentation = 1
            if date <= 0:
                unsupported.append({
                    "reason": "date is not positive",
                    "source": path.name,
                    "fields": {child.tag: child.text or "" for child in entry},
                })
                continue
            if duration < 0:
                unsupported.append({
                    "reason": "duration is negative",
                    "source": path.name,
                    "fields": {child.tag: child.text or "" for child in entry},
                })
                continue
            if call_type not in _KNOWN_TYPES:
                unknown_types += 1
            attrs = {
                "number": clean(entry.findtext("number") or ""),
                "duration": str(duration),
                "date": str(date),
                "type": str(call_type),
                "presentation": str(presentation),
            }
            name = entry.findtext("name") or ""
            if name.strip():
                attrs["contact_name"] = clean(name)
            rows.append((date, len(rows), attrs))

    if not rows:
        raise CallExportError("no calls could be read from the call log")

    rows.sort(key=lambda row: (row[0], row[1]))
    root = ET.Element("calls", count=str(len(rows)))
    for _, _, attrs in rows:
        ET.SubElement(root, "call", attrs)
    side_path = write_document(root, out_path, unsupported, CallExportError)
    return CallExportResult(
        exported=len(rows),
        unknown_types=unknown_types,
        unsupported=len(unsupported),
        unsupported_path=side_path,
        replaced_chars=clean.replaced,
    )
