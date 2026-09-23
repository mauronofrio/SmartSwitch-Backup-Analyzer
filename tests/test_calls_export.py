from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from ssba.core.parsers.calls import CallExportError, export_calls
from ssba.core.parsers.sbr_xml import TextCleaner
from tests.call_fixtures import CALL_LOG, build_call_scan_dir, call, call_log


def _export(tmp_path, log=CALL_LOG):
    scan_dir = build_call_scan_dir(tmp_path / "scan", log)
    out = tmp_path / "export" / "calls.xml"
    return export_calls(scan_dir, out), out


def _calls(out):
    root = ET.parse(out).getroot()
    assert root.tag == "calls"
    return root, root.findall("call")


def test_export_writes_every_call_sorted_by_date(tmp_path):
    result, out = _export(tmp_path)

    assert result.exported == 5
    assert (result.unknown_types, result.unsupported, result.replaced_chars) == (0, 0, 0)
    assert result.unsupported_path is None
    root, calls = _calls(out)
    assert root.get("count") == "5"
    assert [c.get("date") for c in calls] == [
        "1700000001000", "1700000002000", "1700000003000", "1700000004000", "1700000005000",
    ]
    assert [c.get("type") for c in calls] == ["2", "1", "3", "5", "6"]


def test_call_attributes_follow_sms_backup_restore(tmp_path):
    _, out = _export(tmp_path)
    _, calls = _calls(out)
    assert calls[1].attrib == {
        "number": "+393330000001",
        "duration": "65",
        "date": "1700000002000",
        "type": "1",
        "presentation": "1",
        "contact_name": "Mario Rossi",
    }


def test_sim_and_samsung_only_fields_are_not_exported(tmp_path):
    _, out = _export(tmp_path)
    _, calls = _calls(out)
    for c in calls:
        assert set(c.attrib) <= {"number", "duration", "date", "type", "presentation", "contact_name"}


def test_empty_name_is_omitted_and_private_number_kept(tmp_path):
    _, out = _export(tmp_path)
    _, calls = _calls(out)
    private = calls[3]
    assert "contact_name" not in private.attrib
    assert private.get("number") == ""
    assert private.get("presentation") == "2"


def test_missing_duration_and_presentation_get_defaults(tmp_path):
    log = call_log(call().replace("<duration>65</duration>", "").replace(
        "<presentation>1</presentation>", ""))
    _, out = _export(tmp_path, log)
    _, calls = _calls(out)
    assert calls[0].get("duration") == "0"
    assert calls[0].get("presentation") == "1"


def test_unknown_type_is_kept_and_counted(tmp_path):
    result, out = _export(tmp_path, call_log(call(type_="42")))
    _, calls = _calls(out)
    assert calls[0].get("type") == "42"
    assert result.unknown_types == 1


@pytest.mark.parametrize("bad, reason", [
    (call(date="yesterday"), "date is not an integer"),
    (call(type_="x"), "type is not an integer"),
    (call(duration="1.5"), "duration is not an integer"),
    (call().replace("<date>1700000002000</date>", ""), "missing date"),
])
def test_unconvertible_call_goes_to_side_file(tmp_path, bad, reason):
    result, out = _export(tmp_path, call_log(call(date="1700000001000"), bad))

    assert result.exported == 1
    assert result.unsupported == 1
    assert result.unsupported_path == out.with_name("calls_unsupported.json")
    rows = json.loads(result.unsupported_path.read_text(encoding="utf-8"))
    assert rows[0]["reason"] == reason
    assert rows[0]["source"] == "call_log.exml"
    assert rows[0]["fields"]["number"] == "+393330000001"


def test_clean_export_removes_a_stale_side_file(tmp_path):
    stale = tmp_path / "export" / "calls_unsupported.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("[]", encoding="utf-8")
    result, _ = _export(tmp_path)
    assert result.unsupported_path is None
    assert not stale.exists()


def test_special_characters_round_trip(tmp_path):
    name = 'Tom & "Jerry" <Srl> 💋 àè'
    _, out = _export(tmp_path, call_log(call(name=name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))))
    _, calls = _calls(out)
    assert calls[0].get("contact_name") == name


def test_text_cleaner_replaces_only_characters_xml_forbids():
    # A well-formed call log cannot carry these characters, so the shared
    # cleaner is tested directly; the message tests cover it end to end.
    clean = TextCleaner()
    assert clean("a\x07b\x00c\td\ne\rf\uFFFEg") == "a\uFFFDb\uFFFDc\td\ne\rf\uFFFDg"
    assert clean.replaced == 3


def test_malformed_call_log_raises(tmp_path):
    with pytest.raises(CallExportError, match="cannot read"):
        _export(tmp_path, "<CallLogs><CallLog>")


def test_wrong_root_raises(tmp_path):
    with pytest.raises(CallExportError, match="not a call log"):
        _export(tmp_path, "<Alarms></Alarms>")


def test_empty_call_log_raises(tmp_path):
    with pytest.raises(CallExportError, match="no calls"):
        _export(tmp_path, call_log())


def test_missing_category_raises(tmp_path):
    (tmp_path / "report.json").write_text('{"categories": []}', encoding="utf-8")
    with pytest.raises(CallExportError, match="CALLLOG"):
        export_calls(tmp_path, tmp_path / "calls.xml")


def test_no_exml_source_raises(tmp_path):
    scan_dir = build_call_scan_dir(tmp_path / "scan")
    report = {"categories": [{"category": "CALLLOG", "files": []}]}
    (scan_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(CallExportError, match=r"no call log \(\.exml\)"):
        export_calls(scan_dir, tmp_path / "calls.xml")


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_call_scan_dir(tmp_path / "scan")
    out = tmp_path / "calls.xml"
    out.mkdir()
    with pytest.raises(CallExportError, match="cannot write"):
        export_calls(scan_dir, out)
