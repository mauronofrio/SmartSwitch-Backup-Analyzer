# SMS and Call Log Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ssba export messages` and `ssba export calls`, which turn the Google Messages database and the Samsung call log from `ssba scan` output into SMS Backup & Restore XML files.

**Architecture:** A shared `scan_report` helper lists a category's files from `report.json` (extracted from the contacts exporter). A shared `sbr_xml` module holds the XML rules (invalid-character replacement, writing, `_unsupported.json` side file). `messages.py` reads the SQLite database read-only; `calls.py` reads `call_log.exml`; the CLI adds two subcommands in the style of `export contacts`.

**Tech Stack:** Python 3.10+, stdlib only (`sqlite3`, `xml.etree.ElementTree`, `json`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-23-sms-calls-export-design.md`

## Global Constraints

- Python 3.10+. No new dependencies (`sqlite3`, `xml.etree` are stdlib).
- `core/` never prints; only `cli/` does.
- No real personal data in the repository, tests or fixtures.
- No attribution lines in commit messages; commits stay local — nothing is pushed until the project owner says so.
- Work directly on `master` (project owner's instruction).
- Run tests with `python -m pytest` from the repository root `D:/SmartSwitch-Backup-Analyzer`. On Windows use `D:/...` paths, never MSYS `/d/...` paths, when passing paths to Python.
- Files are LF-terminated; edit with an editor tool, not with scripts that rewrite whole files.

---

### Task 1: Shared scan-report helper

**Files:**
- Create: `src/ssba/core/parsers/scan_report.py`
- Create: `tests/test_scan_report.py`
- Modify: `src/ssba/core/parsers/contact.py` (`find_contact_sources`, imports, `_EXPORTABLE_STATUSES`)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `ssba.core.parsers.scan_report.ScanReportError(Exception)`
  - `ssba.core.parsers.scan_report.category_files(scan_dir: Path, category: str) -> list[Path]`
  - `ssba.core.parsers.scan_report.EXPORTABLE_STATUSES: frozenset[str]`

- [ ] **Step 1: Write the failing tests** — `tests/test_scan_report.py`:

```python
from __future__ import annotations

import json

import pytest

from ssba.core.parsers.scan_report import ScanReportError, category_files


def _write_report(scan_dir, files, category="CALLLOG"):
    scan_dir.mkdir(parents=True, exist_ok=True)
    report = {"categories": [
        {"category": "OTHER", "counts": {}, "files": []},
        {"category": category, "counts": {}, "files": files},
    ]}
    (scan_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_returns_exportable_files_in_report_order(tmp_path):
    b = _touch(tmp_path / "CALLLOG" / "CALLLOG.zip" / "b.exml")
    a = _touch(tmp_path / "CALLLOG" / "a.exml")
    _write_report(tmp_path, [
        {"path": "CALLLOG.zip", "status": "plaintext_passthrough"},  # a directory
        {"path": "CALLLOG.zip/b.exml", "status": "decrypted"},
        {"path": "a.exml", "status": "plaintext_passthrough"},
    ])
    assert category_files(tmp_path, "CALLLOG") == [b, a]


def test_skips_bad_status_malformed_missing_and_escaping_entries(tmp_path):
    good = _touch(tmp_path / "CALLLOG" / "good.exml")
    _touch(tmp_path / "CALLLOG" / "undecoded.exml")
    _touch(tmp_path / "outside.exml")
    _write_report(tmp_path, [
        "not a dict",
        {"path": None, "status": "decrypted"},
        {"status": "decrypted"},
        {"path": "", "status": "decrypted"},
        {"path": "undecoded.exml", "status": "undecoded"},
        {"path": "error.exml", "status": "error"},
        {"path": "missing.exml", "status": "decrypted"},
        {"path": "../outside.exml", "status": "decrypted"},
        {"path": str(tmp_path / "outside.exml"), "status": "decrypted"},
        {"path": "good.exml", "status": "decrypted"},
    ])
    assert category_files(tmp_path, "CALLLOG") == [good]


def test_files_that_is_not_a_list_gives_no_files(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    report = {"categories": [{"category": "CALLLOG", "files": "nope"}]}
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    assert category_files(tmp_path, "CALLLOG") == []


def test_missing_report_raises(tmp_path):
    with pytest.raises(ScanReportError, match="report.json not found"):
        category_files(tmp_path, "CALLLOG")


@pytest.mark.parametrize("content", [b"{not json", b"\xff\xfe{", b"[]", b'{"categories": {}}'])
def test_unreadable_report_raises(tmp_path, content):
    (tmp_path / "report.json").write_bytes(content)
    with pytest.raises(ScanReportError, match="report.json is not readable"):
        category_files(tmp_path, "CALLLOG")


def test_missing_category_raises_naming_it(tmp_path):
    _write_report(tmp_path, [], category="CONTACT")
    with pytest.raises(ScanReportError, match="the scan report has no GMMESSAGE category"):
        category_files(tmp_path, "GMMESSAGE")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_scan_report.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'ssba.core.parsers.scan_report'`.

- [ ] **Step 3: Implement** — `src/ssba/core/parsers/scan_report.py`:

```python
"""Read the report.json `ssba scan` writes and list a category's files safely."""

from __future__ import annotations

import json
from pathlib import Path

EXPORTABLE_STATUSES = frozenset({"decrypted", "plaintext_passthrough"})


class ScanReportError(Exception):
    """Raised when report.json is missing, unreadable, or lacks the category."""


def category_files(scan_dir: Path, category: str) -> list[Path]:
    """Return, in report order, the recovered files of ``category`` on disk.

    Only entries Phase 1 decrypted or passed through are kept, and only when
    they resolve to a file inside ``scan_dir / category``.
    """
    report_path = scan_dir / "report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScanReportError(f"report.json not found in {scan_dir}") from exc
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ScanReportError(f"report.json is not readable: {exc}") from exc

    if not isinstance(report, dict):
        raise ScanReportError("report.json is not readable: top level is not an object")
    categories = report.get("categories", [])
    if not isinstance(categories, list):
        raise ScanReportError("report.json is not readable: categories is not a list")

    entry = next(
        (c for c in categories if isinstance(c, dict) and c.get("category") == category),
        None,
    )
    if entry is None:
        raise ScanReportError(f"the scan report has no {category} category")

    files = entry.get("files", [])
    if not isinstance(files, list):
        return []

    root = scan_dir / category
    try:
        root_resolved = root.resolve()
    except (OSError, ValueError):
        root_resolved = root

    paths: list[Path] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        rel = item.get("path")
        if not isinstance(rel, str) or not rel:
            continue
        if item.get("status") not in EXPORTABLE_STATUSES:
            continue
        path = root / rel
        # Defense against path traversal: the file must stay inside the category.
        try:
            if not path.resolve().is_relative_to(root_resolved):
                continue
        except (OSError, ValueError):
            continue
        if path.is_file():
            paths.append(path)
    return paths
```

- [ ] **Step 4: Run the new tests**

Run: `python -m pytest tests/test_scan_report.py -v`
Expected: all PASS.

- [ ] **Step 5: Make `find_contact_sources` use the helper.** In `src/ssba/core/parsers/contact.py`, replace the whole body of `find_contact_sources` with:

```python
def find_contact_sources(scan_dir: Path) -> list[ContactSource]:
    try:
        paths = category_files(scan_dir, "CONTACT")
    except ScanReportError as exc:
        raise ContactExportError(str(exc)) from exc
    sources = [
        ContactSource(path=path, label=path.name, is_profile=path.name.lower() == "profile.vcf")
        for path in paths
        if path.name.lower().endswith(".vcf")
    ]
    sources.sort(key=lambda s: (not s.is_profile, s.label))
    return sources
```

Add `from ssba.core.parsers.scan_report import ScanReportError, category_files` to the imports. Delete the module constant `_EXPORTABLE_STATUSES` and the `import json` line if nothing else in `contact.py` uses them (check with a search before deleting).

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest -q`
Expected: all PASS (contact tests unchanged, including `test_find_sources_skips_malformed_entries`, `test_find_sources_skips_path_traversal_attempts`, `test_find_sources_with_invalid_report_structure_raises`, `test_find_sources_with_non_utf8_report_raises`).

- [ ] **Step 7: Commit**

```bash
git add src/ssba/core/parsers/scan_report.py src/ssba/core/parsers/contact.py tests/test_scan_report.py
git commit -m "refactor: share report.json reading between exporters"
```

---

### Task 2: Shared SMS Backup & Restore XML writer and call log export

**Files:**
- Create: `src/ssba/core/parsers/sbr_xml.py`
- Create: `src/ssba/core/parsers/calls.py`
- Create: `tests/call_fixtures.py`
- Create: `tests/test_calls_export.py`

**Interfaces:**
- Consumes: `category_files(scan_dir: Path, category: str) -> list[Path]`, `ScanReportError` (Task 1).
- Produces:
  - `ssba.core.parsers.sbr_xml.TextCleaner` — callable `(text: str) -> str`, attribute `replaced: int`.
  - `ssba.core.parsers.sbr_xml.write_document(root: ET.Element, out_path: Path, unsupported: list[dict], error: type[Exception]) -> Path | None` — returns the side file path when written, else `None`.
  - `ssba.core.parsers.calls.CallExportError(Exception)`
  - `ssba.core.parsers.calls.CallExportResult` dataclass: `exported: int`, `unknown_types: int = 0`, `unsupported: int = 0`, `unsupported_path: Path | None = None`, `replaced_chars: int = 0`.
  - `ssba.core.parsers.calls.export_calls(scan_dir: Path, out_path: Path) -> CallExportResult`
  - `tests.call_fixtures.build_call_scan_dir(scan_dir: Path, call_log: str = CALL_LOG) -> Path`

- [ ] **Step 1: Write the fixtures** — `tests/call_fixtures.py` (fabricated data only):

```python
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
```

- [ ] **Step 2: Write the failing tests** — `tests/test_calls_export.py`:

```python
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
    assert clean("a\x07b\x00c\td\ne\rf\ufffeg") == "a\ufffdb\ufffdc\td\ne\rf\ufffdg"
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_calls_export.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'ssba.core.parsers.calls'`.

- [ ] **Step 4: Implement the shared writer** — `src/ssba/core/parsers/sbr_xml.py`:

```python
"""Shared rules for writing SMS Backup & Restore XML files."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# Characters XML 1.0 forbids even as character references.
_INVALID_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff\ud800-\udfff]")


class TextCleaner:
    """Replace characters XML 1.0 forbids with U+FFFD, counting them."""

    def __init__(self) -> None:
        self.replaced = 0

    def __call__(self, text: str) -> str:
        cleaned, count = _INVALID_XML_CHARS.subn("\ufffd", text)
        self.replaced += count
        return cleaned


def write_document(
    root: ET.Element,
    out_path: Path,
    unsupported: list[dict],
    error: type[Exception],
) -> Path | None:
    """Write ``root`` to ``out_path`` and the rows that could not be converted
    to ``<stem>_unsupported.json`` beside it.

    Returns the side file's path when one was written. A side file left by an
    earlier run is deleted on a clean run, since it would claim rows are
    missing. Any write failure is raised as ``error``.
    """
    side_path = out_path.with_name(f"{out_path.stem}_unsupported.json")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(out_path, encoding="utf-8", xml_declaration=True)
        if not unsupported:
            side_path.unlink(missing_ok=True)
            return None
        # ensure_ascii keeps undecodable source bytes (lone surrogates) writable.
        side_path.write_text(json.dumps(unsupported, indent=2), encoding="utf-8")
        return side_path
    except OSError as exc:
        raise error(f"cannot write {exc.filename or out_path}: {exc}") from exc
```

- [ ] **Step 5: Implement the call exporter** — `src/ssba/core/parsers/calls.py`:

```python
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
                presentation = _integer(entry, "presentation", 1)
            except ValueError as exc:
                unsupported.append({
                    "reason": str(exc),
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
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_calls_export.py -v`
Expected: all PASS. Then `python -m pytest -q`: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/ssba/core/parsers/sbr_xml.py src/ssba/core/parsers/calls.py tests/call_fixtures.py tests/test_calls_export.py
git commit -m "feat: export the call log as SMS Backup & Restore XML"
```

---

### Task 3: Message export

**Files:**
- Create: `src/ssba/core/parsers/messages.py`
- Create: `tests/message_fixtures.py`
- Create: `tests/test_messages_export.py`

**Interfaces:**
- Consumes: `category_files`, `ScanReportError` (Task 1); `TextCleaner`, `write_document` (Task 2).
- Produces:
  - `ssba.core.parsers.messages.MessageExportError(Exception)`
  - `ssba.core.parsers.messages.MessageExportResult` dataclass: `exported: int`, `rcs_as_sms: int = 0`, `system_skipped: int = 0`, `unsupported: int = 0`, `unsupported_path: Path | None = None`, `replaced_chars: int = 0`.
  - `ssba.core.parsers.messages.export_messages(scan_dir: Path, out_path: Path) -> MessageExportResult`
  - `tests.message_fixtures.build_message_scan_dir(scan_dir: Path, **tables) -> Path`

- [ ] **Step 1: Write the fixtures** — `tests/message_fixtures.py` (fabricated data; the schema is a reduced copy of Google Messages' backup tables):

```python
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
```

- [ ] **Step 2: Write the failing tests** — `tests/test_messages_export.py`:

```python
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
    assert sorted(p.name for p in db.parent.iterdir()) == [DB_NAME, "d2d_item_info.json"]


def test_clean_export_removes_a_stale_side_file(tmp_path):
    stale = tmp_path / "export" / "sms_unsupported.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("[]", encoding="utf-8")
    result, _ = _export(tmp_path, **ONE_TO_ONE)
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_messages_export.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'ssba.core.parsers.messages'`.

- [ ] **Step 4: Implement** — `src/ssba/core/parsers/messages.py`:

```python
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
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_messages_export.py -v`
Expected: all PASS. Then `python -m pytest -q`: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ssba/core/parsers/messages.py tests/message_fixtures.py tests/test_messages_export.py
git commit -m "feat: export Google Messages texts as SMS Backup & Restore XML"
```

---

### Task 4: CLI subcommands

**Files:**
- Modify: `src/ssba/cli/main.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `export_messages`, `MessageExportError`, `MessageExportResult` (Task 3); `export_calls`, `CallExportError`, `CallExportResult` (Task 2); `build_message_scan_dir` (`tests/message_fixtures.py`), `build_call_scan_dir` (`tests/call_fixtures.py`).
- Produces: `ssba export messages <scan_dir> --out <file>` and `ssba export calls <scan_dir> --out <file>`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_cli.py` (and add the two fixture imports at the top, next to `build_scan_dir`):

```python
from tests.call_fixtures import build_call_scan_dir
from tests.message_fixtures import build_message_scan_dir
```

```python
def test_export_messages_success(tmp_path, capsys):
    scan_dir = build_message_scan_dir(tmp_path / "scan")
    out = tmp_path / "sms.xml"

    exit_code = run(["export", "messages", str(scan_dir), "--out", str(out)])

    assert exit_code == 0
    assert out.is_file()
    printed = capsys.readouterr().out
    assert f"3 messages written to {out}" in printed
    assert "1 RCS messages converted to SMS" in printed
    assert "1 system messages skipped" in printed
    assert f"1 messages could not be converted; kept in {tmp_path / 'sms_unsupported.json'}" in printed
    assert "invalid characters" not in printed


def test_export_messages_missing_report(tmp_path, capsys):
    exit_code = run(["export", "messages", str(tmp_path), "--out", str(tmp_path / "s.xml")])
    assert exit_code == 1
    assert capsys.readouterr().err.startswith("error: report.json not found")


def test_export_messages_unwritable_out(tmp_path, capsys):
    scan_dir = build_message_scan_dir(tmp_path / "scan")
    out = tmp_path / "sms.xml"
    out.mkdir()
    exit_code = run(["export", "messages", str(scan_dir), "--out", str(out)])
    assert exit_code == 1
    assert capsys.readouterr().err.startswith("error: cannot write")


def test_export_calls_success(tmp_path, capsys):
    scan_dir = build_call_scan_dir(tmp_path / "scan")
    out = tmp_path / "calls.xml"

    exit_code = run(["export", "calls", str(scan_dir), "--out", str(out)])

    assert exit_code == 0
    assert out.is_file()
    printed = capsys.readouterr().out
    assert f"5 calls written to {out}" in printed
    assert "unknown type" not in printed
    assert "could not be converted" not in printed


def test_export_calls_missing_report(tmp_path, capsys):
    exit_code = run(["export", "calls", str(tmp_path), "--out", str(tmp_path / "c.xml")])
    assert exit_code == 1
    assert capsys.readouterr().err.startswith("error: report.json not found")


def test_export_calls_unwritable_out(tmp_path, capsys):
    scan_dir = build_call_scan_dir(tmp_path / "scan")
    out = tmp_path / "calls.xml"
    out.mkdir()
    exit_code = run(["export", "calls", str(scan_dir), "--out", str(out)])
    assert exit_code == 1
    assert capsys.readouterr().err.startswith("error: cannot write")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: the six new tests FAIL (argparse exits with status 2: `invalid choice: 'messages'` / `'calls'`); the existing ones PASS.

- [ ] **Step 3: Implement** — in `src/ssba/cli/main.py`:

Imports, next to the contacts import:

```python
from ssba.core.parsers.calls import CallExportError, export_calls
from ssba.core.parsers.messages import MessageExportError, export_messages
```

In `build_arg_parser`, after the `contacts_parser` arguments and before `return parser`:

```python
    messages_parser = export_kinds.add_parser(
        "messages", help="write the recovered text messages as SMS Backup & Restore XML"
    )
    messages_parser.add_argument(
        "scan_dir", type=Path, help="directory written by `ssba scan --out`"
    )
    messages_parser.add_argument(
        "--out", type=Path, required=True, help="path of the .xml file to write"
    )
    calls_parser = export_kinds.add_parser(
        "calls", help="write the recovered call log as SMS Backup & Restore XML"
    )
    calls_parser.add_argument(
        "scan_dir", type=Path, help="directory written by `ssba scan --out`"
    )
    calls_parser.add_argument(
        "--out", type=Path, required=True, help="path of the .xml file to write"
    )
```

After `_run_export_contacts`:

```python
def _run_export_messages(scan_dir: Path, out: Path) -> int:
    try:
        result = export_messages(scan_dir, out)
    except MessageExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{result.exported} messages written to {out}")
    if result.rcs_as_sms:
        print(f"{result.rcs_as_sms} RCS messages converted to SMS")
    if result.system_skipped:
        print(f"{result.system_skipped} system messages skipped")
    if result.unsupported:
        print(
            f"{result.unsupported} messages could not be converted; "
            f"kept in {result.unsupported_path}"
        )
    if result.replaced_chars:
        print(f"{result.replaced_chars} invalid characters replaced")
    return 0


def _run_export_calls(scan_dir: Path, out: Path) -> int:
    try:
        result = export_calls(scan_dir, out)
    except CallExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{result.exported} calls written to {out}")
    if result.unknown_types:
        print(f"{result.unknown_types} calls have an unknown type (kept as is)")
    if result.unsupported:
        print(
            f"{result.unsupported} calls could not be converted; "
            f"kept in {result.unsupported_path}"
        )
    if result.replaced_chars:
        print(f"{result.replaced_chars} invalid characters replaced")
    return 0
```

In `run`, after the contacts branch:

```python
    if args.command == "export" and args.export_kind == "messages":
        return _run_export_messages(args.scan_dir, args.out)

    if args.command == "export" and args.export_kind == "calls":
        return _run_export_calls(args.scan_dir, args.out)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ssba/cli/main.py tests/test_cli.py
git commit -m "feat: add ssba export messages and ssba export calls"
```

---

## After the tasks (controller, not a subagent task)

Manual, local-only validation on the real scan (outputs stay under the git-ignored `out/`, never committed):

```bash
python -c "from ssba.cli.main import main; import sys; sys.argv=['ssba','export','messages','D:/SmartSwitch-Backup-Analyzer/out/real-scan-v4','--out','D:/SmartSwitch-Backup-Analyzer/out/messages/sms.xml']; main()"
python -c "from ssba.cli.main import main; import sys; sys.argv=['ssba','export','calls','D:/SmartSwitch-Backup-Analyzer/out/real-scan-v4','--out','D:/SmartSwitch-Backup-Analyzer/out/calls/calls.xml']; main()"
```

Check: both re-parse; `count` equals the element count; messages exported + system_skipped + unsupported = 2018 and every source part text appears whole in its `body`; calls = 2000 with number/date/duration/type equal to the source.
