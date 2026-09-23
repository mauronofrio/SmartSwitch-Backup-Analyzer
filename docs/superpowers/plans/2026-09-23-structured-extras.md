# Structured Extras Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ssba export wifi | blocked-numbers | browser | clipboard | clock | all`, exporting the remaining structured data of a Smart Switch scan.

**Architecture:** One module per kind in `src/ssba/core/parsers/`, each reading files through `scan_report` and writing through a shared `html_page` helper (escaped, self-contained HTML). The CLI declares every export subparser through one helper and dispatches through a table, which `export all` reuses.

**Tech Stack:** Python 3.10+, stdlib (`sqlite3`, `zipfile`, `csv`, `html`, `xml.etree`), `segno>=1.6` for QR codes, pytest.

**Spec:** `docs/superpowers/specs/2026-09-23-structured-extras-design.md`

## Global Constraints

- Python 3.10+. New runtime dependency: `segno>=1.6` (pure Python, no dependencies), used only to draw QR codes; the QR payload is built by this project.
- `core/` never prints; only `cli/` does.
- No real personal data in the repository, tests or fixtures.
- No attribution lines in commit messages; commits stay local — nothing is pushed. Work directly on `master`.
- Every HTML page: single self-contained UTF-8 file, inline CSS, no scripts, no external resources; all text from the backup escaped.
- Run tests with `python -m pytest` from `D:/SmartSwitch-Backup-Analyzer`; pass paths to Python as `D:/...`, never `/d/...`.
- Create/edit files with editor tools, never through scripts or heredocs. Escape sequences in Python string literals (`\x00`, `\u2615`, `\t`, `\\` …) must stay escape text in the files — verify bytes if a tool might have converted them.

---

### Task 1: Shared helpers (scan_report additions, html_page, test fixture helper)

**Files:**
- Modify: `src/ssba/core/parsers/scan_report.py`
- Create: `src/ssba/core/parsers/html_page.py`
- Create: `tests/scan_fixtures.py`
- Create: `tests/test_html_page.py`
- Modify: `tests/test_scan_report.py`

**Interfaces:**
- Produces:
  - `ssba.core.parsers.scan_report.MissingCategoryError(ScanReportError)`
  - `ssba.core.parsers.scan_report.category_zip(scan_dir: Path, category: str, member: str) -> Path | None`
  - `ssba.core.parsers.html_page.esc(text: str) -> str`
  - `ssba.core.parsers.html_page.page(title: str, body: str) -> str`
  - `ssba.core.parsers.html_page.format_time(seconds: float | None) -> str`
  - `ssba.core.parsers.html_page.safe_link(url: str, text: str) -> str`
  - `ssba.core.parsers.html_page.write_output(path: Path, text: str, error: type[Exception]) -> None`
  - `tests.scan_fixtures.add_category(scan_dir: Path, category: str, files: list[dict]) -> None` (merges into an existing `report.json`)
  - `tests.scan_fixtures.entry(path: str, status: str = "decrypted", kind: str | None = None) -> dict`

- [ ] **Step 1: Write the fixture helper** — `tests/scan_fixtures.py`:

```python
"""Helpers to build fake `ssba scan` output trees - no real data."""

from __future__ import annotations

import json
from pathlib import Path


def entry(path: str, status: str = "decrypted", kind: str | None = None) -> dict:
    return {"path": path, "status": status, "kind": kind, "detail": None}


def add_category(scan_dir: Path, category: str, files: list[dict]) -> None:
    """Add ``category`` to scan_dir/report.json, creating or extending it."""
    scan_dir.mkdir(parents=True, exist_ok=True)
    report_path = scan_dir / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        report = {"categories": []}
    report["categories"].append({"category": category, "counts": {}, "files": files})
    report_path.write_text(json.dumps(report), encoding="utf-8")
```

- [ ] **Step 2: Write the failing tests.** Append to `tests/test_scan_report.py` (add `import zipfile` and extend the import to `from ssba.core.parsers.scan_report import MissingCategoryError, ScanReportError, category_files, category_zip`):

```python
def test_missing_category_error_is_a_scan_report_error(tmp_path):
    _write_report(tmp_path, [], category="CONTACT")
    with pytest.raises(MissingCategoryError, match="the scan report has no WIFICONFIG category"):
        category_files(tmp_path, "WIFICONFIG")
    assert issubclass(MissingCategoryError, ScanReportError)


def test_missing_report_is_not_a_missing_category(tmp_path):
    with pytest.raises(ScanReportError) as info:
        category_files(tmp_path, "CALLLOG")
    assert not isinstance(info.value, MissingCategoryError)


def _zip(path, members):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def test_category_zip_returns_the_first_zip_holding_the_member(tmp_path):
    _touch(tmp_path / "CALLLOG" / "not-a-zip.bin")
    _zip(tmp_path / "CALLLOG" / "other.zip", {"x.txt": b"x"})
    wanted = _zip(tmp_path / "CALLLOG" / "backup.enc", {"databases/SBrowser.db": b"db"})
    _zip(tmp_path / "CALLLOG" / "later.zip", {"databases/SBrowser.db": b"db"})
    _write_report(tmp_path, [
        {"path": "not-a-zip.bin", "status": "decrypted"},
        {"path": "other.zip", "status": "decrypted"},
        {"path": "backup.enc", "status": "decrypted"},
        {"path": "later.zip", "status": "decrypted"},
    ])
    assert category_zip(tmp_path, "CALLLOG", "databases/SBrowser.db") == wanted


def test_category_zip_without_a_match_returns_none(tmp_path):
    _zip(tmp_path / "CALLLOG" / "other.zip", {"x.txt": b"x"})
    _write_report(tmp_path, [{"path": "other.zip", "status": "decrypted"}])
    assert category_zip(tmp_path, "CALLLOG", "databases/SBrowser.db") is None
```

And create `tests/test_html_page.py`:

```python
from __future__ import annotations

from datetime import datetime

import pytest

from ssba.core.parsers.html_page import esc, format_time, page, safe_link, write_output


def test_esc_escapes_markup_and_quotes():
    assert esc("<a href=\"x\">'&") == "&lt;a href=&quot;x&quot;&gt;&#x27;&amp;"


@pytest.mark.parametrize("url", ["https://e.example/?a=1&b=2", "HTTP://E.EXAMPLE/"])
def test_safe_link_links_http_urls(url):
    assert safe_link(url, "<t>") == f'<a href="{esc(url)}">&lt;t&gt;</a>'


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,x", ""])
def test_safe_link_never_links_other_schemes(url):
    assert safe_link(url, "<t>") == "&lt;t&gt;"


@pytest.mark.parametrize("value", [None, 0, -5])
def test_format_time_of_unknown_is_empty(value):
    assert format_time(value) == ""


def test_format_time_uses_local_time():
    expected = datetime.fromtimestamp(1700000000).strftime("%Y-%m-%d %H:%M:%S")
    assert format_time(1700000000) == expected


def test_format_time_out_of_range_is_empty():
    assert format_time(1e20) == ""


def test_page_is_a_self_contained_document_with_escaped_title():
    html = page("<T>", "<p>body</p>")
    assert html.startswith("<!DOCTYPE html>")
    assert '<meta charset="utf-8">' in html
    assert "<title>&lt;T&gt;</title>" in html
    assert "<h1>&lt;T&gt;</h1>" in html
    assert "<p>body</p>" in html
    assert "<script" not in html
    assert "http" not in html


def test_write_output_creates_parents_and_writes_utf8(tmp_path):
    target = tmp_path / "a" / "b.html"
    write_output(target, "caff\u00e8", ValueError)
    assert target.read_bytes() == "caff\u00e8".encode("utf-8")


def test_write_output_failure_raises_the_given_error(tmp_path):
    target = tmp_path / "dir"
    target.mkdir()
    with pytest.raises(KeyError, match="cannot write"):
        write_output(target, "x", KeyError)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_scan_report.py tests/test_html_page.py -v`
Expected: collection errors (`ImportError: cannot import name 'MissingCategoryError'`, `ModuleNotFoundError: ... html_page`).

- [ ] **Step 4: Implement.** In `src/ssba/core/parsers/scan_report.py` add `import zipfile`, and after `ScanReportError`:

```python
class MissingCategoryError(ScanReportError):
    """Raised when report.json has no entry for the requested category."""
```

Change the missing-category raise in `category_files` to:

```python
        raise MissingCategoryError(f"the scan report has no {category} category")
```

Append:

```python
def category_zip(scan_dir: Path, category: str, member: str) -> Path | None:
    """Return the first recovered file of ``category`` that is a ZIP holding ``member``."""
    for path in category_files(scan_dir, category):
        try:
            if not zipfile.is_zipfile(path):
                continue
            with zipfile.ZipFile(path) as archive:
                if member in archive.namelist():
                    return path
        except (OSError, zipfile.BadZipFile):
            continue
    return None
```

Create `src/ssba/core/parsers/html_page.py`:

```python
"""Helpers for the self-contained, read-only pages the exporters write."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

_STYLE = (
    "body{font-family:system-ui,sans-serif;margin:2em;color:#222}"
    "table{border-collapse:collapse}"
    "th,td{border:1px solid #ccc;padding:.3em .6em;text-align:left;vertical-align:top}"
    "pre{white-space:pre-wrap;word-break:break-word;margin:0}"
    ".note{background:#fff4ce;padding:.5em 1em}"
    ".entry{border-bottom:1px solid #ddd;padding:.5em 0}"
    "img{max-width:32em}"
)


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def page(title: str, body: str) -> str:
    """A complete HTML document: no scripts, no external resources."""
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{esc(title)}</title>\n<style>{_STYLE}</style>\n</head>\n<body>\n"
        f"<h1>{esc(title)}</h1>\n{body}\n</body>\n</html>\n"
    )


def format_time(seconds: float | None) -> str:
    """Local time as YYYY-MM-DD HH:MM:SS; empty when unknown or out of range."""
    if seconds is None or seconds <= 0:
        return ""
    try:
        return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def safe_link(url: str, text: str) -> str:
    """Link only web addresses; anything else (javascript:, file:, ...) stays text."""
    if url.lower().startswith(("http://", "https://")):
        return f'<a href="{esc(url)}">{esc(text)}</a>'
    return esc(text)


def write_output(path: Path, text: str, error: type[Exception]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise error(f"cannot write {exc.filename or path}: {exc}") from exc
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ssba/core/parsers/scan_report.py src/ssba/core/parsers/html_page.py tests/scan_fixtures.py tests/test_html_page.py tests/test_scan_report.py
git commit -m "feat: add shared helpers for the structured extras exporters"
```

---

### Task 2: Wi-Fi export

**Files:**
- Modify: `pyproject.toml` (dependencies)
- Create: `src/ssba/core/parsers/wifi.py`
- Create: `tests/wifi_fixtures.py`
- Create: `tests/test_wifi_export.py`

**Interfaces:**
- Consumes: `category_files`, `ScanReportError` (scan_report); `esc`, `page`, `write_output` (html_page); `add_category`, `entry` (tests/scan_fixtures).
- Produces:
  - `ssba.core.parsers.wifi.WifiExportError(Exception)`
  - `ssba.core.parsers.wifi.WifiNetwork` dataclass (`ssid: str`, `security: str`, `password: str | None`, `hidden: bool`)
  - `ssba.core.parsers.wifi.WifiExportResult` dataclass (`networks: int`, `with_password: int`, `skipped: int = 0`)
  - `ssba.core.parsers.wifi.read_networks(scan_dir: Path) -> tuple[list[WifiNetwork], int]`
  - `ssba.core.parsers.wifi.qr_payload(network: WifiNetwork) -> str | None`
  - `ssba.core.parsers.wifi.export_wifi(scan_dir: Path, out_path: Path) -> WifiExportResult`
  - `tests.wifi_fixtures.build_wifi_scan_dir(scan_dir: Path, text: str = DEFAULT, *, supplicant: bool = True) -> Path`

- [ ] **Step 1: Add the dependency.** In `pyproject.toml`, `[project] dependencies`, add `"segno>=1.6",` after `"vobject>=0.9.9",`. Run `python -m pip install "segno>=1.6"` (already installed on this machine is fine).

- [ ] **Step 2: Write the fixtures** — `tests/wifi_fixtures.py`:

```python
"""Fabricated Wi-Fi backup for tests - no real networks or passwords."""

from __future__ import annotations

from pathlib import Path

from tests.scan_fixtures import add_category, entry


def block(**fields: str) -> str:
    lines = "".join(f"\t{key}={value}\n" for key, value in fields.items())
    return "network={\n" + lines + "}\n\n"


NEW_STYLE = (
    "New_Version_Style\n<?xml version='1.0' encoding='utf-8' standalone='yes' ?>"
    "<WifiBackupData><NetworkList><Network><WifiConfiguration>"
    "<string name=\"SSID\">&quot;OnlyInNewStyle&quot;</string>"
    "</WifiConfiguration></Network></NetworkList></WifiBackupData>\n"
)


def store(*blocks: str, new_style: bool = True) -> str:
    return "Old_Version_Style\n" + "".join(blocks) + (NEW_STYLE if new_style else "")


DEFAULT = store(
    block(ssid='"Casa"', psk='"segreta123"', key_mgmt="SAE"),
    block(ssid='"Casa"', psk='"segreta123"', key_mgmt="WPA-PSK"),
    block(ssid='"Bar Aperto"', key_mgmt="NONE"),
    block(ssid='"Bar Aperto"', key_mgmt="OWE"),
    block(ssid='"Nascosta"', scan_ssid="1", psk='"x"', key_mgmt="WPA-PSK"),
)


def build_wifi_scan_dir(scan_dir: Path, text: str = DEFAULT, *, supplicant: bool = True) -> Path:
    folder = scan_dir / "WIFICONFIG" / "WIFICONFIG.zip"
    folder.mkdir(parents=True)
    (folder / "WifiConfigStore.xml").write_text(text, encoding="utf-8")
    files = [entry("WIFICONFIG.zip/WifiConfigStore.xml", kind="text")]
    if supplicant:
        (folder / "wpa_supplicant.conf").write_text(text.split("New_Version_Style")[0], encoding="utf-8")
        files.append(entry("WIFICONFIG.zip/wpa_supplicant.conf", kind="text"))
    (folder / "wifi_wpaconf.xml").write_text("<Wi-Fi><model>X</model></Wi-Fi>", encoding="utf-8")
    files.append(entry("WIFICONFIG.zip/wifi_wpaconf.xml", kind="xml"))
    add_category(scan_dir, "WIFICONFIG", files)
    return scan_dir
```

- [ ] **Step 3: Write the failing tests** — `tests/test_wifi_export.py`:

```python
from __future__ import annotations

import pytest

from ssba.core.parsers.wifi import (
    WifiExportError,
    WifiNetwork,
    export_wifi,
    qr_payload,
    read_networks,
)
from tests.scan_fixtures import add_category
from tests.wifi_fixtures import block, build_wifi_scan_dir, store


def _read(tmp_path, text):
    return read_networks(build_wifi_scan_dir(tmp_path / "scan", text))


def test_duplicate_blocks_become_one_network_each(tmp_path):
    networks, skipped = read_networks(build_wifi_scan_dir(tmp_path / "scan"))
    assert networks == [
        WifiNetwork("Casa", "WPA", "segreta123", False),
        WifiNetwork("Bar Aperto", "open", None, False),
        WifiNetwork("Nascosta", "WPA", "x", True),
    ]
    assert skipped == 0


def test_new_version_style_part_is_ignored(tmp_path):
    networks, _ = read_networks(build_wifi_scan_dir(tmp_path / "scan"))
    assert "OnlyInNewStyle" not in [n.ssid for n in networks]


def test_hex_ssid_is_decoded_and_unquoted_psk_kept(tmp_path):
    raw_key = "0123456789abcdef" * 4
    networks, _ = _read(tmp_path, store(block(ssid="4361666520e29895", psk=raw_key, key_mgmt="WPA-PSK")))
    assert networks == [WifiNetwork("Cafe \u2615", "WPA", raw_key, False)]


def test_unquoted_non_hex_ssid_is_kept_as_written(tmp_path):
    networks, _ = _read(tmp_path, store(block(ssid="plain-name", key_mgmt="NONE")))
    assert networks[0].ssid == "plain-name"


def test_block_without_ssid_is_skipped_and_counted(tmp_path):
    networks, skipped = _read(tmp_path, store(block(key_mgmt="NONE"), block(ssid='"Ok"', key_mgmt="NONE")))
    assert [n.ssid for n in networks] == ["Ok"]
    assert skipped == 2  # counted once per source file (WifiConfigStore.xml and wpa_supplicant.conf)


@pytest.mark.parametrize("fields", [
    dict(ssid='"Ufficio"', key_mgmt="WPA-EAP", eap="PEAP"),
    dict(ssid='"Ufficio"', key_mgmt="NONE", wep_key0='"abcde"'),
])
def test_eap_and_wep_networks_are_other_without_qr(tmp_path, fields):
    networks, _ = _read(tmp_path, store(block(**fields)))
    assert networks[0].security == "other"
    assert qr_payload(networks[0]) is None


def test_block_left_open_at_the_end_is_kept(tmp_path):
    text = 'Old_Version_Style\nnetwork={\n\tssid="Coda"\n\tkey_mgmt=NONE\n'
    networks, _ = _read(tmp_path, text)
    assert [n.ssid for n in networks] == ["Coda"]


def test_qr_payload_for_wpa_escapes_special_characters():
    network = WifiNetwork(ssid='a;b,c:d"e\\f', security="WPA", password="p;q", hidden=True)
    assert qr_payload(network) == r'WIFI:T:WPA;S:a\;b\,c\:d\"e\\f;P:p\;q;H:true;;'


def test_qr_payload_for_open_network():
    assert qr_payload(WifiNetwork("Bar", "open", None, False)) == "WIFI:T:nopass;S:Bar;;"


def test_export_writes_one_qr_code_per_network(tmp_path):
    scan_dir = build_wifi_scan_dir(tmp_path / "scan")
    out = tmp_path / "export" / "wifi.html"

    result = export_wifi(scan_dir, out)

    assert (result.networks, result.with_password, result.skipped) == (3, 2, 0)
    html = out.read_text(encoding="utf-8")
    assert html.count("<svg") == 3
    assert "segreta123" in html
    assert "clear text" in html
    assert "<script" not in html


def test_export_escapes_names_and_passwords(tmp_path):
    text = store(block(ssid='"<script>alert(1)</script>"', psk='"a<b>&c"', key_mgmt="WPA-PSK"))
    scan_dir = build_wifi_scan_dir(tmp_path / "scan", text)
    out = tmp_path / "wifi.html"
    export_wifi(scan_dir, out)
    html = out.read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script" not in html
    assert "a&lt;b&gt;&amp;c" in html


def test_missing_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(WifiExportError, match="WIFICONFIG"):
        export_wifi(tmp_path, tmp_path / "wifi.html")


def test_no_network_blocks_raises(tmp_path):
    scan_dir = build_wifi_scan_dir(tmp_path / "scan", "nothing here", supplicant=False)
    with pytest.raises(WifiExportError, match="no Wi-Fi configuration"):
        export_wifi(scan_dir, tmp_path / "wifi.html")


def test_only_nameless_blocks_raises(tmp_path):
    scan_dir = build_wifi_scan_dir(tmp_path / "scan", store(block(key_mgmt="NONE")))
    with pytest.raises(WifiExportError, match="no Wi-Fi networks"):
        export_wifi(scan_dir, tmp_path / "wifi.html")


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_wifi_scan_dir(tmp_path / "scan")
    out = tmp_path / "wifi.html"
    out.mkdir()
    with pytest.raises(WifiExportError, match="cannot write"):
        export_wifi(scan_dir, out)
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/test_wifi_export.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'ssba.core.parsers.wifi'`.

- [ ] **Step 5: Implement** — `src/ssba/core/parsers/wifi.py`:

```python
"""List the Wi-Fi networks Phase 1 recovered, with a QR code to re-add each one."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import segno

from ssba.core.parsers.html_page import esc, page, write_output
from ssba.core.parsers.scan_report import ScanReportError, category_files

# WifiConfigStore.xml holds wpa_supplicant blocks, then this marker and
# Android's XML backup, whose networks are all also in the blocks.
_NEW_STYLE_MARKER = "New_Version_Style"
_HEX = re.compile(r"(?:[0-9A-Fa-f]{2})+")
# Characters the ZXing WIFI: format requires to be backslash-escaped.
_QR_SPECIAL = re.compile(r'([\\;,:"])')
_SECURITY_LABELS = {"WPA": "WPA/WPA2/WPA3", "open": "Open", "other": "Other (EAP/WEP)"}


class WifiExportError(Exception):
    """Raised when no Wi-Fi networks can be exported from a scan output directory."""


@dataclass
class WifiNetwork:
    ssid: str
    security: str  # "WPA", "open" or "other"
    password: str | None
    hidden: bool


@dataclass
class WifiExportResult:
    networks: int
    with_password: int
    skipped: int = 0


def _unquote(raw: str) -> str | None:
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return None


def _ssid(raw: str) -> str:
    quoted = _unquote(raw)
    if quoted is not None:
        return quoted
    if _HEX.fullmatch(raw):
        return bytes.fromhex(raw).decode("utf-8", errors="replace")
    return raw


def _password(raw: str) -> str:
    # An unquoted psk is a raw 64-hex-digit key, which Android also accepts.
    quoted = _unquote(raw)
    return raw if quoted is None else quoted


def _blocks(text: str) -> list[dict[str, str]]:
    text = text.split(_NEW_STYLE_MARKER, 1)[0]
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "network={":
            current = {}
        elif stripped == "}" and current is not None:
            blocks.append(current)
            current = None
        elif current is not None and "=" in stripped:
            key, value = stripped.split("=", 1)
            current.setdefault(key.strip(), value.strip())
    if current is not None:  # truncated file: keep what was read
        blocks.append(current)
    return blocks


def read_networks(scan_dir: Path) -> tuple[list[WifiNetwork], int]:
    try:
        paths = category_files(scan_dir, "WIFICONFIG")
    except ScanReportError as exc:
        raise WifiExportError(str(exc)) from exc

    grouped: dict[str, list[dict[str, str]]] = {}
    skipped = 0
    found = False
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise WifiExportError(f"cannot read {path}: {exc}") from exc
        if "network={" not in text:
            continue
        found = True
        for block in _blocks(text):
            if "ssid" not in block:
                skipped += 1
                continue
            grouped.setdefault(_ssid(block["ssid"]), []).append(block)
    if not found:
        raise WifiExportError("no Wi-Fi configuration found in the scan output")

    networks = []
    for ssid, blocks in grouped.items():
        password = next(
            (_password(b["psk"]) for b in blocks if b.get("psk") and _password(b["psk"])),
            None,
        )
        other = any("EAP" in b.get("key_mgmt", "").upper() or "wep_key0" in b for b in blocks)
        security = "other" if other else "WPA" if password else "open"
        hidden = any(b.get("scan_ssid") == "1" for b in blocks)
        networks.append(WifiNetwork(ssid, security, password, hidden))
    return networks, skipped


def _qr_escape(text: str) -> str:
    return _QR_SPECIAL.sub(r"\\\1", text)


def qr_payload(network: WifiNetwork) -> str | None:
    """The ZXing WIFI: text Android's camera and Wi-Fi settings understand."""
    if network.security == "other":
        return None
    hidden = "H:true;" if network.hidden else ""
    ssid = _qr_escape(network.ssid)
    if network.security == "WPA":
        return f"WIFI:T:WPA;S:{ssid};P:{_qr_escape(network.password or '')};{hidden};"
    return f"WIFI:T:nopass;S:{ssid};{hidden};"


def export_wifi(scan_dir: Path, out_path: Path) -> WifiExportResult:
    networks, skipped = read_networks(scan_dir)
    if not networks:
        raise WifiExportError("no Wi-Fi networks found in the scan output")

    rows = []
    for network in networks:
        payload = qr_payload(network)
        qr = segno.make(payload, error="m", micro=False).svg_inline(scale=4) if payload else "\u2014"
        cells = (
            esc(network.ssid),
            esc(_SECURITY_LABELS[network.security]),
            esc(network.password) if network.password else "\u2014",
            "yes" if network.hidden else "no",
            qr,
        )
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    body = (
        '<p class="note">This page contains Wi-Fi passwords in clear text. Keep it private.</p>\n'
        "<p>To add a network on Android: Settings &rarr; Wi-Fi &rarr; the QR code icon "
        "next to &ldquo;Add network&rdquo;, then scan its code.</p>\n"
        "<table>\n<tr><th>Network</th><th>Security</th><th>Password</th>"
        "<th>Hidden</th><th>QR code</th></tr>\n" + "\n".join(rows) + "\n</table>"
    )
    write_output(out_path, page("Wi-Fi networks", body), WifiExportError)
    return WifiExportResult(
        networks=len(networks),
        with_password=sum(n.password is not None for n in networks),
        skipped=skipped,
    )
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_wifi_export.py -v`, then `python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/ssba/core/parsers/wifi.py tests/wifi_fixtures.py tests/test_wifi_export.py
git commit -m "feat: export Wi-Fi networks with passwords and QR codes"
```

---

### Task 3: Blocked numbers export

**Files:**
- Create: `src/ssba/core/parsers/blocked.py`
- Create: `tests/test_blocked_export.py` (fixtures inside the test module)

**Interfaces:**
- Consumes: `category_files`, `ScanReportError`; `write_output`; `add_category`, `entry`.
- Produces:
  - `ssba.core.parsers.blocked.BlockedExportError(Exception)`
  - `ssba.core.parsers.blocked.BlockedExportResult` dataclass (`exported: int`, `skipped: int = 0`)
  - `ssba.core.parsers.blocked.export_blocked_numbers(scan_dir: Path, out_path: Path) -> BlockedExportResult`
  - `tests.test_blocked_export.build_blocked_scan_dir(scan_dir: Path, csv_text: str = CSV) -> Path`

- [ ] **Step 1: Write the failing tests** — `tests/test_blocked_export.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from ssba.core.parsers.blocked import BlockedExportError, export_blocked_numbers
from tests.scan_fixtures import add_category, entry

NAME = "com.samsung.android.app.telephonyui.callsettings.api.entity.BlockNumberItem.csv"
PHOTO_RING = "com.samsung.android.app.telephonyui.callsettings.api.entity.PhotoRingBlockNumberItem.csv"
CSV = (
    "_id\treject_number\treject_match\n"
    "4\t+393330000004\t0\n"
    "3\tSpamCo\t0\n"
    "2\t\t0\n"
    "1\t+39333\t1\n"
    "0\t+393330000000\t0\n"
)


def build_blocked_scan_dir(scan_dir: Path, csv_text: str = CSV) -> Path:
    folder = scan_dir / "CALLOGSETTING" / "CALLOGSETTING.zip"
    folder.mkdir(parents=True)
    (folder / NAME).write_text(csv_text, encoding="utf-8")
    (folder / PHOTO_RING).write_text("_id\treject_number\n0\t+390000000999\n", encoding="utf-8")
    add_category(scan_dir, "CALLOGSETTING", [
        entry(f"CALLOGSETTING.zip/{NAME}", kind="text"),
        entry(f"CALLOGSETTING.zip/{PHOTO_RING}", kind="text"),
    ])
    return scan_dir


def _export(tmp_path, csv_text=CSV):
    out = tmp_path / "export" / "blocked-numbers.txt"
    return export_blocked_numbers(build_blocked_scan_dir(tmp_path / "scan", csv_text), out), out


def test_numbers_are_written_in_id_order(tmp_path):
    result, out = _export(tmp_path)
    assert out.read_text(encoding="utf-8") == (
        "+393330000000\n+39333\t(match type 1)\nSpamCo\n+393330000004\n"
    )
    assert (result.exported, result.skipped) == (4, 1)


def test_photo_ring_list_is_not_exported(tmp_path):
    _, out = _export(tmp_path)
    assert "+390000000999" not in out.read_text(encoding="utf-8")


def test_non_integer_ids_come_last_in_file_order(tmp_path):
    csv_text = "_id\treject_number\treject_match\nx\tB\t0\n5\tA\t0\ny\tC\t0\n"
    _, out = _export(tmp_path, csv_text)
    assert out.read_text(encoding="utf-8") == "A\nB\nC\n"


def test_missing_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(BlockedExportError, match="CALLOGSETTING"):
        export_blocked_numbers(tmp_path, tmp_path / "b.txt")


def test_no_list_raises(tmp_path):
    add_category(tmp_path, "CALLOGSETTING", [])
    with pytest.raises(BlockedExportError, match="no blocked-number list"):
        export_blocked_numbers(tmp_path, tmp_path / "b.txt")


def test_list_without_numbers_raises(tmp_path):
    with pytest.raises(BlockedExportError, match="no blocked numbers"):
        _export(tmp_path, "_id\treject_number\treject_match\n0\t\t0\n")


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_blocked_scan_dir(tmp_path / "scan")
    out = tmp_path / "b.txt"
    out.mkdir()
    with pytest.raises(BlockedExportError, match="cannot write"):
        export_blocked_numbers(scan_dir, out)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_blocked_export.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'ssba.core.parsers.blocked'`.

- [ ] **Step 3: Implement** — `src/ssba/core/parsers/blocked.py`:

```python
"""List the numbers the phone blocked, one per line, to re-enter by hand."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from ssba.core.parsers.html_page import write_output
from ssba.core.parsers.scan_report import ScanReportError, category_files

# The call settings backup names each table's CSV after its entity class;
# "...PhotoRingBlockNumberItem.csv" is another list and does not match.
_SOURCE_SUFFIX = ".blocknumberitem.csv"


class BlockedExportError(Exception):
    """Raised when no blocked numbers can be exported from a scan output directory."""


@dataclass
class BlockedExportResult:
    exported: int
    skipped: int = 0


def _find_source(scan_dir: Path) -> Path:
    try:
        paths = category_files(scan_dir, "CALLOGSETTING")
    except ScanReportError as exc:
        raise BlockedExportError(str(exc)) from exc
    for path in paths:
        if path.name.lower().endswith(_SOURCE_SUFFIX):
            return path
    raise BlockedExportError("no blocked-number list found in the scan output")


def _row_order(item: tuple[int, dict]) -> tuple[int, int, int]:
    index, row = item
    try:
        return (0, int(row.get("_id") or ""), index)
    except ValueError:
        return (1, 0, index)


def export_blocked_numbers(scan_dir: Path, out_path: Path) -> BlockedExportResult:
    path = _find_source(scan_dir)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise BlockedExportError(f"cannot read {path}: {exc}") from exc

    rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
    lines: list[str] = []
    skipped = 0
    for _, row in sorted(enumerate(rows), key=_row_order):
        number = (row.get("reject_number") or "").strip()
        if not number:
            skipped += 1
            continue
        match = (row.get("reject_match") or "0").strip()
        lines.append(number if match == "0" else f"{number}\t(match type {match})")

    if not lines:
        raise BlockedExportError("no blocked numbers found in the list")
    write_output(out_path, "\n".join(lines) + "\n", BlockedExportError)
    return BlockedExportResult(exported=len(lines), skipped=skipped)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_blocked_export.py -v`, then `python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ssba/core/parsers/blocked.py tests/test_blocked_export.py
git commit -m "feat: export the blocked-number list"
```

---

### Task 4: Samsung Internet export

**Files:**
- Create: `src/ssba/core/parsers/browser.py`
- Create: `tests/browser_fixtures.py`
- Create: `tests/test_browser_export.py`

**Interfaces:**
- Consumes: `category_zip`, `ScanReportError`; `esc`, `format_time`, `page`, `safe_link`, `write_output`; `add_category`, `entry`.
- Produces:
  - `ssba.core.parsers.browser.BrowserExportError(Exception)`
  - `ssba.core.parsers.browser.BrowserExportResult` dataclass (`bookmarks`, `folders`, `quick_access`, `history`, `downloads`, `skipped`, all `int = 0`)
  - `ssba.core.parsers.browser.export_browser(scan_dir: Path, out_dir: Path) -> BrowserExportResult` (writes `out_dir/bookmarks.html` and `out_dir/history.html`)
  - `tests.browser_fixtures.build_browser_scan_dir(scan_dir: Path, *, bookmarks=BOOKMARKS, quick=QUICK, history=True) -> Path`

- [ ] **Step 1: Write the fixtures** — `tests/browser_fixtures.py`:

```python
"""Fabricated Samsung Internet backup for tests - no real browsing data."""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from pathlib import Path

from tests.scan_fixtures import add_category, entry


def chromium(seconds: float) -> int:
    """Unix seconds -> Chromium time (microseconds since 1601-01-01)."""
    return int((seconds + 11644473600) * 1_000_000)


# (_ID, URL, TITLE, FOLDER, PARENT, POSITION, DELETED)
BOOKMARKS = [
    (-3, None, "Bookmarks", 1, -2, -10, 0),
    (0, None, "Samsung", 1, -3, -10001, 0),
    (73, "https://example.com/a", "Esempio A", 0, 0, -100, 0),
    (74, 'https://example.com/b?x=1&y="2"', "B <tag>", 0, 0, -101, 0),
    (75, "https://example.com/deleted", "Deleted", 0, 0, -99, 1),
    (76, "https://example.com/top", "", 0, 999, 5, 0),
    (77, "", "No url", 0, 0, -98, 0),
]
# (id, title, url, position, deleted)
QUICK = [
    (1, "Meteo", "https://meteo.example", 1, 0),
    (2, "Notizie", "https://news.example", 0, 0),
    (3, "Vecchio", "https://old.example", 2, 1),
    (4, "Vuoto", "", 3, 0),
]
# (id, url, title, visit_count, last_visit_time)
URLS = [
    (1, "https://example.com/a", "A", 3, chromium(1700000000)),
    (2, "javascript:alert(1)", "JS", 1, chromium(1700000100)),
    (3, "http://example.org/<x>", "<b>T</b>", 2, chromium(1690000000)),
]
# (id, target_path, start_time, total_bytes, state)
DOWNLOADS = [
    (1, "/storage/emulated/0/Download/a.pdf", chromium(1700000200), 1234, 1),
    (2, "/storage/emulated/0/Download/b.zip", chromium(1600000000), 99, 1),
]
# (id, chain_index, url)
CHAINS = [
    (1, 0, "https://example.com/redirect"),
    (1, 1, "https://cdn.example.com/a.pdf"),
    (2, 0, "https://example.com/b.zip"),
]


def _db(path: Path, script: str, inserts: list[tuple[str, list[tuple]]]) -> bytes:
    con = sqlite3.connect(path)
    con.executescript(script)
    for sql, rows in inserts:
        con.executemany(sql, rows)
    con.commit()
    con.close()
    return path.read_bytes()


def build_browser_scan_dir(scan_dir: Path, *, bookmarks=BOOKMARKS, quick=QUICK, history=True) -> Path:
    members: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        members["databases/SBrowser.db"] = _db(
            tmp / "b.db",
            "CREATE TABLE BOOKMARKS (_ID INTEGER, URL TEXT, TITLE TEXT, FOLDER INTEGER,"
            " PARENT INTEGER, POSITION INTEGER, DELETED INTEGER);",
            [("INSERT INTO BOOKMARKS VALUES (?,?,?,?,?,?,?)", bookmarks)],
        )
        if quick is not None:
            members["databases/quickaccess.db"] = _db(
                tmp / "q.db",
                "CREATE TABLE quickaccess_item (id INTEGER PRIMARY KEY, title TEXT, url TEXT,"
                " position INTEGER, deleted INTEGER);",
                [("INSERT INTO quickaccess_item VALUES (?,?,?,?,?)", quick)],
            )
        if history:
            members["app_sbrowser/Default/History"] = _db(
                tmp / "h.db",
                "CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT,"
                " visit_count INTEGER, last_visit_time INTEGER);"
                "CREATE TABLE downloads (id INTEGER PRIMARY KEY, target_path TEXT,"
                " start_time INTEGER, total_bytes INTEGER, state INTEGER);"
                "CREATE TABLE downloads_url_chains (id INTEGER, chain_index INTEGER, url TEXT);",
                [
                    ("INSERT INTO urls VALUES (?,?,?,?,?)", URLS),
                    ("INSERT INTO downloads VALUES (?,?,?,?,?)", DOWNLOADS),
                    ("INSERT INTO downloads_url_chains VALUES (?,?,?)", CHAINS),
                ],
            )
    archive = scan_dir / "SBROWSER" / "SBROWSER.zip" / "backup.enc"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    add_category(scan_dir, "SBROWSER", [entry("SBROWSER.zip/backup.enc", kind="zip")])
    return scan_dir
```

- [ ] **Step 2: Write the failing tests** — `tests/test_browser_export.py`:

```python
from __future__ import annotations

import zipfile
from html.parser import HTMLParser

import pytest

from ssba.core.parsers.browser import BrowserExportError, export_browser
from ssba.core.parsers.html_page import format_time
from tests.browser_fixtures import build_browser_scan_dir
from tests.scan_fixtures import add_category, entry


class _Tree(HTMLParser):
    """Rebuild the folder/link tree of a Netscape bookmark file."""

    def __init__(self):
        super().__init__()
        self.root: list = []
        self.stack = [self.root]
        self.pending = None
        self.tag = None
        self.href = None
        self.text = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("h3", "a"):
            self.tag, self.href, self.text = tag, dict(attrs).get("href"), ""
        elif tag == "dl" and self.pending is not None:
            self.stack.append(self.pending)
            self.pending = None

    def handle_endtag(self, tag):
        if tag == "h3":
            items: list = []
            self.stack[-1].append(("folder", self.text, items))
            self.pending, self.tag = items, None
        elif tag == "a":
            self.stack[-1].append(("link", self.text, self.href))
            self.tag = None
        elif tag == "dl" and len(self.stack) > 1:
            self.stack.pop()

    def handle_data(self, data):
        if self.tag:
            self.text += data


def _tree(html: str) -> list:
    parser = _Tree()
    parser.feed(html)
    return parser.root


def _export(tmp_path, **kwargs):
    out = tmp_path / "export" / "browser"
    return export_browser(build_browser_scan_dir(tmp_path / "scan", **kwargs), out), out


def test_bookmarks_keep_folders_order_and_quick_access(tmp_path):
    result, out = _export(tmp_path)
    html = (out / "bookmarks.html").read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE NETSCAPE-Bookmark-file-1>")
    assert _tree(html) == [
        ("folder", "Bookmarks", [
            ("folder", "Samsung", [
                ("link", "B <tag>", 'https://example.com/b?x=1&y="2"'),
                ("link", "Esempio A", "https://example.com/a"),
            ]),
        ]),
        ("link", "https://example.com/top", "https://example.com/top"),
        ("folder", "Quick access", [
            ("link", "Notizie", "https://news.example"),
            ("link", "Meteo", "https://meteo.example"),
        ]),
    ]
    assert (result.bookmarks, result.folders, result.quick_access, result.skipped) == (3, 2, 2, 2)


def test_bookmark_titles_and_urls_are_escaped(tmp_path):
    _, out = _export(tmp_path)
    html = (out / "bookmarks.html").read_text(encoding="utf-8")
    assert "B &lt;tag&gt;" in html
    assert "y=&quot;2&quot;" in html


def test_folders_caught_in_a_parent_cycle_are_still_exported(tmp_path):
    bookmarks = [
        (1, None, "A", 1, 2, 0, 0),
        (2, None, "B", 1, 1, 1, 0),
        (3, "https://x.example", "X", 0, 1, 0, 0),
    ]
    result, out = _export(tmp_path, bookmarks=bookmarks, quick=None)
    html = (out / "bookmarks.html").read_text(encoding="utf-8")
    assert (result.folders, result.bookmarks) == (2, 1)
    assert "https://x.example" in html


def test_history_lists_visits_newest_first_and_links_only_web_urls(tmp_path):
    result, out = _export(tmp_path)
    html = (out / "history.html").read_text(encoding="utf-8")
    assert (result.history, result.downloads) == (3, 2)
    assert html.index(format_time(1700000100)) < html.index(format_time(1700000000)) < html.index(format_time(1690000000))
    assert '<a href="https://example.com/a">' in html
    assert "javascript:alert(1)" in html
    assert 'href="javascript' not in html
    assert "&lt;b&gt;T&lt;/b&gt;" in html
    assert "<b>T</b>" not in html
    assert "<script" not in html


def test_downloads_show_the_final_url_newest_first(tmp_path):
    _, out = _export(tmp_path)
    html = (out / "history.html").read_text(encoding="utf-8")
    assert "https://cdn.example.com/a.pdf" in html
    assert "https://example.com/redirect" not in html
    assert html.index("a.pdf") < html.index("b.zip")


def test_missing_quick_access_and_history_are_tolerated(tmp_path):
    result, out = _export(tmp_path, quick=None, history=False)
    assert (result.quick_access, result.history, result.downloads) == (0, 0, 0)
    assert "Quick access" not in (out / "bookmarks.html").read_text(encoding="utf-8")
    assert (out / "history.html").is_file()


def test_missing_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(BrowserExportError, match="SBROWSER"):
        export_browser(tmp_path, tmp_path / "out")


def test_no_browser_archive_raises(tmp_path):
    other = tmp_path / "SBROWSER" / "note.txt"
    other.parent.mkdir(parents=True)
    other.write_text("x", encoding="utf-8")
    add_category(tmp_path, "SBROWSER", [entry("note.txt")])
    with pytest.raises(BrowserExportError, match="no Samsung Internet backup"):
        export_browser(tmp_path, tmp_path / "out")


def test_corrupt_database_raises(tmp_path):
    archive = tmp_path / "SBROWSER" / "backup.enc"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("databases/SBrowser.db", b"this is not sqlite")
    add_category(tmp_path, "SBROWSER", [entry("backup.enc")])
    with pytest.raises(BrowserExportError, match="cannot read"):
        export_browser(tmp_path, tmp_path / "out")


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_browser_scan_dir(tmp_path / "scan")
    out = tmp_path / "out"
    out.write_text("a file, not a directory", encoding="utf-8")
    with pytest.raises(BrowserExportError, match="cannot write"):
        export_browser(scan_dir, out)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_browser_export.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'ssba.core.parsers.browser'`.

- [ ] **Step 4: Implement** — `src/ssba/core/parsers/browser.py`:

```python
"""Export Samsung Internet bookmarks (importable) and history (read-only)."""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ssba.core.parsers.html_page import esc, format_time, page, safe_link, write_output
from ssba.core.parsers.scan_report import ScanReportError, category_zip

_BOOKMARKS_DB = "databases/SBrowser.db"
_QUICK_ACCESS_DB = "databases/quickaccess.db"
_HISTORY_DB = "app_sbrowser/Default/History"
# Chromium stores times as microseconds since 1601-01-01 UTC.
_CHROMIUM_EPOCH_OFFSET = 11644473600
_TOP = object()  # key of the top-level entries in the bookmark tree
_NETSCAPE_HEAD = (
    "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n"
    '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n'
    "<TITLE>Bookmarks</TITLE>\n<H1>Bookmarks</H1>\n<DL><p>\n"
)


class BrowserExportError(Exception):
    """Raised when the Samsung Internet data cannot be exported."""


@dataclass
class BrowserExportResult:
    bookmarks: int = 0
    folders: int = 0
    quick_access: int = 0
    history: int = 0
    downloads: int = 0
    skipped: int = 0


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _chromium_seconds(value) -> float | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return value / 1_000_000 - _CHROMIUM_EPOCH_OFFSET


def _extract(archive: Path, member: str, tmp: Path) -> Path | None:
    with zipfile.ZipFile(archive) as zf:
        if member not in zf.namelist():
            return None
        target = tmp / member.replace("/", "_")
        target.write_bytes(zf.read(member))
        return target


def _with_db(path: Path, read):
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        con.text_factory = lambda raw: raw.decode("utf-8", errors="replace")
        return read(con)
    finally:
        con.close()


def _position(row) -> tuple:
    position = row["POSITION"]
    return (position if isinstance(position, (int, float)) else 0, row["_ID"])


def _render(children: dict, parent, depth: int, visited: set, result: BrowserExportResult) -> list[str]:
    pad = "    " * depth
    lines: list[str] = []
    for row in children.get(parent, []):
        if row["_ID"] in visited:
            continue
        visited.add(row["_ID"])
        if row["FOLDER"] == 1:
            result.folders += 1
            lines.append(f"{pad}<DT><H3>{esc(_text(row['TITLE']) or 'Untitled folder')}</H3>")
            lines.append(f"{pad}<DL><p>")
            lines += _render(children, row["_ID"], depth + 1, visited, result)
            lines.append(f"{pad}</DL><p>")
            continue
        url = _text(row["URL"])
        if not url:
            result.skipped += 1
            continue
        result.bookmarks += 1
        lines.append(f'{pad}<DT><A HREF="{esc(url)}">{esc(_text(row["TITLE"]) or url)}</A>')
    return lines


def _bookmark_lines(con: sqlite3.Connection, result: BrowserExportResult) -> list[str]:
    rows = [
        row
        for row in con.execute(
            "SELECT _ID, URL, TITLE, FOLDER, PARENT, POSITION, DELETED FROM BOOKMARKS"
        )
        if not row["DELETED"]
    ]
    folder_ids = {row["_ID"] for row in rows if row["FOLDER"] == 1}
    children: dict = {}
    for row in rows:
        parent = row["PARENT"]
        key = parent if parent in folder_ids and parent != row["_ID"] else _TOP
        children.setdefault(key, []).append(row)
    for siblings in children.values():
        siblings.sort(key=_position)

    visited: set = set()
    lines = _render(children, _TOP, 1, visited, result)
    for row in sorted(rows, key=_position):
        if row["_ID"] not in visited:  # a folder caught in a PARENT cycle
            lines += _render({**children, _TOP: [row]}, _TOP, 1, visited, result)
    return lines


def _quick_access_lines(con: sqlite3.Connection, result: BrowserExportResult) -> list[str]:
    lines = []
    for row in con.execute(
        "SELECT title, url, deleted FROM quickaccess_item ORDER BY position, id"
    ):
        if row["deleted"]:
            continue
        url = _text(row["url"])
        if not url:
            result.skipped += 1
            continue
        result.quick_access += 1
        lines.append(f'        <DT><A HREF="{esc(url)}">{esc(_text(row["title"]) or url)}</A>')
    if not lines:
        return []
    return ["    <DT><H3>Quick access</H3>", "    <DL><p>", *lines, "    </DL><p>"]


def _read_history(con: sqlite3.Connection) -> tuple[list, list]:
    urls = con.execute(
        "SELECT url, title, visit_count, last_visit_time FROM urls"
        " ORDER BY last_visit_time DESC, id DESC"
    ).fetchall()
    downloads = con.execute(
        "SELECT d.target_path, d.start_time, d.total_bytes,"
        " (SELECT c.url FROM downloads_url_chains c WHERE c.id = d.id"
        "  ORDER BY c.chain_index DESC LIMIT 1) AS url"
        " FROM downloads d ORDER BY d.start_time DESC, d.id DESC"
    ).fetchall()
    return urls, downloads


def _history_body(urls: list, downloads: list) -> str:
    visit_rows = "".join(
        "<tr>"
        f"<td>{esc(format_time(_chromium_seconds(row['last_visit_time'])))}</td>"
        f"<td>{esc(_text(row['title']))}</td>"
        f"<td>{safe_link(_text(row['url']), _text(row['url']))}</td>"
        f"<td>{esc(_text(row['visit_count']))}</td>"
        "</tr>\n"
        for row in urls
    )
    download_rows = "".join(
        "<tr>"
        f"<td>{esc(format_time(_chromium_seconds(row['start_time'])))}</td>"
        f"<td>{esc(_text(row['target_path']))}</td>"
        f"<td>{safe_link(_text(row['url']), _text(row['url']))}</td>"
        f"<td>{esc(_text(row['total_bytes']))}</td>"
        "</tr>\n"
        for row in downloads
    )
    return (
        f"<h2>Visited sites ({len(urls)})</h2>\n<table>\n"
        "<tr><th>Last visit</th><th>Title</th><th>Address</th><th>Visits</th></tr>\n"
        f"{visit_rows}</table>\n"
        f"<h2>Downloads ({len(downloads)})</h2>\n<table>\n"
        "<tr><th>Started</th><th>File</th><th>Source</th><th>Size (bytes)</th></tr>\n"
        f"{download_rows}</table>"
    )


def export_browser(scan_dir: Path, out_dir: Path) -> BrowserExportResult:
    try:
        archive = category_zip(scan_dir, "SBROWSER", _BOOKMARKS_DB)
    except ScanReportError as exc:
        raise BrowserExportError(str(exc)) from exc
    if archive is None:
        raise BrowserExportError("no Samsung Internet backup found in the scan output")

    result = BrowserExportResult()
    try:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            bookmarks_db = _extract(archive, _BOOKMARKS_DB, tmp)
            tree = _with_db(bookmarks_db, lambda con: _bookmark_lines(con, result))
            quick_db = _extract(archive, _QUICK_ACCESS_DB, tmp)
            quick = _with_db(quick_db, lambda con: _quick_access_lines(con, result)) if quick_db else []
            history_db = _extract(archive, _HISTORY_DB, tmp)
            urls, downloads = _with_db(history_db, _read_history) if history_db else ([], [])
    except (OSError, zipfile.BadZipFile, sqlite3.Error) as exc:
        raise BrowserExportError(f"cannot read {archive}: {exc}") from exc

    result.history = len(urls)
    result.downloads = len(downloads)
    write_output(
        out_dir / "bookmarks.html",
        _NETSCAPE_HEAD + "\n".join(tree + quick) + "\n</DL><p>\n",
        BrowserExportError,
    )
    write_output(
        out_dir / "history.html",
        page("Samsung Internet history", _history_body(urls, downloads)),
        BrowserExportError,
    )
    return result
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_browser_export.py -v`, then `python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ssba/core/parsers/browser.py tests/browser_fixtures.py tests/test_browser_export.py
git commit -m "feat: export Samsung Internet bookmarks and history"
```

---

### Task 5: Clipboard export

**Files:**
- Create: `src/ssba/core/parsers/clipboard.py`
- Create: `tests/clipboard_fixtures.py`
- Create: `tests/test_clipboard_export.py`

**Interfaces:**
- Consumes: `category_zip`, `ScanReportError`; `esc`, `format_time`, `page`, `write_output`; `add_category`, `entry`.
- Produces:
  - `ssba.core.parsers.clipboard.ClipboardExportError(Exception)`
  - `ssba.core.parsers.clipboard.ClipboardExportResult` dataclass (`texts`, `images`, `missing_images`, `other_types`, all `int = 0`)
  - `ssba.core.parsers.clipboard.export_clipboard(scan_dir: Path, out_dir: Path) -> ClipboardExportResult` (writes `out_dir/index.html` and `out_dir/images/*`)
  - `tests.clipboard_fixtures.build_clipboard_scan_dir(scan_dir: Path, *, rows=ROWS, images=IMAGES) -> Path`

- [ ] **Step 1: Write the fixtures** — `tests/clipboard_fixtures.py`:

```python
"""Fabricated Samsung Keyboard clipboard backup for tests - no real data."""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from pathlib import Path

from tests.scan_fixtures import add_category, entry

JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png"
UNKNOWN = b"\x00\x01not-an-image"

# (id, time_stamp ms, type, text, html)
ROWS = [
    (1, 1700000001000, 1, "Ciao <script>alert(1)</script>", None),
    (2, 1700000002000, 4, "testo html", "<b>testo html</b>"),
    (3, 1700000003000, 4, "", "<i>solo html</i>"),
    (4, 1700000004000, 2, None, None),
    (5, 1700000005000, 2, None, None),
    (6, 1700000006000, 9, "strano", None),
]
# clipboard/<folder>/clip -> bytes
IMAGES = {
    "1700000004000": JPEG,
    "1690000000000": JPEG,
    "1690000000500": JPEG,  # same second and type as the one above: name collision
    "1695000000000": PNG,
    "1680000000000": UNKNOWN,
}


def build_clipboard_scan_dir(scan_dir: Path, *, rows=ROWS, images=IMAGES) -> Path:
    with tempfile.TemporaryDirectory() as tmp_name:
        db = Path(tmp_name) / "c.db"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE clip_table (id INTEGER PRIMARY KEY, time_stamp INTEGER,"
            " type INTEGER, text TEXT, html TEXT)"
        )
        con.executemany("INSERT INTO clip_table VALUES (?,?,?,?,?)", rows)
        con.commit()
        con.close()
        db_bytes = db.read_bytes()
    archive = scan_dir / "CLIPBOARD" / "CLIPBOARD.zip" / "clipboard_backup_keyboard.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("BackupClipItem.db", db_bytes)
        for folder, data in images.items():
            zf.writestr(f"clipboard/{folder}/clip", data)
    add_category(scan_dir, "CLIPBOARD", [
        entry("CLIPBOARD.zip/clipboard_backup_keyboard.zip", status="plaintext_passthrough", kind="zip"),
    ])
    return scan_dir
```

- [ ] **Step 2: Write the failing tests** — `tests/test_clipboard_export.py`:

```python
from __future__ import annotations

import zipfile
from datetime import datetime

import pytest

from ssba.core.parsers.clipboard import ClipboardExportError, export_clipboard
from ssba.core.parsers.html_page import format_time
from tests.clipboard_fixtures import JPEG, PNG, UNKNOWN, build_clipboard_scan_dir
from tests.scan_fixtures import add_category, entry


def _stamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d_%H-%M-%S")


def _export(tmp_path, **kwargs):
    out = tmp_path / "export" / "clipboard"
    return export_clipboard(build_clipboard_scan_dir(tmp_path / "scan", **kwargs), out), out


def test_counts(tmp_path):
    result, _ = _export(tmp_path)
    assert (result.texts, result.images, result.missing_images, result.other_types) == (3, 5, 1, 1)


def test_images_are_written_with_dated_names_and_exact_bytes(tmp_path):
    _, out = _export(tmp_path)
    images = out / "images"
    assert (images / f"{_stamp(1700000004000)}.jpg").read_bytes() == JPEG
    assert (images / f"{_stamp(1690000000000)}.jpg").read_bytes() == JPEG
    assert (images / f"{_stamp(1690000000500)}_2.jpg").read_bytes() == JPEG
    assert (images / f"{_stamp(1695000000000)}.png").read_bytes() == PNG
    assert (images / f"{_stamp(1680000000000)}.bin").read_bytes() == UNKNOWN
    assert len(list(images.iterdir())) == 5


def test_page_lists_entries_in_time_order_with_relative_images(tmp_path):
    _, out = _export(tmp_path)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert f'src="images/{_stamp(1700000004000)}.jpg"' in html
    assert f'href="images/{_stamp(1680000000000)}.bin"' in html
    positions = [html.index(format_time(ms / 1000)) for ms in (1680000000000, 1690000000000, 1700000001000, 1700000006000)]
    assert positions == sorted(positions)


def test_texts_are_escaped_and_html_only_rows_show_their_source(tmp_path):
    _, out = _export(tmp_path)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Ciao &lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script" not in html
    assert "&lt;i&gt;solo html&lt;/i&gt;" in html
    assert "HTML source" in html
    assert "Image missing from the backup" in html
    assert "Type 9" in html


def test_image_folder_that_is_not_a_timestamp_is_undated(tmp_path):
    result, out = _export(tmp_path, rows=[(1, 1700000001000, 1, "x", None)], images={"abc": JPEG})
    assert result.images == 1
    assert (out / "images" / "clip-1.jpg").read_bytes() == JPEG


def test_missing_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(ClipboardExportError, match="CLIPBOARD"):
        export_clipboard(tmp_path, tmp_path / "out")


def test_no_clipboard_archive_raises(tmp_path):
    add_category(tmp_path, "CLIPBOARD", [])
    with pytest.raises(ClipboardExportError, match="no clipboard backup"):
        export_clipboard(tmp_path, tmp_path / "out")


def test_corrupt_database_raises(tmp_path):
    archive = tmp_path / "CLIPBOARD" / "clipboard_backup_keyboard.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("BackupClipItem.db", b"not sqlite")
    add_category(tmp_path, "CLIPBOARD", [entry("clipboard_backup_keyboard.zip")])
    with pytest.raises(ClipboardExportError, match="cannot read"):
        export_clipboard(tmp_path, tmp_path / "out")


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_clipboard_scan_dir(tmp_path / "scan")
    out = tmp_path / "out"
    out.write_text("a file, not a directory", encoding="utf-8")
    with pytest.raises(ClipboardExportError, match="cannot write"):
        export_clipboard(scan_dir, out)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_clipboard_export.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'ssba.core.parsers.clipboard'`.

- [ ] **Step 4: Implement** — `src/ssba/core/parsers/clipboard.py`:

```python
"""Export the Samsung Keyboard clipboard - texts and images - as a read-only page."""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from ssba.core.parsers.html_page import esc, format_time, page, write_output
from ssba.core.parsers.scan_report import ScanReportError, category_zip

_DB = "BackupClipItem.db"
_TEXT_TYPES = {1: "Text", 4: "HTML"}
_IMAGE_TYPE = 2
_MAGIC = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"GIF8", "gif"))


class ClipboardExportError(Exception):
    """Raised when the clipboard cannot be exported."""


@dataclass
class ClipboardExportResult:
    texts: int = 0
    images: int = 0
    missing_images: int = 0
    other_types: int = 0


@dataclass
class _Entry:
    ms: int | None
    order: int
    html: str


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _ms(value) -> int | None:
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return ms if ms > 0 else None


def _extension(data: bytes) -> str:
    for magic, extension in _MAGIC:
        if data.startswith(magic):
            return extension
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "bin"


def _file_stamp(ms: int | None) -> str:
    if ms is None:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d_%H-%M-%S")
    except (OverflowError, OSError, ValueError):
        return ""


def _unique_name(ms: int | None, extension: str, used: set[str]) -> str:
    base = _file_stamp(ms) or f"clip-{len(used) + 1}"
    name, n = f"{base}.{extension}", 2
    while name in used:
        name, n = f"{base}_{n}.{extension}", n + 1
    used.add(name)
    return name


def _read_rows(db_bytes: bytes) -> list[sqlite3.Row]:
    with tempfile.TemporaryDirectory() as tmp_name:
        path = Path(tmp_name) / "clip.db"
        path.write_bytes(db_bytes)
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            con.row_factory = sqlite3.Row
            con.text_factory = lambda raw: raw.decode("utf-8", errors="replace")
            return con.execute(
                "SELECT time_stamp, type, text, html FROM clip_table ORDER BY time_stamp, id"
            ).fetchall()
        finally:
            con.close()


def _write_image(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        raise ClipboardExportError(f"cannot write {exc.filename or path}: {exc}") from exc


def export_clipboard(scan_dir: Path, out_dir: Path) -> ClipboardExportResult:
    try:
        archive = category_zip(scan_dir, "CLIPBOARD", _DB)
    except ScanReportError as exc:
        raise ClipboardExportError(str(exc)) from exc
    if archive is None:
        raise ClipboardExportError("no clipboard backup found in the scan output")

    result = ClipboardExportResult()
    entries: list[_Entry] = []
    used: set[str] = set()
    try:
        with zipfile.ZipFile(archive) as zf:
            rows = _read_rows(zf.read(_DB))
            images: dict[str, str] = {}
            for name in zf.namelist():
                parts = PurePosixPath(name).parts
                if len(parts) >= 3 and parts[0] == "clipboard" and not name.endswith("/"):
                    images.setdefault(parts[1], name)

            for order, row in enumerate(rows):
                ms = _ms(row["time_stamp"])
                kind = row["type"]
                if kind == _IMAGE_TYPE:
                    # The image itself is listed from its folder below.
                    if _text(row["time_stamp"]) not in images:
                        result.missing_images += 1
                        entries.append(_Entry(ms, order, '<p class="note">Image missing from the backup</p>'))
                    continue
                text = _text(row["text"])
                if kind in _TEXT_TYPES:
                    result.texts += 1
                    label = _TEXT_TYPES[kind] if text else "HTML source"
                else:
                    result.other_types += 1
                    label = f"Type {kind}"
                body = text or _text(row["html"])
                entries.append(_Entry(ms, order, f"<p><b>{esc(label)}</b></p><pre>{esc(body)}</pre>"))

            for offset, (folder, member) in enumerate(sorted(images.items())):
                data = zf.read(member)
                ms = _ms(folder)
                extension = _extension(data)
                filename = _unique_name(ms, extension, used)
                _write_image(out_dir / "images" / filename, data)
                result.images += 1
                src = esc(f"images/{filename}")
                html = (
                    f'<a href="{src}">{esc(filename)}</a>'
                    if extension == "bin"
                    else f'<img src="{src}" alt="clipboard image">'
                )
                entries.append(_Entry(ms, len(rows) + offset, html))
    except (OSError, zipfile.BadZipFile, sqlite3.Error) as exc:
        raise ClipboardExportError(f"cannot read {archive}: {exc}") from exc

    entries.sort(key=lambda e: (e.ms is None, e.ms or 0, e.order))
    body = "\n".join(
        f'<div class="entry"><p>{esc(format_time(e.ms / 1000) if e.ms else "") or "Unknown date"}</p>{e.html}</div>'
        for e in entries
    )
    write_output(out_dir / "index.html", page("Clipboard", body), ClipboardExportError)
    return result
```

Note: `_write_image` raises `ClipboardExportError` (not an `OSError`), so it passes through the read-error handler unchanged.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_clipboard_export.py -v`, then `python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ssba/core/parsers/clipboard.py tests/clipboard_fixtures.py tests/test_clipboard_export.py
git commit -m "feat: export the keyboard clipboard texts and images"
```

---

### Task 6: Clock export

**Files:**
- Create: `src/ssba/core/parsers/clock.py`
- Create: `tests/clock_fixtures.py`
- Create: `tests/test_clock_export.py`

**Interfaces:**
- Consumes: `category_files`, `MissingCategoryError`, `ScanReportError`; `esc`, `page`, `write_output`; `add_category`, `entry`.
- Produces:
  - `ssba.core.parsers.clock.ClockExportError(Exception)`
  - `ssba.core.parsers.clock.ClockExportResult` dataclass (`alarms`, `timers`, `cities`, all `int = 0`)
  - `ssba.core.parsers.clock.export_clock(scan_dir: Path, out_path: Path) -> ClockExportResult`
  - `tests.clock_fixtures.build_clock_scan_dir(scan_dir: Path, *, alarm: str | None = ALARM_XML, timer: str | None = TIMER_XML, world: str | None = WORLD_XML) -> Path`

- [ ] **Step 1: Write the fixtures** — `tests/clock_fixtures.py`:

```python
"""Fabricated Samsung Clock backup for tests - no real data."""

from __future__ import annotations

from pathlib import Path

from tests.scan_fixtures import add_category, entry

ALARM_XML = (
    "<Alarms><BackupVersion>8</BackupVersion>"
    "<alarm><active>1</active><alarmtime>530</alarmtime><name>Sveglia &lt;presto&gt;</name>"
    "<repeattype>65537</repeattype></alarm>"
    "<alarm><active>0</active><alarmtime>2359</alarmtime><name></name><repeattype>0</repeattype></alarm>"
    "<alarm><active>0</active><alarmtime>abc</alarmtime><name/><repeattype/></alarm>"
    "</Alarms>"
)
TIMER_XML = (
    "<Timer><BackupVersion>8</BackupVersion><timerlife>"
    "<item><id>1</id><timername></timername><time>00:30:00</time></item>"
    "<item><id>2</id><timername>Pasta</timername><time>00:10:00</time></item>"
    "</timerlife></Timer>"
)
WORLD_XML = (
    "<Worldclocks><worldclock>"
    "<item><city>Roma</city><gmt>GMT+1:00</gmt></item>"
    "<item><city>Tokyo</city><gmt>GMT+9:00</gmt></item>"
    "</worldclock></Worldclocks>"
)


def build_clock_scan_dir(scan_dir: Path, *, alarm: str | None = ALARM_XML,
                         timer: str | None = TIMER_XML, world: str | None = WORLD_XML) -> Path:
    if alarm is not None:
        folder = scan_dir / "ALARM" / "ALARM.zip"
        folder.mkdir(parents=True)
        (folder / "alarm.exml").write_text(alarm, encoding="utf-8")
        add_category(scan_dir, "ALARM", [entry("ALARM.zip/alarm.exml", kind="xml")])
    files = []
    folder = scan_dir / "WORLDCLOCK" / "WORLDCLOCK.zip"
    for name, text in (("timer.exml", timer), ("worldclock.exml", world)):
        if text is not None:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / name).write_text(text, encoding="utf-8")
            files.append(entry(f"WORLDCLOCK.zip/{name}", kind="xml"))
    if files:
        add_category(scan_dir, "WORLDCLOCK", files)
    return scan_dir
```

- [ ] **Step 2: Write the failing tests** — `tests/test_clock_export.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_clock_export.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'ssba.core.parsers.clock'`.

- [ ] **Step 4: Implement** — `src/ssba/core/parsers/clock.py`:

```python
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
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_clock_export.py -v`, then `python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ssba/core/parsers/clock.py tests/clock_fixtures.py tests/test_clock_export.py
git commit -m "feat: export alarms, timers and world clock cities"
```

---

### Task 7: CLI subcommands and `export all`

**Files:**
- Modify: `src/ssba/cli/main.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `export_wifi`/`WifiExportError` (Task 2), `export_blocked_numbers`/`BlockedExportError` (Task 3), `export_browser`/`BrowserExportError` (Task 4), `export_clipboard`/`ClipboardExportError` (Task 5), `export_clock`/`ClockExportError` (Task 6); fixture builders `build_wifi_scan_dir` (tests/wifi_fixtures.py), `build_blocked_scan_dir` (tests/test_blocked_export.py), `build_browser_scan_dir` (tests/browser_fixtures.py), `build_clipboard_scan_dir` (tests/clipboard_fixtures.py), `build_clock_scan_dir` (tests/clock_fixtures.py), `build_call_scan_dir` (tests/call_fixtures.py).
- Produces: `ssba export wifi|blocked-numbers|browser|clipboard|clock|all <scan_dir> --out <path>`.

- [ ] **Step 1: Write the failing tests** — add these imports at the top of `tests/test_cli.py`:

```python
from tests.browser_fixtures import build_browser_scan_dir
from tests.clipboard_fixtures import build_clipboard_scan_dir
from tests.clock_fixtures import build_clock_scan_dir
from tests.test_blocked_export import build_blocked_scan_dir
from tests.wifi_fixtures import build_wifi_scan_dir
```

and append:

```python
def test_export_wifi_success_warns_about_passwords(tmp_path, capsys):
    scan_dir = build_wifi_scan_dir(tmp_path / "scan")
    out = tmp_path / "wifi.html"
    assert run(["export", "wifi", str(scan_dir), "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert f"3 Wi-Fi networks written to {out} (2 with a password)" in captured.out
    assert f"warning: {out} contains Wi-Fi passwords in clear text" in captured.err


def test_export_blocked_numbers_success(tmp_path, capsys):
    scan_dir = build_blocked_scan_dir(tmp_path / "scan")
    out = tmp_path / "blocked.txt"
    assert run(["export", "blocked-numbers", str(scan_dir), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert f"4 blocked numbers written to {out}" in printed
    assert "1 rows without a number skipped" in printed


def test_export_browser_success(tmp_path, capsys):
    scan_dir = build_browser_scan_dir(tmp_path / "scan")
    out = tmp_path / "browser"
    assert run(["export", "browser", str(scan_dir), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert f"3 bookmarks in 2 folders and 2 quick access items written to {out / 'bookmarks.html'}" in printed
    assert f"3 visited sites and 2 downloads written to {out / 'history.html'}" in printed
    assert "2 entries without an address skipped" in printed


def test_export_clipboard_success(tmp_path, capsys):
    scan_dir = build_clipboard_scan_dir(tmp_path / "scan")
    out = tmp_path / "clipboard"
    assert run(["export", "clipboard", str(scan_dir), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert f"3 texts and 5 images written to {out / 'index.html'}" in printed
    assert "1 clipboard images were missing from the backup" in printed
    assert "1 entries of an unknown type included as text" in printed


def test_export_clock_success(tmp_path, capsys):
    scan_dir = build_clock_scan_dir(tmp_path / "scan")
    out = tmp_path / "clock.html"
    assert run(["export", "clock", str(scan_dir), "--out", str(out)]) == 0
    assert f"3 alarms, 2 timers and 2 world clock cities written to {out}" in capsys.readouterr().out


def test_new_exports_report_errors_on_stderr(tmp_path, capsys):
    for kind in ("wifi", "blocked-numbers", "browser", "clipboard", "clock"):
        assert run(["export", kind, str(tmp_path), "--out", str(tmp_path / "x")]) == 1
        assert capsys.readouterr().err.startswith("error: ")


def test_export_all_runs_every_kind_and_continues_past_failures(tmp_path, capsys):
    scan_dir = build_call_scan_dir(tmp_path / "scan")
    build_wifi_scan_dir(scan_dir)
    out = tmp_path / "all"

    assert run(["export", "all", str(scan_dir), "--out", str(out)]) == 0

    captured = capsys.readouterr()
    for kind in ("contacts", "messages", "calls", "wifi", "blocked-numbers", "browser", "clipboard", "clock"):
        assert f"== {kind} ==" in captured.out
    assert "error: the scan report has no CONTACT category" in captured.err
    assert (out / "calls.xml").is_file()
    assert (out / "wifi.html").is_file()
    assert f"2 of 8 exports written to {out}" in captured.out


def test_export_all_without_report_runs_nothing(tmp_path, capsys):
    assert run(["export", "all", str(tmp_path), "--out", str(tmp_path / "all")]) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: report.json not found")
    assert "==" not in captured.out


def test_export_all_with_nothing_exportable_fails(tmp_path, capsys):
    (tmp_path / "report.json").write_text('{"categories": []}', encoding="utf-8")
    assert run(["export", "all", str(tmp_path), "--out", str(tmp_path / "all")]) == 1
    assert "0 of 8 exports written" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: the new tests FAIL (argparse exits 2 with `invalid choice: 'wifi'` etc.); existing tests PASS.

- [ ] **Step 3: Implement** — in `src/ssba/cli/main.py`:

Imports (keep alphabetical with the existing parser imports):

```python
from ssba.core.parsers.blocked import BlockedExportError, export_blocked_numbers
from ssba.core.parsers.browser import BrowserExportError, export_browser
from ssba.core.parsers.clipboard import ClipboardExportError, export_clipboard
from ssba.core.parsers.clock import ClockExportError, export_clock
from ssba.core.parsers.wifi import WifiExportError, export_wifi
```

In `build_arg_parser`, replace everything from `contacts_parser = export_kinds.add_parser(` up to (not including) `return parser` with:

```python
    exports = (
        ("contacts", "merge the recovered contacts into one vCard 3.0 file", "the .vcf file to write"),
        ("messages", "write the recovered text messages as SMS Backup & Restore XML", "the .xml file to write"),
        ("calls", "write the recovered call log as SMS Backup & Restore XML", "the .xml file to write"),
        ("wifi", "list the saved Wi-Fi networks with passwords and QR codes", "the .html file to write"),
        ("blocked-numbers", "list the blocked phone numbers", "the .txt file to write"),
        ("browser", "export Samsung Internet bookmarks and history", "the directory to write"),
        ("clipboard", "export the keyboard clipboard texts and images", "the directory to write"),
        ("clock", "list alarms, timers and world clock cities", "the .html file to write"),
        ("all", "run every export above into one directory", "the directory to write"),
    )
    for name, help_text, out_help in exports:
        kind_parser = export_kinds.add_parser(name, help=help_text)
        kind_parser.add_argument(
            "scan_dir", type=Path, help="directory written by `ssba scan --out`"
        )
        kind_parser.add_argument("--out", type=Path, required=True, help=out_help)
```

After `_run_export_calls`, add:

```python
def _run_export_wifi(scan_dir: Path, out: Path) -> int:
    try:
        result = export_wifi(scan_dir, out)
    except WifiExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"{result.networks} Wi-Fi networks written to {out} "
        f"({result.with_password} with a password)"
    )
    if result.skipped:
        print(f"{result.skipped} network entries without a name skipped")
    print(f"warning: {out} contains Wi-Fi passwords in clear text", file=sys.stderr)
    return 0


def _run_export_blocked_numbers(scan_dir: Path, out: Path) -> int:
    try:
        result = export_blocked_numbers(scan_dir, out)
    except BlockedExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{result.exported} blocked numbers written to {out}")
    if result.skipped:
        print(f"{result.skipped} rows without a number skipped")
    return 0


def _run_export_browser(scan_dir: Path, out: Path) -> int:
    try:
        result = export_browser(scan_dir, out)
    except BrowserExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"{result.bookmarks} bookmarks in {result.folders} folders and "
        f"{result.quick_access} quick access items written to {out / 'bookmarks.html'}"
    )
    print(
        f"{result.history} visited sites and {result.downloads} downloads "
        f"written to {out / 'history.html'}"
    )
    if result.skipped:
        print(f"{result.skipped} entries without an address skipped")
    return 0


def _run_export_clipboard(scan_dir: Path, out: Path) -> int:
    try:
        result = export_clipboard(scan_dir, out)
    except ClipboardExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{result.texts} texts and {result.images} images written to {out / 'index.html'}")
    if result.missing_images:
        print(f"{result.missing_images} clipboard images were missing from the backup")
    if result.other_types:
        print(f"{result.other_types} entries of an unknown type included as text")
    return 0


def _run_export_clock(scan_dir: Path, out: Path) -> int:
    try:
        result = export_clock(scan_dir, out)
    except ClockExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"{result.alarms} alarms, {result.timers} timers and "
        f"{result.cities} world clock cities written to {out}"
    )
    return 0


# Every kind `export all` runs, in order, with the name it writes inside --out.
_ALL_EXPORTS = (
    ("contacts", _run_export_contacts, "contacts.vcf"),
    ("messages", _run_export_messages, "sms.xml"),
    ("calls", _run_export_calls, "calls.xml"),
    ("wifi", _run_export_wifi, "wifi.html"),
    ("blocked-numbers", _run_export_blocked_numbers, "blocked-numbers.txt"),
    ("browser", _run_export_browser, "browser"),
    ("clipboard", _run_export_clipboard, "clipboard"),
    ("clock", _run_export_clock, "clock.html"),
)


def _run_export_all(scan_dir: Path, out: Path) -> int:
    if not (scan_dir / "report.json").is_file():
        print(f"error: report.json not found in {scan_dir}", file=sys.stderr)
        return 1
    written = 0
    for name, runner, target in _ALL_EXPORTS:
        print(f"== {name} ==")
        if runner(scan_dir, out / target) == 0:
            written += 1
    print(f"\n{written} of {len(_ALL_EXPORTS)} exports written to {out}")
    return 0 if written else 1


_EXPORT_RUNNERS = {name: runner for name, runner, _ in _ALL_EXPORTS}
_EXPORT_RUNNERS["all"] = _run_export_all
```

In `run`, replace the three `if args.command == "export" and args.export_kind == ...` blocks with:

```python
    if args.command == "export":
        return _EXPORT_RUNNERS[args.export_kind](args.scan_dir, args.out)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ssba/cli/main.py tests/test_cli.py
git commit -m "feat: add CLI exports for Wi-Fi, blocked numbers, browser, clipboard, clock and all"
```

---

## After the tasks (controller, not a subagent task)

Manual, local-only validation on the real scan (`out/real-scan-v4`, outputs under the git-ignored `out/`, never committed):

```bash
python -c "from ssba.cli.main import main; import sys; sys.argv=['ssba','export','all','D:/SmartSwitch-Backup-Analyzer/out/real-scan-v4','--out','D:/SmartSwitch-Backup-Analyzer/out/all']; main()"
```

Check: 8 of 8; 40 networks (26 with password, 3 hidden) and each QR payload re-derived from the source blocks; 5 blocked numbers; 3 bookmarks in 2 folders + 10 quick access; 696 visited sites, 440 downloads; 56 clip rows accounted for and 687 images byte-identical to the ZIP members; 1 alarm, 3 timers, 2 cities.
