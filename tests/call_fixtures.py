"""Fabricated Samsung call log for tests - no real numbers or names."""

from __future__ import annotations

import json
from pathlib import Path

SIM = (
    "<is_read>1</is_read><new>1</new><sec_icc_id>89390000000000000000</sec_icc_id>"
    "<subscription_component_name>com.android.phone/com.android.services.telephony."
    "TelephonyConnectionService</subscription_component_name>"
    "<subscription_id>3</subscription_id><data1 /><data2 /><data3 /><data4 />"
    "<sim_id>0</sim_id>"
)


def call(*, name="", date="1700000002000", duration="65", number="+393330000001",
         presentation="1", type_="1", logtype="1000") -> str:
    return (
        f"<CallLog><name>{name}</name><date>{date}</date><duration>{duration}</duration>"
        f"<number>{number}</number><presentation>{presentation}</presentation>"
        f"<type>{type_}</type><logtype>{logtype}</logtype>{SIM}</CallLog>"
    )


def call_log(*calls: str) -> str:
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><CallLogs>"
        + "".join(calls)
        + "</CallLogs>"
    )


CALL_LOG = call_log(
    call(name="Mario Rossi", date="1700000002000", type_="1"),
    call(name="", date="1700000001000", duration="12", number="+393330000002", type_="2"),
    call(name="Anna Bianchi", date="1700000003000", duration="0", type_="3", logtype="100"),
    call(name="", date="1700000004000", duration="0", number="", presentation="2", type_="5"),
    call(name="", date="1700000005000", duration="0", number="+393330000009", type_="6"),
)


def build_call_scan_dir(scan_dir: Path, call_log: str = CALL_LOG) -> Path:
    """Write a fake `ssba scan` output tree with a CALLLOG category."""
    exml = scan_dir / "CALLLOG" / "CALLLOG.zip" / "call_log.exml"
    exml.parent.mkdir(parents=True)
    exml.write_text(call_log, encoding="utf-8")
    files = [
        {"path": "CALLLOG.zip/call_log.exml", "status": "decrypted", "kind": "xml", "detail": None},
        {"path": "CALLLOG.zip", "status": "decrypted", "kind": "zip", "detail": None},
    ]
    report = {"categories": [{"category": "CALLLOG", "counts": {}, "files": files}]}
    (scan_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return scan_dir
