"""Convert the Google Messages database Phase 1 recovered into SMS Backup & Restore XML."""

from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from ssba.core.parsers.sbr_xml import TextCleaner, write_document
from ssba.core.parsers.scan_report import ScanReportError, category_files

_SQLITE_MAGIC = b"SQLite format 3\x00"
_REQUIRED_TABLES = (
    "messages_backup",
    "parts_backup",
    "participants_backup",
    "conversation_participants_backup",
)
# Google Messages ("Bugle") status codes: 1-99 outgoing, 100-199 incoming,
# 200 and above are system rows ("chat started", ...) with no text.
_FIRST_SYSTEM_STATUS = 200


class MessageExportError(Exception):
    """Raised when no messages can be exported from a scan output directory."""


@dataclass
class MessageExportResult:
    exported: int
    rcs_as_sms: int = 0
    system_skipped: int = 0
    unsupported: int = 0
    unsupported_path: Path | None = None
    replaced_chars: int = 0


@dataclass
class _Database:
    participants: dict[int, sqlite3.Row]
    members: dict[int, list[int]]
    texts: dict[int, list[str]]
    messages: list[sqlite3.Row]


def _find_sources(scan_dir: Path) -> list[Path]:
    try:
        paths = category_files(scan_dir, "GMMESSAGE")
    except ScanReportError as exc:
        raise MessageExportError(str(exc)) from exc
    sources = []
    for path in paths:
        try:
            with path.open("rb") as fh:
                head = fh.read(len(_SQLITE_MAGIC))
        except OSError as exc:
            raise MessageExportError(f"cannot read {path}: {exc}") from exc
        if head == _SQLITE_MAGIC:
            sources.append(path)
    if not sources:
        raise MessageExportError("no Google Messages database found in the scan output")
    return sources


def _read_database(path: Path) -> _Database:
    try:
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise MessageExportError(f"cannot open {path}: {exc}") from exc
    con.row_factory = sqlite3.Row
    # Invalid UTF-8 must not abort the export: it becomes U+FFFD when written.
    con.text_factory = lambda raw: raw.decode("utf-8", "surrogateescape")
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in _REQUIRED_TABLES if t not in tables]
        if missing:
            raise MessageExportError(
                f"{path} is not a Google Messages backup (missing {', '.join(missing)})"
            )
        participants = {
            row["_id"]: row
            for row in con.execute(
                "SELECT _id, is_self, send_destination, normalized_destination,"
                " display_destination, full_name FROM participants_backup"
            )
        }
        members: dict[int, list[int]] = {}
        for row in con.execute(
            "SELECT conversation_id, participant_id FROM conversation_participants_backup"
        ):
            members.setdefault(row["conversation_id"], []).append(row["participant_id"])
        texts: dict[int, list[str]] = {}
        for row in con.execute(
            "SELECT message_id, text FROM parts_backup WHERE text IS NOT NULL ORDER BY _id"
        ):
            texts.setdefault(row["message_id"], []).append(row["text"])
        messages = con.execute(
            "SELECT _id, conversation_id, sender_participant_id, message_status, read,"
            " received_timestamp, sent_timestamp, protocol FROM messages_backup ORDER BY _id"
        ).fetchall()
    except sqlite3.Error as exc:
        raise MessageExportError(f"cannot read {path}: {exc}") from exc
    finally:
        con.close()
    return _Database(participants, members, texts, messages)


def _sms_type(status: int | None) -> int | None:
    if status is None or status <= 0:
        return None
    if status == 3:
        return 3  # draft
    if status in (8, 9):
        return 5  # failed
    if status < 100:
        return 2  # sent
    return 1  # received


def _destination(participant: sqlite3.Row) -> str | None:
    for column in ("send_destination", "normalized_destination", "display_destination"):
        value = participant[column]
        if value is not None and str(value).strip():
            return str(value)
    return None


def _counterpart(db: _Database, conversation_id: int) -> sqlite3.Row | None:
    others = [
        db.participants[pid]
        for pid in db.members.get(conversation_id, [])
        if pid in db.participants and not db.participants[pid]["is_self"]
    ]
    return others[0] if len(others) == 1 else None


def export_messages(scan_dir: Path, out_path: Path) -> MessageExportResult:
    clean = TextCleaner()
    rows: list[tuple[int, int, dict[str, str]]] = []
    unsupported: list[dict] = []
    result = MessageExportResult(exported=0)

    for path in _find_sources(scan_dir):
        db = _read_database(path)
        for message in db.messages:
            status = message["message_status"]
            if status is not None and status >= _FIRST_SYSTEM_STATUS:
                result.system_skipped += 1
                continue

            def reject(reason: str) -> None:
                unsupported.append({
                    "reason": reason,
                    "source": path.name,
                    "message": dict(message),
                    "texts": db.texts.get(message["_id"], []),
                })

            sms_type = _sms_type(status)
            if sms_type is None:
                reject("unknown status")
                continue
            if message["_id"] not in db.texts:
                reject("no text")
                continue
            counterpart = _counterpart(db, message["conversation_id"])
            if counterpart is None:
                reject("group or no recipient")
                continue
            address = _destination(counterpart)
            if address is None:
                reject("no address")
                continue
            sent = message["sent_timestamp"] or 0
            date = message["received_timestamp"] or sent
            if not date:
                reject("no date")
                continue

            attrs = {
                "protocol": "0",
                "address": clean(address),
                "date": str(date),
                "type": str(sms_type),
                "body": clean("\n".join(db.texts[message["_id"]])),
                "read": "1" if message["read"] else "0",
                "status": "-1",
                "locked": "0",
            }
            if sent > 0:
                attrs["date_sent"] = str(sent)
            name = counterpart["full_name"]
            if name is not None and str(name).strip():
                attrs["contact_name"] = clean(str(name))
            if message["protocol"]:
                result.rcs_as_sms += 1
            rows.append((date, len(rows), attrs))

    if not rows:
        raise MessageExportError("no messages could be converted from the Google Messages backup")

    rows.sort(key=lambda row: (row[0], row[1]))
    root = ET.Element("smses", count=str(len(rows)))
    for _, _, attrs in rows:
        ET.SubElement(root, "sms", attrs)
    result.unsupported_path = write_document(root, out_path, unsupported, MessageExportError)
    result.exported = len(rows)
    result.unsupported = len(unsupported)
    result.replaced_chars = clean.replaced
    return result
