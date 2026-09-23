"""Show the alarms, timers and world clock cities from the backup (read-only)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from ssba.core.parsers.html_page import esc, page, write_output
from ssba.core.parsers.scan_report import MissingCategoryError, ScanReportError, category_files


class ClockExportError(Exception):
    """Raised when no clock data can be exported from a scan output directory."""


@dataclass
class ClockExportResult:
    alarms: int = 0
    timers: int = 0
    cities: int = 0


def _source(scan_dir: Path, category: str, name: str) -> Path | None:
    try:
        paths = category_files(scan_dir, category)
    except MissingCategoryError:
        return None
    except ScanReportError as exc:
        raise ClockExportError(str(exc)) from exc
    return next((p for p in paths if p.name.lower() == name), None)


def _parse(path: Path) -> ET.Element:
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ClockExportError(f"cannot read {path}: {exc}") from exc


def _field(element: ET.Element, tag: str) -> str:
    return (element.findtext(tag) or "").strip()


def _alarm_time(raw: str) -> str:
    """Samsung stores 05:30 as the integer 530."""
    try:
        value = int(raw)
    except ValueError:
        return raw
    hours, minutes = divmod(value, 100)
    if 0 <= hours < 24 and 0 <= minutes < 60:
        return f"{hours:02d}:{minutes:02d}"
    return raw


def _section(title: str, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>\n" for row in rows
    )
    return f"<h2>{esc(title)} ({len(rows)})</h2>\n<table>\n<tr>{head}</tr>\n{body}</table>"


def export_clock(scan_dir: Path, out_path: Path) -> ClockExportResult:
    alarm = _source(scan_dir, "ALARM", "alarm.exml")
    timer = _source(scan_dir, "WORLDCLOCK", "timer.exml")
    world = _source(scan_dir, "WORLDCLOCK", "worldclock.exml")
    if alarm is None and timer is None and world is None:
        raise ClockExportError("no alarm, timer or world clock data found in the scan output")

    result = ClockExportResult()
    sections = []
    if alarm is not None:
        rows = [
            (
                _alarm_time(_field(a, "alarmtime")),
                "on" if _field(a, "active") == "1" else "off",
                _field(a, "name"),
                _field(a, "repeattype"),
            )
            for a in _parse(alarm).iter("alarm")
        ]
        result.alarms = len(rows)
        sections.append(_section("Alarms", ("Time", "State", "Name", "Repeat code (raw)"), rows))
    if timer is not None:
        rows = [
            (_field(t, "timername") or f"Timer {n}", _field(t, "time"))
            for n, t in enumerate(_parse(timer).iter("item"), start=1)
        ]
        result.timers = len(rows)
        sections.append(_section("Timers", ("Name", "Duration"), rows))
    if world is not None:
        rows = [(_field(c, "city"), _field(c, "gmt")) for c in _parse(world).iter("item")]
        result.cities = len(rows)
        sections.append(_section("World clock", ("City", "Time zone"), rows))

    write_output(out_path, page("Clock", "\n".join(sections)), ClockExportError)
    return result
