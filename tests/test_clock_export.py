from __future__ import annotations

import pytest

from ssba.core.parsers.clock import ClockExportError, export_clock
from tests.clock_fixtures import build_clock_scan_dir
from tests.scan_fixtures import add_category


def _export(tmp_path, **kwargs):
    out = tmp_path / "export" / "clock.html"
    result = export_clock(build_clock_scan_dir(tmp_path / "scan", **kwargs), out)
    return result, out.read_text(encoding="utf-8")


def test_all_sources(tmp_path):
    result, html = _export(tmp_path)
    assert (result.alarms, result.timers, result.cities) == (3, 2, 2)
    for text in ("05:30", "23:59", "abc", "65537", "Timer 1", "Pasta", "00:10:00", "Roma", "GMT+9:00"):
        assert text in html
    assert "<td>on</td>" in html
    assert "<td>off</td>" in html


def test_alarm_names_are_escaped(tmp_path):
    _, html = _export(tmp_path)
    assert "Sveglia &lt;presto&gt;" in html
    assert "<presto>" not in html


@pytest.mark.parametrize("raw", ["2460", "-5", "99999"])
def test_out_of_range_alarm_time_is_shown_raw(tmp_path, raw):
    alarm = f"<Alarms><alarm><active>1</active><alarmtime>{raw}</alarmtime></alarm></Alarms>"
    _, html = _export(tmp_path, alarm=alarm, timer=None, world=None)
    assert f"<td>{raw}</td>" in html


def test_only_alarms(tmp_path):
    result, html = _export(tmp_path, timer=None, world=None)
    assert (result.alarms, result.timers, result.cities) == (3, 0, 0)
    assert "Timers" not in html
    assert "World clock" not in html


def test_only_world_clock_category(tmp_path):
    result, _ = _export(tmp_path, alarm=None)
    assert (result.alarms, result.timers, result.cities) == (0, 2, 2)


def test_no_source_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(ClockExportError, match="no alarm, timer or world clock"):
        export_clock(tmp_path, tmp_path / "clock.html")


def test_missing_report_raises(tmp_path):
    with pytest.raises(ClockExportError, match="report.json"):
        export_clock(tmp_path, tmp_path / "clock.html")


def test_malformed_xml_raises(tmp_path):
    scan_dir = build_clock_scan_dir(tmp_path / "scan", alarm="<Alarms><alarm>")
    with pytest.raises(ClockExportError, match="cannot read"):
        export_clock(scan_dir, tmp_path / "clock.html")


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_clock_scan_dir(tmp_path / "scan")
    out = tmp_path / "clock.html"
    out.mkdir()
    with pytest.raises(ClockExportError, match="cannot write"):
        export_clock(scan_dir, out)
