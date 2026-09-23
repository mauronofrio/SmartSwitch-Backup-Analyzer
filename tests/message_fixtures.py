"""Fabricated Google Messages backup database for tests - no real data."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_NAME = "item_instant_1700000000000_size_4096_id_0"

SCHEMA = """
CREATE TABLE messages_backup (
    _id INTEGER PRIMARY KEY, conversation_id INT, sender_participant_id INT,
    message_status INT, read INT, received_timestamp INT, sent_timestamp INT,
    protocol INT);
CREATE TABLE parts_backup (
    _id INTEGER PRIMARY KEY AUTOINCREMENT, message_id INT, content_type TEXT, text TEXT);
CREATE TABLE participants_backup (
    _id INTEGER PRIMARY KEY, is_self INT, send_destination TEXT,
    normalized_destination TEXT, display_destination TEXT, full_name TEXT);
CREATE TABLE conversation_participants_backup (
    _id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INT, participant_id INT);
"""

# (_id, is_self, send_destination, normalized_destination, display_destination, full_name)
PARTICIPANTS = [
    (1, 1, None, None, None, None),
    (2, 0, "+393330000001", "+393330000001", "333 000 0001", "Mario Rossi"),
    (3, 0, "+393330000002", "+393330000002", "333 000 0002", None),
    (4, 0, "+393330000003", "+393330000003", "333 000 0003", "Anna Gruppo"),
    (5, 0, "+393330000004", "+393330000004", "333 000 0004", None),
]
# (conversation_id, participant_id)
MEMBERS = [(10, 1), (10, 2), (20, 1), (20, 3), (30, 1), (30, 4), (30, 5)]
# (_id, conversation_id, sender, status, read, received, sent, protocol)
MESSAGES = [
    (100, 10, 2, 100, 1, 1700000002000, 1700000001000, 0),  # received SMS
    (101, 10, 1, 1, 1, 1700000003000, 1700000003000, 0),    # sent SMS
    (102, 20, 3, 100, 0, 1700000000500, 0, 3),              # received RCS, unread
    (103, 10, 1, 206, 1, 1700000004000, 0, 0),              # system row, no parts
    (104, 30, 4, 100, 1, 1700000005000, 0, 0),              # group conversation
]
# (message_id, content_type, text)
PARTS = [
    (100, "text/plain", "Ciao"),
    (101, "text/plain", "Risposta"),
    (102, "text/plain", "Messaggio RCS"),
    (104, "text/plain", "nel gruppo"),
]


def build_db(path: Path, *, participants=PARTICIPANTS, members=MEMBERS,
             messages=MESSAGES, parts=PARTS) -> Path:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO participants_backup VALUES (?,?,?,?,?,?)", participants)
    con.executemany(
        "INSERT INTO conversation_participants_backup (conversation_id, participant_id) VALUES (?,?)",
        members,
    )
    con.executemany("INSERT INTO messages_backup VALUES (?,?,?,?,?,?,?,?)", messages)
    con.executemany(
        "INSERT INTO parts_backup (message_id, content_type, text) VALUES (?,?,?)", parts
    )
    con.commit()
    con.close()
    return path


def build_message_scan_dir(scan_dir: Path, *, db_names=(DB_NAME,), **tables) -> Path:
    """Write a fake `ssba scan` output tree with a GMMESSAGE category.

    ``tables`` overrides the default rows (participants, members, messages,
    parts) of every database written.
    """
    gm = scan_dir / "GMMESSAGE"
    gm.mkdir(parents=True)
    (gm / "d2d_item_info.json").write_text("[]", encoding="utf-8")
    files = [{"path": "d2d_item_info.json", "status": "plaintext_passthrough", "kind": "json", "detail": None}]
    for name in db_names:
        build_db(gm / name, **tables)
        files.append({"path": name, "status": "plaintext_passthrough", "kind": "sqlite", "detail": None})
    report = {"categories": [{"category": "GMMESSAGE", "counts": {}, "files": files}]}
    (scan_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return scan_dir
