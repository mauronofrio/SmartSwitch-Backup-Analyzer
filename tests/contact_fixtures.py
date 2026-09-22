"""Fabricated vCard fixtures shaped like Samsung's real exports (no real data)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

FAKE_JPEG = b"\xff\xd8\xff\xe0FAKEJPEGBYTES"
_JPEG_B64 = base64.b64encode(FAKE_JPEG).decode()

GOOGLE_VCF = (
    "BEGIN:VCARD\r\n"
    "VERSION:2.1\r\n"
    "N:Rossi;Mario;;;\r\n"
    "TEL;CELL:+39 333 000 0001\r\n"
    "GROUP_MEMBER;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=4D=79=20=43=6F=6E=74=61=63=74=73\r\n"
    "END:VCARD\r\n"
    "BEGIN:VCARD\r\n"
    "VERSION:2.1\r\n"
    "N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:;=C3=80nna=F0=9F=92=8B Test;;;\r\n"
    "TEL;CELL;PREF:+39 333 000 0002\r\n"
    "END:VCARD\r\n"
)

PHONE_ONLY_VCF = (
    "BEGIN:VCARD\r\n"
    "VERSION:2.1\r\n"
    "N:Bianchi;Lucia;;;\r\n"
    "TEL;CELL:+39 333 000 0003\r\n"
    "END:VCARD\r\n"
)

PROFILE_VCF = (
    "BEGIN:VCARD\r\n"
    "VERSION:2.1\r\n"
    "N:Verdi;Paolo;;;\r\n"
    "EMAIL;WORK:paolo@example.com\r\n"
    "ORG:Example Srl\r\n"
    "DEPARTMENT:Ufficio Test\r\n"
    "BDAY;;:--12-25\r\n"
    f"PHOTO;ENCODING=BASE64;PREF;JPEG; :{_JPEG_B64}\r\n"
    "\r\n"
    "END:VCARD\r\n"
)


def android_qp(text: str) -> str:
    """Quoted-printable exactly as Android's vCard 2.1 writer emits it.

    Every UTF-8 byte becomes ``=XX`` and a soft line break (``=`` + CRLF, with no
    leading space on the next line) is inserted every 67 characters -- also right
    at the end of a value that fills the line exactly.
    """
    out, count = [], 0
    for byte in text.encode("utf-8"):
        out.append(f"={byte:02X}")
        count += 3
        if count >= 67:
            out.append("=\r\n")
            count = 0
    return "".join(out)


QP = "CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE"

# Cards whose values break a naive vCard 2.1 -> 3.0 conversion: unescaped commas,
# semicolons inside quoted-printable text, soft line breaks, newlines, emoji.
TRICKY_VCF = (
    "BEGIN:VCARD\r\n"
    "VERSION:2.1\r\n"
    "N:Neri, Jr.;Carlo;;;\r\n"
    "TEL;CELL:+39 333 000 0010\r\n"
    "ORG:Acme, Inc.\r\n"
    "DEPARTMENT:Sales, North\r\n"
    "TITLE:CEO, founder\r\n"
    "NOTE:hello, world\r\n"
    "GROUP_MEMBER:Friends, Family\r\n"
    "X-ANDROID-CUSTOM:vnd.android.cursor.item/nickname;Carletto, the Great;1;;;;;;;;;;;;;\r\n"
    "X-FAVORITE:1\r\n"
    "END:VCARD\r\n"
    "BEGIN:VCARD\r\n"
    "VERSION:2.1\r\n"
    f"N;{QP}:{android_qp('Gialli, Sr.')};{android_qp('Élodie 💋')};;;\r\n"
    f"ORG;{QP}:{android_qp('Società, Uno; Due')}\r\n"
    f"TITLE;{QP}:{android_qp('Direttrice, capo; reparto')}\r\n"
    f"NOTE;{QP}:"
    + android_qp("Prima riga, con virgola; e punto e virgola\nseconda riga 😀 fine, davvero")
    + "\r\n"
    f"GROUP_MEMBER;{QP}:{android_qp('Colleghi, ufficio')}\r\n"
    f"X-ANDROID-CUSTOM;{QP}:{android_qp('vnd.sec.cursor.item/emergency_info')};;"
    f"{android_qp('via Roma 1, 00100 Roma, piano 3')};;;;;;;;;;;;;\r\n"
    "END:VCARD\r\n"
)

GOOGLE_NAME ="@@someone@example.com@@com.google.vcf"
PHONE_NAME = "@@vnd.sec.contact.phone@@vnd.sec.contact.phone.vcf"
CONTAINER = "Contact.spbm/Contact.bk"


def build_scan_dir(scan_dir: Path, *, google: str = GOOGLE_VCF) -> Path:
    """Write a fake `ssba scan` output tree with a CONTACT category."""
    contact_dir = scan_dir / "CONTACT" / CONTAINER
    contact_dir.mkdir(parents=True)
    (contact_dir / GOOGLE_NAME).write_text(google, encoding="utf-8", newline="")
    (contact_dir / PHONE_NAME).write_text(PHONE_ONLY_VCF, encoding="utf-8", newline="")
    (contact_dir / "profile.vcf").write_text(PROFILE_VCF, encoding="utf-8", newline="")
    (contact_dir / "SpeedDials.json").write_text("{}", encoding="utf-8")
    files = [
        {"path": "Contact.spbm", "status": "plaintext_passthrough", "kind": "zip", "detail": None},
        {"path": f"{CONTAINER}/{GOOGLE_NAME}", "status": "plaintext_passthrough", "kind": "text", "detail": None},
        {"path": f"{CONTAINER}/{PHONE_NAME}", "status": "plaintext_passthrough", "kind": "text", "detail": None},
        {"path": f"{CONTAINER}/profile.vcf", "status": "plaintext_passthrough", "kind": "text", "detail": None},
        {"path": f"{CONTAINER}/SpeedDials.json", "status": "plaintext_passthrough", "kind": "json", "detail": None},
        {"path": f"{CONTAINER}/broken.vcf", "status": "error", "kind": None, "detail": "boom"},
        {"path": f"{CONTAINER}/missing.vcf", "status": "plaintext_passthrough", "kind": "text", "detail": None},
    ]
    report = {"categories": [
        {"category": "CALLLOG", "counts": {}, "files": []},
        {"category": "CONTACT", "counts": {}, "files": files},
    ]}
    (scan_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return scan_dir
