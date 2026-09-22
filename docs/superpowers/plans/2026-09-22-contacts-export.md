# Contacts Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ssba export contacts <scan_dir> --out <file.vcf>`, which merges every contact Phase 1 recovered into one clean vCard 3.0 file importable on any device.

**Architecture:** A new `ssba.core.parsers.contact` module reads the output `ssba scan` already wrote (`report.json` + the decrypted tree), parses each recovered vCard card independently with `vobject` after fixing Samsung's malformed headers, normalizes each card to vCard 3.0, and writes one merged file (plus a side file for any card it cannot parse). The CLI gets a thin `export contacts` subcommand on top.

**Tech Stack:** Python 3.10+, `vobject` (new dependency), stdlib `json`/`re`/`dataclasses`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-22-contacts-export-design.md`

Every code block in this plan was run before the plan was written: in a scratch copy of the repo the full suite passed (87 tests: the existing 69 + the 18 below), and the finished command exported all 798 real contacts, which re-parsed cleanly.

## Global Constraints

- Python 3.10+.
- New runtime dependency: `vobject>=0.9.9` (pulls in `python-dateutil`, `pytz`, `six`). No other new dependencies.
- `core/` never prints; only `cli/` does.
- No real personal data in the repository, tests or fixtures.
- No attribution lines in commit messages; commits stay local — nothing is pushed until the project owner says so.

---

### Task 1: Card parsing and vCard 3.0 normalization

**Files:**
- Modify: `pyproject.toml` (dependencies list)
- Create: `src/ssba/core/parsers/__init__.py`
- Create: `src/ssba/core/parsers/contact.py`
- Create: `tests/contact_fixtures.py`
- Test: `tests/test_contact_parser.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (first task of this plan).
- Produces:
  - `ssba.core.parsers.contact.parse_cards(text: str) -> tuple[list[vobject.base.Component], list[str]]` — (normalized vCard 3.0 cards, raw text of cards that failed to parse).
  - `tests.contact_fixtures`: `FAKE_JPEG: bytes`, `GOOGLE_VCF: str`, `PHONE_ONLY_VCF: str`, `PROFILE_VCF: str`, `GOOGLE_NAME: str`, `PHONE_NAME: str`, `CONTAINER: str`, `build_scan_dir(scan_dir: Path, *, google: str = GOOGLE_VCF) -> Path` (Tasks 2 and 3 use `build_scan_dir`).

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, change

```toml
dependencies = [
    "pycryptodome>=3.20",
]
```

to

```toml
dependencies = [
    "pycryptodome>=3.20",
    "vobject>=0.9.9",
]
```

Then run: `pip install -e ".[dev]"`
Expected: installs `vobject` (and `python-dateutil`, `pytz`, `six`) without errors.

- [ ] **Step 2: Create the fixtures module, `tests/contact_fixtures.py`**

These are fabricated cards shaped like Samsung's real exports — including every quirk the spec lists — never real data.

```python
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

GOOGLE_NAME = "@@someone@example.com@@com.google.vcf"
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
```

- [ ] **Step 3: Write the failing tests, `tests/test_contact_parser.py`**

```python
from __future__ import annotations

import base64

import vobject

from ssba.core.parsers.contact import parse_cards
from tests.contact_fixtures import FAKE_JPEG, PROFILE_VCF


def _one(text: str):
    cards, unparsed = parse_cards(text)
    assert unparsed == []
    assert len(cards) == 1
    return cards[0]


def _card(*lines: str) -> str:
    return "BEGIN:VCARD\r\nVERSION:2.1\r\n" + "".join(l + "\r\n" for l in lines) + "END:VCARD\r\n"


def test_malformed_photo_header_parses_and_keeps_bytes():
    b64 = base64.b64encode(FAKE_JPEG).decode()
    card = _one(_card("N:Rossi;Mario;;;", f"PHOTO;ENCODING=BASE64;PREF;JPEG; :{b64}"))
    assert card.photo.value == FAKE_JPEG


def test_empty_parameter_birthday_parses():
    card = _one(_card("N:Rossi;Mario;;;", "BDAY;;:--12-25"))
    assert card.bday.value == "--12-25"


def test_quoted_printable_utf8_name_with_emoji_is_decoded():
    card = _one(_card("N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:;=C3=80nna=F0=9F=92=8B Test;;;"))
    assert card.n.value.given == "Ànna💋 Test"
    assert card.fn.value == "Ànna💋 Test"


def test_group_member_becomes_deduplicated_categories():
    card = _one(_card(
        "N:Rossi;Mario;;;",
        "GROUP_MEMBER;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=4D=79=20=43=6F=6E=74=61=63=74=73",
        "GROUP_MEMBER:Famiglia",
        "GROUP_MEMBER:Famiglia",
    ))
    assert card.categories.value == ["My Contacts", "Famiglia"]
    assert "group-member" not in card.contents


def test_department_is_appended_to_existing_org():
    card = _one(_card("N:Rossi;Mario;;;", "ORG:Example Srl", "DEPARTMENT:Vendite"))
    assert card.org.value == ["Example Srl", "Vendite"]
    assert "department" not in card.contents


def test_department_alone_becomes_org():
    card = _one(_card("N:Rossi;Mario;;;", "DEPARTMENT:Vendite"))
    assert card.org.value == ["Vendite"]


def test_missing_name_falls_back_to_phone_for_fn():
    card = _one(_card("TEL;CELL:+39 333 000 0009"))
    assert card.fn.value == "+39 333 000 0009"


def test_v21_parameters_become_v3_type_and_encoding():
    card = _one(_card("N:Rossi;Mario;;;", "TEL;CELL;PREF:+39 333 000 0001"))
    assert card.tel.params.get("TYPE") == ["CELL", "PREF"]
    assert card.tel.singletonparams == []
    assert "CHARSET" not in card.n.params
    out = card.serialize()
    assert "VERSION:3.0" in out
    assert "TEL;TYPE=CELL,PREF:+39 333 000 0001" in out


def test_unparseable_card_is_kept_raw_and_neighbours_still_parse():
    bad = _card("THIS LINE HAS NO COLON")
    text = _card("N:Uno;Primo;;;") + bad + _card("N:Due;Secondo;;;")
    cards, unparsed = parse_cards(text)
    assert [c.fn.value for c in cards] == ["Primo Uno", "Secondo Due"]
    assert unparsed == [bad.rstrip("\r\n")]


def test_profile_fixture_round_trips_as_vcard3():
    card = _one(PROFILE_VCF)
    again = vobject.readOne(card.serialize())
    assert again.version.value == "3.0"
    assert again.fn.value == "Paolo Verdi"
    assert again.photo.value == FAKE_JPEG
    assert again.org.value == ["Example Srl", "Ufficio Test"]
    assert again.bday.value == "--12-25"
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `pytest tests/test_contact_parser.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'ssba.core.parsers'`.

- [ ] **Step 5: Create `src/ssba/core/parsers/__init__.py`**

```python
"""Category-specific parsers that turn Phase 1's decrypted output into usable files."""
```

- [ ] **Step 6: Create `src/ssba/core/parsers/contact.py`**

```python
"""Merge the contacts Phase 1 recovered into one importable vCard 3.0 file."""

from __future__ import annotations

import re

import vobject

_CARD_RE = re.compile(r"BEGIN:VCARD.*?END:VCARD", re.DOTALL)


def _sanitize(card: str) -> str:
    # Samsung writes headers like "PHOTO;ENCODING=BASE64;PREF;JPEG; :" and
    # "BDAY;;:--12-25"; vobject rejects the empty parameters.
    out = []
    for line in card.splitlines():
        if line[:1] in (" ", "\t") or ":" not in line:
            out.append(line)
            continue
        header, value = line.split(":", 1)
        name, *params = header.split(";")
        params = [p for p in params if p.strip()]
        out.append(";".join([name, *params]) + ":" + value)
    return "\r\n".join(out)


def _params_to_v3(line) -> None:
    line.params.pop("CHARSET", None)
    encoding = line.params.get("ENCODING")
    if encoding and encoding[0].upper() in ("BASE64", "B"):
        line.params["ENCODING"] = ["b"]
    if line.singletonparams:
        types = line.params.setdefault("TYPE", [])
        for param in line.singletonparams:
            if param not in types:
                types.append(param)
        line.singletonparams = []


def _formatted_name(card) -> str:
    if "n" in card.contents:
        name = card.n.value
        pieces = []
        for part in (name.prefix, name.given, name.additional, name.family, name.suffix):
            pieces.extend(part if isinstance(part, (list, tuple)) else [part])
        joined = " ".join(" ".join(p.split()) for p in pieces if p and p.strip())
        if joined:
            return joined
    if "org" in card.contents and card.org.value and card.org.value[0].strip():
        return card.org.value[0].strip()
    for key in ("email", "tel"):
        if key in card.contents and card.contents[key][0].value.strip():
            return card.contents[key][0].value.strip()
    return "Unknown"


def _normalize(card):
    categories: list[str] = []
    for group in card.contents.pop("group-member", []):
        if group.value not in categories:
            categories.append(group.value)
    if categories:
        card.add("categories").value = categories

    departments = card.contents.pop("department", [])
    if departments:
        department = departments[0].value
        if "org" in card.contents:
            first = card.org.value[0] if card.org.value else ""
            card.org.value = [first, department]
        else:
            card.add("org").value = [department]

    if "fn" not in card.contents:
        card.add("fn").value = _formatted_name(card)

    for lines in card.contents.values():
        for line in lines:
            _params_to_v3(line)
    card.version.value = "3.0"
    return card


def parse_cards(text: str) -> tuple[list, list[str]]:
    """Parse every vCard in ``text`` independently.

    Returns the normalized vCard 3.0 components and the raw text of every card
    that could not be parsed, so a single bad card never loses the others.
    """
    cards, unparsed = [], []
    for raw in _CARD_RE.findall(text):
        try:
            card = vobject.readOne(_sanitize(raw))
        except Exception:
            unparsed.append(raw)
            continue
        cards.append(_normalize(card))
    return cards, unparsed
```

Notes for the implementer (why the code looks like this — verified while writing the plan, don't "simplify" these away):
- `vobject` stores the Samsung `GROUP_MEMBER` property under the key `"group-member"` (underscore turned into a hyphen), so that is the key popped.
- `vobject` refuses to serialize a card without `FN`, and on its own it re-emits 2.1 bare parameters (`TEL;CELL`) and crashes serializing a 2.1 `PHOTO;ENCODING=BASE64` — `_params_to_v3` is what fixes both.
- `_sanitize` must run before parsing; without it 110 of the 795 real Google contacts and the owner's profile are lost.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/test_contact_parser.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 8: Run the full suite**

Run: `pytest -q`
Expected: 79 passed (69 existing + 10 new), no warnings.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml src/ssba/core/parsers/__init__.py src/ssba/core/parsers/contact.py tests/contact_fixtures.py tests/test_contact_parser.py
git commit -m "Add vCard parsing and 3.0 normalization for recovered contacts"
```

---

### Task 2: Discover recovered contact files and export them as one file

**Files:**
- Modify: `src/ssba/core/parsers/contact.py` (import block; append new code at the end)
- Test: `tests/test_contact_export.py`

**Interfaces:**
- Consumes: `parse_cards(text: str) -> tuple[list, list[str]]` (Task 1, same module); `tests.contact_fixtures.build_scan_dir`, `GOOGLE_NAME`, `GOOGLE_VCF`, `PHONE_NAME` (Task 1).
- Produces (all in `ssba.core.parsers.contact`):
  - `ContactExportError(Exception)`
  - `ContactSource` — frozen dataclass: `path: Path`, `label: str`, `is_profile: bool`
  - `ContactExportResult` — dataclass: `exported: int`, `per_source: dict[str, int]`, `unparsed: int = 0`, `unparsed_path: Path | None = None`
  - `find_contact_sources(scan_dir: Path) -> list[ContactSource]`
  - `export_contacts(scan_dir: Path, out_path: Path) -> ContactExportResult`

- [ ] **Step 1: Write the failing tests, `tests/test_contact_export.py`**

```python
from __future__ import annotations

import pytest
import vobject

from ssba.core.parsers.contact import (
    ContactExportError,
    export_contacts,
    find_contact_sources,
)
from tests.contact_fixtures import GOOGLE_NAME, GOOGLE_VCF, PHONE_NAME, build_scan_dir


def test_find_sources_returns_vcf_files_profile_first(tmp_path):
    scan_dir = build_scan_dir(tmp_path / "scan")
    sources = find_contact_sources(scan_dir)
    assert [s.label for s in sources] == ["profile.vcf", GOOGLE_NAME, PHONE_NAME]
    assert [s.is_profile for s in sources] == [True, False, False]
    assert all(s.path.is_file() for s in sources)


def test_find_sources_without_report_raises(tmp_path):
    with pytest.raises(ContactExportError, match="report.json"):
        find_contact_sources(tmp_path)


def test_find_sources_without_contact_category_raises(tmp_path):
    (tmp_path / "report.json").write_text('{"categories": []}', encoding="utf-8")
    with pytest.raises(ContactExportError, match="CONTACT"):
        find_contact_sources(tmp_path)


def test_export_merges_all_sources_as_vcard3(tmp_path):
    scan_dir = build_scan_dir(tmp_path / "scan")
    out = tmp_path / "export" / "contacts.vcf"

    result = export_contacts(scan_dir, out)

    assert result.exported == 4
    assert result.per_source == {"profile.vcf": 1, GOOGLE_NAME: 2, PHONE_NAME: 1}
    assert result.unparsed == 0
    assert result.unparsed_path is None
    assert not (tmp_path / "export" / "contacts_unparsed.vcf").exists()

    cards = list(vobject.readComponents(out.read_text(encoding="utf-8")))
    assert [c.fn.value for c in cards] == ["Paolo Verdi", "Mario Rossi", "Ànna💋 Test", "Lucia Bianchi"]
    assert all(c.version.value == "3.0" for c in cards)


def test_export_writes_unparsed_cards_to_side_file(tmp_path):
    broken = "BEGIN:VCARD\r\nVERSION:2.1\r\nTHIS LINE HAS NO COLON\r\nEND:VCARD\r\n"
    scan_dir = build_scan_dir(tmp_path / "scan", google=GOOGLE_VCF + broken)
    out = tmp_path / "contacts.vcf"

    result = export_contacts(scan_dir, out)

    assert result.exported == 4
    assert result.unparsed == 1
    assert result.unparsed_path == tmp_path / "contacts_unparsed.vcf"
    assert "THIS LINE HAS NO COLON" in result.unparsed_path.read_text(encoding="utf-8")


def test_export_with_no_vcf_sources_raises(tmp_path):
    (tmp_path / "report.json").write_text(
        '{"categories": [{"category": "CONTACT", "counts": {}, "files": []}]}', encoding="utf-8"
    )
    with pytest.raises(ContactExportError, match="no contact"):
        export_contacts(tmp_path, tmp_path / "contacts.vcf")
```

(The fixture's `report.json` deliberately also lists a non-`.vcf` file, an `error` entry and an entry whose file is missing on disk — the first test proves all three are skipped.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_contact_export.py -v`
Expected: collection error — `ImportError: cannot import name 'ContactExportError'`.

- [ ] **Step 3: Replace the import block of `src/ssba/core/parsers/contact.py`**

Replace

```python
from __future__ import annotations

import re

import vobject

_CARD_RE = re.compile(r"BEGIN:VCARD.*?END:VCARD", re.DOTALL)
```

with

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import vobject

_CARD_RE = re.compile(r"BEGIN:VCARD.*?END:VCARD", re.DOTALL)
_EXPORTABLE_STATUSES = {"decrypted", "plaintext_passthrough"}


class ContactExportError(Exception):
    """Raised when no contacts can be exported from a scan output directory."""


@dataclass(frozen=True)
class ContactSource:
    path: Path
    label: str
    is_profile: bool


@dataclass
class ContactExportResult:
    exported: int
    per_source: dict[str, int] = field(default_factory=dict)
    unparsed: int = 0
    unparsed_path: Path | None = None
```

- [ ] **Step 4: Append discovery and export at the end of `src/ssba/core/parsers/contact.py`**

```python
def find_contact_sources(scan_dir: Path) -> list[ContactSource]:
    report_path = scan_dir / "report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContactExportError(f"report.json not found in {scan_dir}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ContactExportError(f"report.json is not readable: {exc}") from exc

    category = next(
        (c for c in report.get("categories", []) if c.get("category") == "CONTACT"),
        None,
    )
    if category is None:
        raise ContactExportError("the scan report has no CONTACT category")

    sources = []
    for entry in category.get("files", []):
        rel = entry.get("path", "")
        if not rel.lower().endswith(".vcf") or entry.get("status") not in _EXPORTABLE_STATUSES:
            continue
        path = scan_dir / "CONTACT" / rel
        if not path.is_file():
            continue
        label = path.name
        sources.append(ContactSource(path=path, label=label, is_profile=label.lower() == "profile.vcf"))
    sources.sort(key=lambda s: (not s.is_profile, s.label))
    return sources


def export_contacts(scan_dir: Path, out_path: Path) -> ContactExportResult:
    sources = find_contact_sources(scan_dir)
    if not sources:
        raise ContactExportError("no contact .vcf files found in the scan output")

    serialized: list[str] = []
    unparsed: list[str] = []
    result = ContactExportResult(exported=0)
    for source in sources:
        cards, bad = parse_cards(source.path.read_text(encoding="utf-8", errors="replace"))
        serialized.extend(card.serialize() for card in cards)
        unparsed.extend(bad)
        result.per_source[source.label] = len(cards)
        result.exported += len(cards)

    if result.exported == 0:
        raise ContactExportError("no contacts could be parsed from the recovered .vcf files")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(serialized), encoding="utf-8", newline="")
    if unparsed:
        unparsed_path = out_path.with_name(f"{out_path.stem}_unparsed.vcf")
        unparsed_path.write_text("\r\n".join(unparsed) + "\r\n", encoding="utf-8", newline="")
        result.unparsed = len(unparsed)
        result.unparsed_path = unparsed_path
    return result
```

(`newline=""` keeps vobject's CRLF line endings exactly as vCard requires — without it, Windows text mode would turn them into CR CR LF.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_contact_export.py tests/test_contact_parser.py -v`
Expected: all 16 tests PASS.

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: 85 passed, no warnings.

- [ ] **Step 7: Commit**

```bash
git add src/ssba/core/parsers/contact.py tests/test_contact_export.py
git commit -m "Discover recovered contact files and export them as one vCard 3.0 file"
```

---

### Task 3: `ssba export contacts` CLI subcommand

**Files:**
- Modify: `src/ssba/cli/main.py` (imports; `build_arg_parser`; new `_run_export_contacts`; `run`)
- Modify: `tests/test_cli.py` (one import; two tests appended)
- Modify: `README.md` (Usage section)

**Interfaces:**
- Consumes: `ContactExportError`, `export_contacts(scan_dir: Path, out_path: Path) -> ContactExportResult` with fields `exported`, `per_source`, `unparsed`, `unparsed_path` (Task 2); `tests.contact_fixtures.build_scan_dir` (Task 1).
- Produces: the `ssba export contacts <scan_dir> --out <file.vcf>` command; exit 0 when at least one contact was exported, exit 1 with `error: ...` on stderr on `ContactExportError`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, replace the import line

```python
from tests.crypto_helpers import encrypt_dummy_ecb, encrypt_iv_prefixed
```

with

```python
from tests.contact_fixtures import build_scan_dir
from tests.crypto_helpers import encrypt_dummy_ecb, encrypt_iv_prefixed
```

and append at the end of the file:

```python


def test_export_contacts_success(tmp_path, capsys):
    scan_dir = build_scan_dir(tmp_path / "scan")
    out = tmp_path / "contacts.vcf"

    exit_code = run(["export", "contacts", str(scan_dir), "--out", str(out)])

    assert exit_code == 0
    assert out.is_file()
    captured = capsys.readouterr()
    assert "profile.vcf: 1 contacts" in captured.out
    assert "4 contacts written to" in captured.out


def test_export_contacts_missing_report(tmp_path, capsys):
    exit_code = run(["export", "contacts", str(tmp_path), "--out", str(tmp_path / "c.vcf")])

    assert exit_code == 1
    assert "report.json" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: the two new tests FAIL — argparse rejects `export` (`invalid choice: 'export'`, exits with code 2 → `SystemExit`); the existing CLI tests still pass.

- [ ] **Step 3: Implement the subcommand in `src/ssba/cli/main.py`**

Replace

```python
from ssba.core.errors import UnsupportedBackupError
from ssba.core.scanner import scan_backup
```

with

```python
from ssba.core.errors import UnsupportedBackupError
from ssba.core.parsers.contact import ContactExportError, export_contacts
from ssba.core.scanner import scan_backup
```

Replace the end of `build_arg_parser`

```python
        help="only scan this category (repeatable); defaults to every category found",
    )

    return parser
```

with

```python
        help="only scan this category (repeatable); defaults to every category found",
    )

    export_parser = subparsers.add_parser(
        "export", help="turn `ssba scan` output into files you can import elsewhere"
    )
    export_kinds = export_parser.add_subparsers(dest="export_kind", required=True)
    contacts_parser = export_kinds.add_parser(
        "contacts", help="merge the recovered contacts into one vCard 3.0 file"
    )
    contacts_parser.add_argument(
        "scan_dir", type=Path, help="directory written by `ssba scan --out`"
    )
    contacts_parser.add_argument(
        "--out", type=Path, required=True, help="path of the .vcf file to write"
    )

    return parser


def _run_export_contacts(scan_dir: Path, out: Path) -> int:
    try:
        result = export_contacts(scan_dir, out)
    except ContactExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for label, count in result.per_source.items():
        print(f"{label}: {count} contacts")
    print(f"\n{result.exported} contacts written to {out}")
    if result.unparsed:
        print(
            f"{result.unparsed} contacts could not be parsed; "
            f"kept unchanged in {result.unparsed_path}"
        )
    return 0
```

Replace the end of `run`

```python
        print(f"\nfull report written to {report_path}")
        return 0 if any_success else 1

    return 1
```

with

```python
        print(f"\nfull report written to {report_path}")
        return 0 if any_success else 1

    if args.command == "export" and args.export_kind == "contacts":
        return _run_export_contacts(args.scan_dir, args.out)

    return 1
```

- [ ] **Step 4: Document the command in `README.md`**

In the `## Usage` section, replace

```markdown
This writes decrypted category data under `./recovered/<CATEGORY>/...` and a
`./recovered/report.json` summary.
```

with

~~~markdown
This writes decrypted category data under `./recovered/<CATEGORY>/...` and a
`./recovered/report.json` summary.

Then turn the recovered contacts into one file you can import on any phone or
contacts service (Google Contacts, iCloud, Outlook, another Android phone):

```bash
ssba export contacts ./recovered --out contacts.vcf
```

It merges every account's contacts found in the backup — including contacts
that were stored only on the phone and never synced anywhere — plus your own
profile card, as vCard 3.0. Any card that can't be read is kept unchanged in
`contacts_unparsed.vcf` instead of being dropped.
~~~

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: all CLI tests PASS, including the two new ones.

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: 87 passed, no warnings.

- [ ] **Step 7: Commit**

```bash
git add src/ssba/cli/main.py tests/test_cli.py README.md
git commit -m "Add ssba export contacts command"
```

---

### Task 4: Manual validation on the real backup (not committed)

**Files:** none — this runs the finished command on the project owner's real scan output and writes only into `out/`, which is git-ignored.

**Interfaces:**
- Consumes: the `ssba export contacts` command (Task 3); the existing real scan output at `D:\SmartSwitch-Backup-Analyzer\out\real-scan\real-scan-v3` (the folder that holds `report.json`).

- [ ] **Step 1: Run the export**

Run: `ssba export contacts "D:/SmartSwitch-Backup-Analyzer/out/real-scan/real-scan-v3" --out "D:/SmartSwitch-Backup-Analyzer/out/contacts/contacts.vcf"`
Expected: `profile.vcf: 1 contacts`, the Google file `795 contacts`, the phone-only file `2 contacts`, `798 contacts written to ...`, no unparsed line; exit code 0.

- [ ] **Step 2: Check the output**

Run (PowerShell or bash with `PYTHONIOENCODING=utf-8`):

```bash
python -c "import vobject; cs=list(vobject.readComponents(open('D:/SmartSwitch-Backup-Analyzer/out/contacts/contacts.vcf', encoding='utf-8').read())); print(len(cs), cs[0].fn.value, len(cs[0].photo.value), all(c.version.value=='3.0' and 'fn' in c.contents for c in cs))"
```

Expected: `798`, the owner's name first, a photo of about 308 000 bytes, `True`.

- [ ] **Step 3: Confirm nothing personal got staged**

Run: `git status --short`
Expected: no `out/` paths listed.
