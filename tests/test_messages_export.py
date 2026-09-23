from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET

import pytest

from ssba.core.parsers.messages import MessageExportError, export_messages
from tests.message_fixtures import DB_NAME, build_message_scan_dir

ONE_TO_ONE = dict(members=[(10, 1), (10, 2)])


def _export(tmp_path, **kwargs):
    scan_dir = build_message_scan_dir(tmp_path / "scan", **kwargs)
    out = tmp_path / "export" / "sms.xml"
    return export_messages(scan_dir, out), out


def _sms(out):
    root = ET.parse(out).getroot()
    assert root.tag == "smses"
    return root, root.findall("sms")


def _single(tmp_path, *, status=100, parts=((100, "text/plain", "x"),), received=1700000002000,
            sent=1700000001000, **extra):
    messages = [(100, 10, 2 if status >= 100 else 1, status, 1, received, sent, 0)]
    return _export(tmp_path, messages=messages, parts=list(parts), **ONE_TO_ONE, **extra)


def test_export_writes_sms_sorted_by_date(tmp_path):
    result, out = _export(tmp_path)

    assert result.exported == 3
    assert result.rcs_as_sms == 1
    assert result.system_skipped == 1
    assert result.unsupported == 1
    assert result.replaced_chars == 0
    root, sms = _sms(out)
    assert root.get("count") == "3"
    assert [s.get("body") for s in sms] == ["Messaggio RCS", "Ciao", "Risposta"]


def test_sms_attributes_follow_sms_backup_restore(tmp_path):
    _, out = _export(tmp_path)
    _, sms = _sms(out)
    rcs, received, sent = sms
    assert list(received.attrib.items()) == [
        ("protocol", "0"), ("address", "+393330000001"), ("date", "1700000002000"),
        ("type", "1"), ("body", "Ciao"), ("read", "1"), ("status", "-1"),
        ("locked", "0"), ("date_sent", "1700000001000"), ("contact_name", "Mario Rossi"),
    ]
    assert rcs.get("protocol") == "0"
    assert rcs.get("read") == "0"
    assert "date_sent" not in rcs.attrib
    assert "contact_name" not in rcs.attrib
    assert sent.get("type") == "2"
    assert sent.get("address") == "+393330000001"


@pytest.mark.parametrize("status, sms_type", [
    (1, "2"), (2, "2"), (3, "3"), (4, "2"), (8, "5"), (9, "5"), (11, "2"), (100, "1"), (199, "1"),
])
def test_status_maps_to_sms_type(tmp_path, status, sms_type):
    _, out = _single(tmp_path, status=status)
    _, sms = _sms(out)
    assert sms[0].get("type") == sms_type


@pytest.mark.parametrize("status", [200, 206, 219])
def test_system_rows_are_skipped(tmp_path, status):
    messages = [
        (100, 10, 2, 100, 1, 1700000002000, 0, 0),
        (101, 10, 1, status, 1, 1700000003000, 0, 0),
    ]
    result, _ = _export(tmp_path, messages=messages, parts=[(100, "text/plain", "x")], **ONE_TO_ONE)
    assert (result.exported, result.system_skipped, result.unsupported) == (1, 1, 0)


def _side_rows(result):
    return json.loads(result.unsupported_path.read_text(encoding="utf-8"))


def test_group_conversation_goes_to_side_file(tmp_path):
    result, out = _export(tmp_path)
    assert result.unsupported_path == out.with_name("sms_unsupported.json")
    rows = _side_rows(result)
    assert rows == [{
        "reason": "group or no recipient",
        "source": DB_NAME,
        "message": {
            "_id": 104, "conversation_id": 30, "sender_participant_id": 4,
            "message_status": 100, "read": 1, "received_timestamp": 1700000005000,
            "sent_timestamp": 0, "protocol": 0,
        },
        "texts": ["nel gruppo"],
    }]


@pytest.mark.parametrize("status", [0, -1, None])
def test_unknown_status_is_unsupported(tmp_path, status):
    messages = [(100, 10, 2, 100, 1, 1700000002000, 0, 0), (101, 10, 2, status, 1, 1700000003000, 0, 0)]
    parts = [(100, "text/plain", "x"), (101, "text/plain", "y")]
    result, _ = _export(tmp_path, messages=messages, parts=parts, **ONE_TO_ONE)
    assert result.unsupported == 1
    assert _side_rows(result)[0]["reason"] == "unknown status"


def test_message_without_text_is_unsupported(tmp_path):
    messages = [(100, 10, 2, 100, 1, 1700000002000, 0, 0), (101, 10, 2, 100, 1, 1700000003000, 0, 0)]
    parts = [(100, "text/plain", "x"), (101, "image/jpeg", None)]
    result, _ = _export(tmp_path, messages=messages, parts=parts, **ONE_TO_ONE)
    assert _side_rows(result)[0]["reason"] == "no text"


def test_bad_status_type_is_unsupported(tmp_path):
    messages = [(100, 10, 2, 100, 1, 1700000002000, 0, 0), (101, 10, 2, "12x", 1, 1700000003000, 0, 0)]
    parts = [(100, "text/plain", "x"), (101, "text/plain", "y")]
    result, _ = _export(tmp_path, messages=messages, parts=parts, **ONE_TO_ONE)
    assert result.exported == 1
    assert result.unsupported == 1
    assert _side_rows(result)[0]["reason"] == "bad column type"


def test_bad_received_timestamp_type_is_unsupported(tmp_path):
    messages = [(100, 10, 2, 100, 1, 1700000002000, 0, 0), (101, 10, 2, 100, 1, 1.5, 0, 0)]
    parts = [(100, "text/plain", "x"), (101, "text/plain", "y")]
    result, _ = _export(tmp_path, messages=messages, parts=parts, **ONE_TO_ONE)
    assert result.exported == 1
    assert result.unsupported == 1
    assert _side_rows(result)[0]["reason"] == "bad column type"


def test_blob_part_text_is_unsupported(tmp_path):
    messages = [(100, 10, 2, 100, 1, 1700000002000, 0, 0), (101, 10, 2, 100, 1, 1700000003000, 0, 0)]
    scan_dir = build_message_scan_dir(tmp_path / "scan", messages=messages,
                                       parts=[(100, "text/plain", "x")], **ONE_TO_ONE)
    con = sqlite3.connect(scan_dir / "GMMESSAGE" / DB_NAME)
    con.execute(
        "INSERT INTO parts_backup (message_id, content_type, text) VALUES (101, 'image/jpeg', ?)",
        (b"\x00\x01",),
    )
    con.commit()
    con.close()
    result = export_messages(scan_dir, tmp_path / "sms.xml")
    _, sms = _sms(tmp_path / "sms.xml")
    assert result.exported == 1
    assert result.unsupported == 1
    rows = json.loads(result.unsupported_path.read_text(encoding="utf-8"))
    assert rows[0]["reason"] == "bad column type"
    assert rows[0]["texts"] == ["0001"]


def test_parts_are_joined_in_part_order(tmp_path):
    _, out = _single(tmp_path, parts=[(100, "text/plain", "uno"), (100, "text/plain", "due")])
    _, sms = _sms(out)
    assert sms[0].get("body") == "uno\ndue"


@pytest.mark.parametrize("participant, address", [
    ((2, 0, None, "+393330000001", "333 000 0001", None), "+393330000001"),
    ((2, 0, "", "", "333 000 0001", None), "333 000 0001"),
])
def test_address_falls_back_to_other_destinations(tmp_path, participant, address):
    _, out = _single(tmp_path, participants=[(1, 1, None, None, None, None), participant])
    _, sms = _sms(out)
    assert sms[0].get("address") == address


def test_participant_without_any_destination_is_unsupported(tmp_path):
    messages = [(100, 10, 2, 100, 1, 1700000002000, 0, 0), (101, 20, 3, 100, 1, 1700000003000, 0, 0)]
    participants = [(1, 1, None, None, None, None),
                    (2, 0, "+393330000001", None, None, None),
                    (3, 0, None, "", None, None)]
    parts = [(100, "text/plain", "x"), (101, "text/plain", "y")]
    result, _ = _export(tmp_path, messages=messages, parts=parts, participants=participants,
                        members=[(10, 1), (10, 2), (20, 1), (20, 3)])
    assert _side_rows(result)[0]["reason"] == "no address"


def test_date_falls_back_to_sent_timestamp(tmp_path):
    _, out = _single(tmp_path, received=0, sent=1700000009000)
    _, sms = _sms(out)
    assert sms[0].get("date") == "1700000009000"


def test_message_without_any_date_is_unsupported(tmp_path):
    messages = [(100, 10, 2, 100, 1, 1700000002000, 0, 0), (101, 10, 2, 100, 1, None, 0, 0)]
    parts = [(100, "text/plain", "x"), (101, "text/plain", "y")]
    result, _ = _export(tmp_path, messages=messages, parts=parts, **ONE_TO_ONE)
    assert _side_rows(result)[0]["reason"] == "no date"


def test_negative_date_is_unsupported(tmp_path):
    messages = [(100, 10, 2, 100, 1, 1700000002000, 0, 0), (101, 10, 2, 100, 1, -5, 0, 0)]
    parts = [(100, "text/plain", "x"), (101, "text/plain", "y")]
    result, _ = _export(tmp_path, messages=messages, parts=parts, **ONE_TO_ONE)
    assert result.exported == 1
    assert result.unsupported == 1
    assert _side_rows(result)[0]["reason"] == "no date"


def test_tricky_body_round_trips_exactly(tmp_path):
    body = "a & b < c > d \"q\" 's'\nriga2\r\nriga3\tTab 💋 àè\u2028fine"
    result, out = _single(tmp_path, parts=[(100, "text/plain", body)])
    _, sms = _sms(out)
    assert sms[0].get("body") == body
    assert result.replaced_chars == 0


def test_control_characters_are_replaced_and_counted(tmp_path):
    result, out = _single(tmp_path, parts=[(100, "text/plain", "x\x07y\x00z")])
    _, sms = _sms(out)
    assert sms[0].get("body") == "x\ufffdy\ufffdz"
    assert result.replaced_chars == 2


def test_invalid_utf8_text_is_replaced_not_fatal(tmp_path):
    scan_dir = build_message_scan_dir(tmp_path / "scan", parts=[], **ONE_TO_ONE,
                                      messages=[(100, 10, 2, 100, 1, 1700000002000, 0, 0)])
    con = sqlite3.connect(scan_dir / "GMMESSAGE" / DB_NAME)
    con.execute("INSERT INTO parts_backup (message_id, content_type, text) VALUES (100, 'text/plain', CAST(? AS TEXT))",
                (b"ok\xff",))
    con.commit()
    con.close()
    result = export_messages(scan_dir, tmp_path / "sms.xml")
    _, sms = _sms(tmp_path / "sms.xml")
    assert sms[0].get("body") == "ok\ufffd"
    assert result.replaced_chars == 1


def test_several_databases_are_merged_by_date(tmp_path):
    result, out = _export(tmp_path, db_names=(DB_NAME, "item_instant_2_size_1_id_1"))
    _, sms = _sms(out)
    assert result.exported == 6
    assert [s.get("body") for s in sms] == [
        "Messaggio RCS", "Messaggio RCS", "Ciao", "Ciao", "Risposta", "Risposta",
    ]


def test_output_follows_the_published_xsd_rules(tmp_path):
    _, out = _export(tmp_path)
    root, sms = _sms(out)
    assert int(root.get("count")) == len(sms)
    for s in sms:
        assert {"address", "date", "type", "body", "read", "status"} <= set(s.attrib)
        for name in ("protocol", "date", "type", "read", "status", "locked", "date_sent"):
            if name in s.attrib:
                int(s.get(name))


def test_source_database_is_not_modified(tmp_path):
    scan_dir = build_message_scan_dir(tmp_path / "scan")
    db = scan_dir / "GMMESSAGE" / DB_NAME
    before = db.read_bytes()
    export_messages(scan_dir, tmp_path / "sms.xml")
    assert db.read_bytes() == before
    assert sorted(p.name for p in db.parent.iterdir()) == ["d2d_item_info.json", DB_NAME]


def test_clean_export_removes_a_stale_side_file(tmp_path):
    stale = tmp_path / "export" / "sms_unsupported.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("[]", encoding="utf-8")
    messages = [(100, 10, 2, 100, 1, 1700000002000, 0, 0)]
    parts = [(100, "text/plain", "x")]
    result, _ = _export(tmp_path, messages=messages, parts=parts, **ONE_TO_ONE)
    assert result.unsupported_path is None
    assert not stale.exists()


def test_database_missing_a_table_raises(tmp_path):
    scan_dir = build_message_scan_dir(tmp_path / "scan")
    con = sqlite3.connect(scan_dir / "GMMESSAGE" / DB_NAME)
    con.execute("DROP TABLE parts_backup")
    con.commit()
    con.close()
    with pytest.raises(MessageExportError, match="missing parts_backup"):
        export_messages(scan_dir, tmp_path / "sms.xml")


def test_no_database_raises(tmp_path):
    scan_dir = build_message_scan_dir(tmp_path / "scan", db_names=())
    with pytest.raises(MessageExportError, match="no Google Messages database"):
        export_messages(scan_dir, tmp_path / "sms.xml")


def test_missing_category_raises(tmp_path):
    (tmp_path / "report.json").write_text('{"categories": []}', encoding="utf-8")
    with pytest.raises(MessageExportError, match="GMMESSAGE"):
        export_messages(tmp_path, tmp_path / "sms.xml")


def test_nothing_exportable_raises(tmp_path):
    with pytest.raises(MessageExportError, match="no messages"):
        _export(tmp_path, messages=[(103, 10, 1, 206, 1, 1700000004000, 0, 0)], parts=[])


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_message_scan_dir(tmp_path / "scan")
    out = tmp_path / "sms.xml"
    out.mkdir()
    with pytest.raises(MessageExportError, match="cannot write"):
        export_messages(scan_dir, out)
