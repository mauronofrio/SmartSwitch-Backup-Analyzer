# Core Decrypt Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the generic, category-agnostic decryption engine for Samsung Smart Switch "basic" (no password) PC backups, plus a thin CLI (`ssba scan`) that uses it, per the approved Phase 1 design.

**Architecture:** A pure `core/` library (crypto primitives → session key recovery → generic file decrypt+sniff → recursive backup scanner) with zero I/O side effects beyond what's explicitly passed in, wrapped by a thin `cli/` layer that owns all stdout/stderr and file-writing decisions. Every module is TDD'd against synthetic, fabricated fixtures — never real backup data.

**Tech Stack:** Python 3.10+, `pycryptodome` for AES, stdlib `argparse`/`zipfile`/`xml.etree`, `pytest` for tests.

**Spec:** `docs/superpowers/specs/2026-09-22-core-decrypt-engine-design.md`

## Global Constraints

- Python 3.10+ only.
- Runtime dependency: `pycryptodome>=3.20`. Dev-only dependency: `pytest>=8.0`. No other third-party dependencies in Phase 1.
- `src/ssba/core/**` must never `print()`, log, or otherwise write to stdout/stderr, and must never decide *where* to write output files on its own — it returns bytes/dataclasses; only `src/ssba/cli/**` writes files and prints.
- No real backup data, personal data, or the project owner's actual session dummy/key values anywhere in the repository, including tests and fixtures — every test fixture is fabricated in the test code itself.
- License: AGPL-3.0, exact official text in `LICENSE`, plus a commercial-license note in `README.md`.
- `.gitignore` must exclude `backups/`, `out/`, `output/` at the repo root.
- No attribution lines in commit messages (project owner's standing instruction).
- All commits are local only in this plan — nothing is pushed to GitHub as part of executing this plan.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/ssba/__init__.py`
- Create: `src/ssba/core/__init__.py`
- Create: `src/ssba/cli/__init__.py`
- Create: `.gitignore`
- Create: `LICENSE`
- Create: `README.md`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: an installable `ssba` package (empty modules) that later tasks add real code to; `pip install -e ".[dev]"` works from repo root.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "smartswitch-backup-analyzer"
version = "0.1.0"
description = "Recover data from Samsung Smart Switch PC backups"
readme = "README.md"
license = "AGPL-3.0-or-later"
requires-python = ">=3.10"
dependencies = [
    "pycryptodome>=3.20",
]

[project.scripts]
ssba = "ssba.cli.main:main"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/ssba"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Create the package skeleton**

`src/ssba/__init__.py`:
```python
"""Smart Switch Backup Analyzer."""
```

`src/ssba/core/__init__.py`:
```python
"""Core decryption/scanning engine.

Nothing in this package performs I/O side effects beyond what the caller
explicitly passes in (paths to read, bytes to return) — no printing, no
deciding where output goes. That's the CLI's job.
"""
```

`src/ssba/cli/__init__.py`:
```python
"""Command-line interface."""
```

- [ ] **Step 3: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
*.egg-info/
dist/
build/
.pytest_cache/
backups/
out/
output/
```

- [ ] **Step 4: Download the official AGPL-3.0 license text**

Run:
```bash
curl -o LICENSE https://www.gnu.org/licenses/agpl-3.0.txt
```

Expected: `LICENSE` now contains the full official AGPL-3.0 text (starts with `GNU AFFERO GENERAL PUBLIC LICENSE`).

- [ ] **Step 5: Create `README.md`**

```markdown
# SmartSwitch Backup Analyzer

Recover data from a Samsung Smart Switch PC backup — even from a phone you
can no longer use (broken screen, dead device, etc.) — as long as you still
have the backup folder Smart Switch created on your PC.

## What this does (today)

Smart Switch "basic" (no backup password) backups encrypt most of their
content with a per-backup key that isn't published, but *is* fully
recoverable from data already inside the backup. This tool:

1. Recovers that per-backup key from `backupHistoryInfo.xml`.
2. Walks every category folder in the backup (Notes, Contacts, Call log,
   ...) and decrypts every encrypted file it finds, whatever the category —
   without needing to understand what the data means.
3. Writes everything it could decrypt (or that was already plaintext) to an
   output folder you choose, plus a `report.json` summarizing what was
   recovered per category.

Turning that raw decrypted data into something readable per category (e.g.
notes as browsable HTML, contacts as a `.vcf` you can import) is a separate,
ongoing effort — see "Status" below.

## Status

- Generic decryption engine (this repo, Phase 1): done
- Per-category readable exports (Notes, Contacts, Call log planned next): not started
- Graphical interface (planned once the above are in place): not started

## Install

Requires Python 3.10+.

```bash
pip install -e .
```

## Usage

```bash
ssba scan "C:\Users\<you>\Samsung\SmartSwitch\backup\<device>\<backup_folder>" --out ./recovered
```

This writes decrypted category data under `./recovered/<CATEGORY>/...` and a
`./recovered/report.json` summary.

**This tool only supports "basic" (no backup password) Smart Switch
backups.** Password/PIN-protected backups are not supported yet.

## Your data, your responsibility

The whole point of this tool is to recover *your own personal data*. Never
commit a real backup, or anything this tool recovers from one, to a public
Git repository. `.gitignore` in this repo already excludes the conventional
`backups/`, `out/`, and `output/` folders — keep your own data outside the
repo entirely if you can.

## License

AGPL-3.0 (see `LICENSE`). If you want to use this project commercially
without the obligations of the AGPL, open a GitHub issue or contact the
maintainer to discuss a commercial license.
```

- [ ] **Step 6: Verify the scaffolding is wired correctly**

Run:
```bash
pip install -e ".[dev]"
python -c "import ssba, ssba.core, ssba.cli; print('ok')"
```
Expected: install succeeds, prints `ok`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/ssba .gitignore LICENSE README.md
git commit -m "Scaffold project: package skeleton, license, readme"
```

---

### Task 2: Crypto primitives

**Files:**
- Create: `src/ssba/core/errors.py`
- Create: `src/ssba/core/crypto.py`
- Create: `tests/crypto_helpers.py`
- Test: `tests/test_crypto.py`

**Interfaces:**
- Consumes: nothing new (uses `pycryptodome`'s `Crypto.Cipher.AES`, from Task 1's dependency).
- Produces:
  - `ssba.core.errors.UnsupportedBackupError` — exception type used by later tasks.
  - `ssba.core.crypto.FIXED_DUMMY_ECB_KEY: bytes`
  - `ssba.core.crypto.derive_key(session_dummy: str) -> bytes`
  - `ssba.core.crypto.decrypt_iv_prefixed(raw: bytes, key: bytes) -> bytes` (raises `ValueError`)
  - `ssba.core.crypto.decrypt_dummy_ecb(ciphertext_hex: str) -> str` (raises `ValueError`)
  - `tests.crypto_helpers.encrypt_iv_prefixed(plaintext: bytes, key: bytes, iv: bytes | None = None) -> bytes` (test-only, inverse of `decrypt_iv_prefixed`)
  - `tests.crypto_helpers.encrypt_dummy_ecb(session_dummy: str) -> str` (test-only, inverse of `decrypt_dummy_ecb`)

- [ ] **Step 1: Write `src/ssba/core/errors.py`**

```python
class UnsupportedBackupError(Exception):
    """Raised when a backup (or a required file within it) doesn't match
    the supported no-password Smart Switch format."""
```

- [ ] **Step 2: Write the test-only fixture helpers, `tests/crypto_helpers.py`**

```python
"""Test-only helpers to build synthetic Smart Switch-shaped ciphertext.

Nothing here uses real backup data - everything is fabricated so the test
suite can run without a real Smart Switch backup.
"""

from __future__ import annotations

import os

from Crypto.Cipher import AES

from ssba.core.crypto import FIXED_DUMMY_ECB_KEY


def encrypt_iv_prefixed(plaintext: bytes, key: bytes, iv: bytes | None = None) -> bytes:
    """Inverse of ssba.core.crypto.decrypt_iv_prefixed, for building fixtures."""
    iv = iv or os.urandom(16)
    pad_len = (-len(plaintext)) % 16
    padded = plaintext + b"\x00" * pad_len
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return iv + cipher.encrypt(padded)


def encrypt_dummy_ecb(session_dummy: str) -> str:
    """Inverse of ssba.core.crypto.decrypt_dummy_ecb, for building fixtures."""
    plaintext = session_dummy.encode("ascii")
    pad_len = (-len(plaintext)) % 16
    padded = plaintext + b"\x00" * pad_len
    cipher = AES.new(FIXED_DUMMY_ECB_KEY, AES.MODE_ECB)
    return cipher.encrypt(padded).hex()
```

Note: this file imports `ssba.core.crypto.FIXED_DUMMY_ECB_KEY`, which doesn't exist yet — that's expected, Step 4 creates it. The failing test in Step 3 will fail on this import, which is the correct "red" state.

- [ ] **Step 3: Write the failing tests, `tests/test_crypto.py`**

```python
from __future__ import annotations

import hashlib

import pytest

from ssba.core.crypto import decrypt_dummy_ecb, decrypt_iv_prefixed, derive_key
from tests.crypto_helpers import encrypt_dummy_ecb, encrypt_iv_prefixed

FAKE_DUMMY = "AABBCCDDEEFF00112233445566778899AABB"


def test_derive_key_matches_formula():
    key = derive_key(FAKE_DUMMY)
    expected = hashlib.sha256(FAKE_DUMMY.encode("utf-8")).digest()[:16]
    assert key == expected
    assert len(key) == 16


def test_decrypt_iv_prefixed_round_trip():
    key = derive_key(FAKE_DUMMY)
    plaintext = b"hello smart switch, this is a fake payload!!!!"
    raw = encrypt_iv_prefixed(plaintext, key)
    decrypted = decrypt_iv_prefixed(raw, key)
    assert decrypted.startswith(plaintext)


def test_decrypt_iv_prefixed_rejects_too_short_payload():
    with pytest.raises(ValueError):
        decrypt_iv_prefixed(b"short", b"0" * 16)


def test_decrypt_dummy_ecb_round_trip():
    ciphertext_hex = encrypt_dummy_ecb(FAKE_DUMMY)
    assert decrypt_dummy_ecb(ciphertext_hex) == FAKE_DUMMY


def test_decrypt_dummy_ecb_rejects_bad_hex():
    with pytest.raises(ValueError):
        decrypt_dummy_ecb("not-hex-at-all")


def test_decrypt_dummy_ecb_rejects_wrong_block_size():
    with pytest.raises(ValueError):
        decrypt_dummy_ecb("aabbcc")
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `pytest tests/test_crypto.py -v`
Expected: collection error / failures — `ssba.core.crypto` has no attribute `derive_key` (module doesn't exist yet).

- [ ] **Step 5: Write `src/ssba/core/crypto.py`**

```python
"""AES primitives for Samsung Smart Switch's backup encryption scheme."""

from __future__ import annotations

import hashlib

from Crypto.Cipher import AES

FIXED_DUMMY_ECB_KEY: bytes = b"0b1e96db05d64ea4"


def derive_key(session_dummy: str) -> bytes:
    """Derive the AES-128 key used for a backup's encrypted payloads.

    The key is the first 16 bytes of SHA-256 of the session dummy string
    (itself recovered via decrypt_dummy_ecb).
    """
    return hashlib.sha256(session_dummy.encode("utf-8")).digest()[:16]


def decrypt_iv_prefixed(raw: bytes, key: bytes) -> bytes:
    """Decrypt a Smart Switch payload: first 16 bytes are the IV, the rest
    is AES-128-CBC ciphertext (truncated to a whole number of blocks).
    """
    if len(raw) < 32:
        raise ValueError("payload too small to contain an IV and ciphertext")
    iv = raw[:16]
    ciphertext = raw[16:]
    aligned_len = len(ciphertext) - (len(ciphertext) % 16)
    ciphertext = ciphertext[:aligned_len]
    if not ciphertext:
        raise ValueError("no AES-block-aligned ciphertext after the IV")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.decrypt(ciphertext)


def decrypt_dummy_ecb(ciphertext_hex: str) -> str:
    """Decrypt the <Dummy> element of backupHistoryInfo.xml.

    It is AES-128-ECB ciphertext (fixed key, hex-encoded), zero-padded.
    Returns the plaintext session dummy as a hex string.
    """
    try:
        ciphertext = bytes.fromhex(ciphertext_hex)
    except ValueError as exc:
        raise ValueError("Dummy value is not valid hexadecimal") from exc
    if not ciphertext or len(ciphertext) % 16 != 0:
        raise ValueError(
            "Dummy ciphertext is not a non-empty multiple of the AES block size"
        )
    cipher = AES.new(FIXED_DUMMY_ECB_KEY, AES.MODE_ECB)
    plaintext = cipher.decrypt(ciphertext).rstrip(b"\x00")
    try:
        text = plaintext.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("decrypted Dummy is not ASCII") from exc
    if not (32 <= len(text) <= 128) or len(text) % 2 != 0:
        raise ValueError(f"decrypted Dummy has an unexpected length ({len(text)})")
    if any(c not in "0123456789abcdefABCDEF" for c in text):
        raise ValueError("decrypted Dummy is not hexadecimal")
    return text
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_crypto.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/ssba/core/errors.py src/ssba/core/crypto.py tests/crypto_helpers.py tests/test_crypto.py
git commit -m "Add core crypto primitives (session-dummy decrypt, IV-prefixed AES)"
```

---

### Task 3: Content sniffing and generic file decryption

**Files:**
- Create: `src/ssba/core/container.py`
- Test: `tests/test_container.py`

**Interfaces:**
- Consumes: `ssba.core.crypto.decrypt_iv_prefixed(raw: bytes, key: bytes) -> bytes` (Task 2).
- Produces:
  - `ssba.core.container.Kind` — `Literal["zip", "sqlite", "xml", "json", "text", "media", "binary"]`
  - `ssba.core.container.DecodedBlob` — frozen dataclass with `data: bytes`, `kind: Kind`
  - `ssba.core.container.sniff_kind(data: bytes) -> Kind`
  - `ssba.core.container.decrypt_file(raw: bytes, key: bytes) -> DecodedBlob` (raises `ValueError` when `decrypt_iv_prefixed` does)

- [ ] **Step 1: Write the failing tests, `tests/test_container.py`**

```python
from __future__ import annotations

from ssba.core.container import decrypt_file, sniff_kind
from ssba.core.crypto import derive_key
from tests.crypto_helpers import encrypt_iv_prefixed

KEY = derive_key("AABBCCDDEEFF00112233445566778899AABB")


def test_sniff_kind_zip():
    assert sniff_kind(b"PK\x03\x04rest of a fake zip") == "zip"


def test_sniff_kind_sqlite():
    assert sniff_kind(b"SQLite format 3\x00rest") == "sqlite"


def test_sniff_kind_xml():
    assert sniff_kind(b"<?xml version='1.0'?><root/>") == "xml"


def test_sniff_kind_json_object():
    assert sniff_kind(b'{"a": 1}') == "json"


def test_sniff_kind_json_array():
    assert sniff_kind(b"[1, 2, 3]") == "json"


def test_sniff_kind_media_jpeg():
    assert sniff_kind(b"\xff\xd8\xff\xe0rest of jpeg") == "media"


def test_sniff_kind_media_png():
    assert sniff_kind(b"\x89PNG\r\n\x1a\nrest") == "media"


def test_sniff_kind_text():
    assert sniff_kind(b"just some plain ascii text content here") == "text"


def test_sniff_kind_binary_fallback():
    assert sniff_kind(bytes(range(256))) == "binary"


def test_sniff_kind_empty():
    assert sniff_kind(b"") == "binary"


def test_decrypt_file_recovers_xml():
    plaintext = b"<?xml version='1.0'?><CallLogs></CallLogs>"
    raw = encrypt_iv_prefixed(plaintext, KEY)
    blob = decrypt_file(raw, KEY)
    assert blob.kind == "xml"
    assert blob.data.startswith(plaintext)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_container.py -v`
Expected: `ModuleNotFoundError: No module named 'ssba.core.container'`.

- [ ] **Step 3: Write `src/ssba/core/container.py`**

```python
"""Decrypt a single Smart Switch payload and identify what it decoded to."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ssba.core.crypto import decrypt_iv_prefixed

Kind = Literal["zip", "sqlite", "xml", "json", "text", "media", "binary"]

ZIP_MAGIC = b"PK\x03\x04"
SQLITE_MAGIC = b"SQLite format 3\x00"
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
GIF_MAGICS = (b"GIF87a", b"GIF89a")
PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True)
class DecodedBlob:
    data: bytes
    kind: Kind


def sniff_kind(data: bytes) -> Kind:
    if data.startswith(ZIP_MAGIC):
        return "zip"
    if data.startswith(SQLITE_MAGIC):
        return "sqlite"
    if (
        data.startswith(JPEG_MAGIC)
        or data.startswith(PNG_MAGIC)
        or data.startswith(GIF_MAGICS)
        or data.startswith(PDF_MAGIC)
    ):
        return "media"

    stripped = data.lstrip()
    if stripped[:5] == b"<?xml" or (stripped[:1] == b"<" and b">" in stripped[:256]):
        return "xml"
    if stripped[:1] in (b"{", b"["):
        return "json"

    head = data[:256]
    if head:
        printable = sum(1 for b in head if 32 <= b < 127 or b in (9, 10, 13))
        if printable / len(head) >= 0.95:
            return "text"

    return "binary"


def decrypt_file(raw: bytes, key: bytes) -> DecodedBlob:
    """Decrypt raw (IV-prefixed AES-128-CBC) and identify the result.

    Raises ValueError (from decrypt_iv_prefixed) if raw is too small to be
    a valid IV+ciphertext payload.
    """
    plaintext = decrypt_iv_prefixed(raw, key)
    return DecodedBlob(data=plaintext, kind=sniff_kind(plaintext))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_container.py -v`
Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ssba/core/container.py tests/test_container.py
git commit -m "Add content sniffing and generic file decryption"
```

---

### Task 4: Session key recovery from `backupHistoryInfo.xml`

**Files:**
- Create: `src/ssba/core/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `ssba.core.crypto.decrypt_dummy_ecb(ciphertext_hex: str) -> str` (Task 2), `ssba.core.errors.UnsupportedBackupError` (Task 2).
- Produces: `ssba.core.session.get_session_dummy(backup_root: pathlib.Path) -> str` (raises `UnsupportedBackupError`).

- [ ] **Step 1: Write the failing tests, `tests/test_session.py`**

```python
from __future__ import annotations

import pytest

from ssba.core.errors import UnsupportedBackupError
from ssba.core.session import get_session_dummy
from tests.crypto_helpers import encrypt_dummy_ecb

FAKE_DUMMY = "AABBCCDDEEFF00112233445566778899AABB"


def _write_history_xml(backup_root, dummy_ciphertext_hex, tag_count=1):
    backup_root.mkdir(parents=True, exist_ok=True)
    dummy_tags = ""
    if dummy_ciphertext_hex is not None:
        dummy_tags = f"<Dummy>{dummy_ciphertext_hex}</Dummy>" * tag_count
    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<BatchInfomationItem xmlns="Kies.Common.Data">
    <BundleInfo>
        {dummy_tags}
    </BundleInfo>
</BatchInfomationItem>"""
    (backup_root / "backupHistoryInfo.xml").write_text(xml, encoding="utf-8")


def test_get_session_dummy_happy_path(tmp_path):
    ciphertext_hex = encrypt_dummy_ecb(FAKE_DUMMY)
    _write_history_xml(tmp_path, ciphertext_hex)
    assert get_session_dummy(tmp_path) == FAKE_DUMMY


def test_get_session_dummy_missing_file(tmp_path):
    with pytest.raises(UnsupportedBackupError):
        get_session_dummy(tmp_path)


def test_get_session_dummy_missing_dummy_element(tmp_path):
    _write_history_xml(tmp_path, dummy_ciphertext_hex=None)
    with pytest.raises(UnsupportedBackupError):
        get_session_dummy(tmp_path)


def test_get_session_dummy_multiple_dummy_elements(tmp_path):
    ciphertext_hex = encrypt_dummy_ecb(FAKE_DUMMY)
    _write_history_xml(tmp_path, ciphertext_hex, tag_count=2)
    with pytest.raises(UnsupportedBackupError):
        get_session_dummy(tmp_path)


def test_get_session_dummy_invalid_xml(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "backupHistoryInfo.xml").write_text("<not valid xml", encoding="utf-8")
    with pytest.raises(UnsupportedBackupError):
        get_session_dummy(tmp_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_session.py -v`
Expected: `ModuleNotFoundError: No module named 'ssba.core.session'`.

- [ ] **Step 3: Write `src/ssba/core/session.py`**

```python
"""Locate and decrypt a Smart Switch backup's per-session key material."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from ssba.core.crypto import decrypt_dummy_ecb
from ssba.core.errors import UnsupportedBackupError


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def get_session_dummy(backup_root: Path) -> str:
    """Read backupHistoryInfo.xml under backup_root and return the
    decrypted session dummy string.
    """
    history_path = backup_root / "backupHistoryInfo.xml"
    if not history_path.is_file():
        raise UnsupportedBackupError(
            f"backupHistoryInfo.xml not found under {backup_root}"
        )
    try:
        tree = ET.parse(history_path)
    except ET.ParseError as exc:
        raise UnsupportedBackupError(
            f"backupHistoryInfo.xml is not valid XML: {exc}"
        ) from exc

    dummy_elements = [
        element
        for element in tree.iter()
        if _local_name(element.tag) == "Dummy" and (element.text or "").strip()
    ]
    if len(dummy_elements) != 1:
        raise UnsupportedBackupError(
            "expected exactly one <Dummy> element in backupHistoryInfo.xml, "
            f"found {len(dummy_elements)}"
        )

    ciphertext_hex = dummy_elements[0].text.strip()
    try:
        return decrypt_dummy_ecb(ciphertext_hex)
    except ValueError as exc:
        raise UnsupportedBackupError(
            f"could not decrypt the session Dummy value: {exc}"
        ) from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_session.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ssba/core/session.py tests/test_session.py
git commit -m "Add session-dummy recovery from backupHistoryInfo.xml"
```

---

### Task 5: Generic backup scanner

**Files:**
- Create: `src/ssba/core/scanner.py`
- Test: `tests/test_scanner.py`

**Interfaces:**
- Consumes:
  - `ssba.core.container.decrypt_file(raw: bytes, key: bytes) -> DecodedBlob`, `ssba.core.container.sniff_kind(data: bytes) -> Kind` (Task 3)
  - `ssba.core.crypto.derive_key(session_dummy: str) -> bytes` (Task 2)
  - `ssba.core.session.get_session_dummy(backup_root: Path) -> str` (Task 4)
- Produces:
  - `ssba.core.scanner.FileStatus` — `Literal["decrypted", "plaintext_passthrough", "undecoded", "error"]`
  - `ssba.core.scanner.FileResult` — dataclass `relative_path: str`, `status: FileStatus`, `kind: str | None`, `detail: str | None`
  - `ssba.core.scanner.CategoryResult` — dataclass `category: str`, `files: list[FileResult]`, method `counts() -> dict[str, int]`
  - `ssba.core.scanner.BackupReport` — dataclass `categories: list[CategoryResult]`, method `to_dict() -> dict`
  - `ssba.core.scanner.list_categories(backup_root: Path) -> list[str]`
  - `ssba.core.scanner.scan_category(backup_root: Path, category: str, key: bytes, out_dir: Path) -> CategoryResult`
  - `ssba.core.scanner.scan_backup(backup_root: Path, out_dir: Path) -> BackupReport` (raises `UnsupportedBackupError` if the session dummy can't be recovered)

- [ ] **Step 1: Write the failing tests, `tests/test_scanner.py`**

```python
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from ssba.core.crypto import derive_key
from ssba.core.scanner import list_categories, scan_backup, scan_category
from tests.crypto_helpers import encrypt_dummy_ecb, encrypt_iv_prefixed

FAKE_DUMMY = "AABBCCDDEEFF00112233445566778899AABB"
KEY = derive_key(FAKE_DUMMY)


def _write_history_xml(backup_root: Path) -> None:
    backup_root.mkdir(parents=True, exist_ok=True)
    ciphertext_hex = encrypt_dummy_ecb(FAKE_DUMMY)
    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<BatchInfomationItem xmlns="Kies.Common.Data">
    <BundleInfo><Dummy>{ciphertext_hex}</Dummy></BundleInfo>
</BatchInfomationItem>"""
    (backup_root / "backupHistoryInfo.xml").write_text(xml, encoding="utf-8")


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _build_fake_backup(backup_root: Path) -> None:
    _write_history_xml(backup_root)

    # Category A: a directly-encrypted file (like Notes' sdoc.bk / Calllog's exml)
    plaintext_a = b"<?xml version='1.0'?><FakeCallLogs><entry>fake</entry></FakeCallLogs>"
    (backup_root / "CATEGORY_A").mkdir()
    (backup_root / "CATEGORY_A" / "data.exml").write_bytes(
        encrypt_iv_prefixed(plaintext_a, KEY)
    )

    # Category B: a plain outer zip wrapping one encrypted entry and one
    # already-plaintext entry (like Contact.spbm)
    inner_encrypted = encrypt_iv_prefixed(b'{"contacts": ["fake person"]}', KEY)
    outer_zip = _zip_bytes(
        {
            "Contact.bk": inner_encrypted,
            "readme.txt": b"already plaintext, should pass through untouched",
        }
    )
    (backup_root / "CATEGORY_B").mkdir()
    (backup_root / "CATEGORY_B" / "wrapper.spbm").write_bytes(outer_zip)

    # Category C: data that isn't really encrypted with this scheme at all
    (backup_root / "CATEGORY_C").mkdir()
    (backup_root / "CATEGORY_C" / "mystery.bin").write_bytes(bytes(range(256)) * 4)


def test_list_categories(tmp_path):
    _build_fake_backup(tmp_path)
    assert list_categories(tmp_path) == ["CATEGORY_A", "CATEGORY_B", "CATEGORY_C"]


def test_scan_category_direct_encrypted_file(tmp_path):
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_A", KEY, out_dir)
    assert result.counts()["decrypted"] == 1
    decrypted_path = out_dir / "CATEGORY_A" / "data.exml"
    assert decrypted_path.exists()
    assert b"FakeCallLogs" in decrypted_path.read_bytes()


def test_scan_category_wrapped_zip(tmp_path):
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_B", KEY, out_dir)
    counts = result.counts()
    assert counts["plaintext_passthrough"] == 2  # wrapper.spbm itself + readme.txt
    assert counts["decrypted"] == 1  # Contact.bk
    assert (out_dir / "CATEGORY_B" / "wrapper.spbm" / "Contact.bk").exists()
    assert (out_dir / "CATEGORY_B" / "wrapper.spbm" / "readme.txt").read_bytes() == (
        b"already plaintext, should pass through untouched"
    )


def test_scan_category_undecodable_file(tmp_path):
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_C", KEY, out_dir)
    assert result.counts()["undecoded"] == 1
    assert (out_dir / "CATEGORY_C" / "mystery.bin").read_bytes() == bytes(range(256)) * 4


def test_scan_backup_end_to_end(tmp_path):
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"
    report = scan_backup(tmp_path, out_dir)
    assert [c.category for c in report.categories] == [
        "CATEGORY_A",
        "CATEGORY_B",
        "CATEGORY_C",
    ]
    totals = {"decrypted": 0, "plaintext_passthrough": 0, "undecoded": 0, "error": 0}
    for category in report.categories:
        for status, count in category.counts().items():
            totals[status] += count
    assert totals == {
        "decrypted": 2,
        "plaintext_passthrough": 2,
        "undecoded": 1,
        "error": 0,
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_scanner.py -v`
Expected: `ModuleNotFoundError: No module named 'ssba.core.scanner'`.

- [ ] **Step 3: Write `src/ssba/core/scanner.py`**

```python
"""Generic, category-agnostic scan of a Smart Switch backup: decrypt every
encrypted file it finds and report what happened, without interpreting the
content.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ssba.core.container import decrypt_file, sniff_kind
from ssba.core.crypto import derive_key
from ssba.core.session import get_session_dummy

FileStatus = Literal["decrypted", "plaintext_passthrough", "undecoded", "error"]


@dataclass
class FileResult:
    relative_path: str
    status: FileStatus
    kind: str | None = None
    detail: str | None = None


@dataclass
class CategoryResult:
    category: str
    files: list[FileResult] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {
            "decrypted": 0,
            "plaintext_passthrough": 0,
            "undecoded": 0,
            "error": 0,
        }
        for file_result in self.files:
            counts[file_result.status] += 1
        return counts


@dataclass
class BackupReport:
    categories: list[CategoryResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "categories": [
                {
                    "category": category.category,
                    "counts": category.counts(),
                    "files": [
                        {
                            "path": f.relative_path,
                            "status": f.status,
                            "kind": f.kind,
                            "detail": f.detail,
                        }
                        for f in category.files
                    ],
                }
                for category in self.categories
            ]
        }


def list_categories(backup_root: Path) -> list[str]:
    """Every top-level subfolder of the backup root is treated as a category."""
    return sorted(p.name for p in backup_root.iterdir() if p.is_dir())


def _write_output(out_path: Path, data: bytes) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)


def _process(
    name: str,
    raw: bytes,
    key: bytes,
    out_dir: Path,
    rel_prefix: str,
    results: list[FileResult],
) -> None:
    rel_path = f"{rel_prefix}{name}"
    try:
        raw_kind = sniff_kind(raw)
        if raw_kind != "binary":
            _write_output(out_dir / rel_path, raw)
            results.append(FileResult(rel_path, "plaintext_passthrough", kind=raw_kind))
            if raw_kind == "zip":
                _recurse_zip(raw, key, out_dir, rel_path + "/", results)
            return

        try:
            blob = decrypt_file(raw, key)
        except ValueError as exc:
            _write_output(out_dir / rel_path, raw)
            results.append(FileResult(rel_path, "undecoded", detail=str(exc)))
            return

        if blob.kind == "binary":
            _write_output(out_dir / rel_path, raw)
            results.append(
                FileResult(
                    rel_path, "undecoded", detail="decrypted output still unrecognized"
                )
            )
            return

        _write_output(out_dir / rel_path, blob.data)
        results.append(FileResult(rel_path, "decrypted", kind=blob.kind))
        if blob.kind == "zip":
            _recurse_zip(blob.data, key, out_dir, rel_path + "/", results)
    except Exception as exc:  # noqa: BLE001 - per-file isolation is a hard requirement
        results.append(FileResult(rel_path, "error", detail=f"{type(exc).__name__}: {exc}"))


def _recurse_zip(
    zip_bytes: bytes,
    key: bytes,
    out_dir: Path,
    rel_prefix: str,
    results: list[FileResult],
) -> None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        results.append(
            FileResult(rel_prefix.rstrip("/"), "error", detail=f"corrupt zip: {exc}")
        )
        return
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            raw = zf.read(info)
            _process(info.filename, raw, key, out_dir, rel_prefix, results)


def scan_category(
    backup_root: Path, category: str, key: bytes, out_dir: Path
) -> CategoryResult:
    category_dir = backup_root / category
    result = CategoryResult(category=category)
    if not category_dir.is_dir():
        return result
    category_out_dir = out_dir / category
    for entry in sorted(category_dir.iterdir()):
        if entry.is_file():
            _process(entry.name, entry.read_bytes(), key, category_out_dir, "", result.files)
    return result


def scan_backup(backup_root: Path, out_dir: Path) -> BackupReport:
    session_dummy = get_session_dummy(backup_root)
    key = derive_key(session_dummy)
    report = BackupReport()
    for category in list_categories(backup_root):
        report.categories.append(scan_category(backup_root, category, key, out_dir))
    return report
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_scanner.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ssba/core/scanner.py tests/test_scanner.py
git commit -m "Add generic recursive backup scanner"
```

---

### Task 6: CLI

**Files:**
- Create: `src/ssba/cli/main.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `ssba.core.scanner.scan_backup(backup_root: Path, out_dir: Path) -> BackupReport` (Task 5), `ssba.core.errors.UnsupportedBackupError` (Task 2).
- Produces: `ssba.cli.main.build_arg_parser() -> argparse.ArgumentParser`, `ssba.cli.main.run(argv: list[str] | None = None) -> int`, `ssba.cli.main.main() -> None` (the `ssba` console-script entry point from `pyproject.toml`).

- [ ] **Step 1: Write the failing tests, `tests/test_cli.py`**

```python
from __future__ import annotations

import json

from ssba.cli.main import run
from ssba.core.crypto import derive_key
from tests.crypto_helpers import encrypt_dummy_ecb, encrypt_iv_prefixed

FAKE_DUMMY = "AABBCCDDEEFF00112233445566778899AABB"
KEY = derive_key(FAKE_DUMMY)


def _build_minimal_backup(backup_root):
    backup_root.mkdir(parents=True, exist_ok=True)
    ciphertext_hex = encrypt_dummy_ecb(FAKE_DUMMY)
    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<BatchInfomationItem xmlns="Kies.Common.Data">
    <BundleInfo><Dummy>{ciphertext_hex}</Dummy></BundleInfo>
</BatchInfomationItem>"""
    (backup_root / "backupHistoryInfo.xml").write_text(xml, encoding="utf-8")
    (backup_root / "NOTES").mkdir()
    (backup_root / "NOTES" / "data.bin").write_bytes(
        encrypt_iv_prefixed(b'{"title": "fake note"}', KEY)
    )


def test_run_scan_success(tmp_path, capsys):
    backup_root = tmp_path / "backup"
    out_dir = tmp_path / "out"
    _build_minimal_backup(backup_root)

    exit_code = run(["scan", str(backup_root), "--out", str(out_dir)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "NOTES:" in captured.out
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["categories"][0]["category"] == "NOTES"


def test_run_scan_missing_backup_history(tmp_path, capsys):
    backup_root = tmp_path / "backup"
    backup_root.mkdir()
    out_dir = tmp_path / "out"

    exit_code = run(["scan", str(backup_root), "--out", str(out_dir)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "backupHistoryInfo.xml" in captured.err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: `ModuleNotFoundError: No module named 'ssba.cli.main'`.

- [ ] **Step 3: Write `src/ssba/cli/main.py`**

```python
"""Command-line entry point for the Smart Switch backup analyzer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ssba.core.errors import UnsupportedBackupError
from ssba.core.scanner import scan_backup


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ssba",
        description="Recover data from a Samsung Smart Switch PC backup.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser(
        "scan", help="decrypt every category of a Smart Switch backup"
    )
    scan_parser.add_argument(
        "backup_root",
        type=Path,
        help="path to the backup folder (contains backupHistoryInfo.xml)",
    )
    scan_parser.add_argument(
        "--out", type=Path, required=True, help="output directory for decrypted data"
    )

    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        try:
            report = scan_backup(args.backup_root, args.out)
        except UnsupportedBackupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        args.out.mkdir(parents=True, exist_ok=True)
        report_path = args.out / "report.json"
        report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

        any_success = False
        for category in report.categories:
            counts = category.counts()
            total = sum(counts.values())
            if total == 0:
                continue
            if counts["decrypted"] or counts["plaintext_passthrough"]:
                any_success = True
            print(
                f"{category.category}: {counts['decrypted']} decrypted, "
                f"{counts['plaintext_passthrough']} plaintext, "
                f"{counts['undecoded']} undecoded, "
                f"{counts['error']} errors"
            )
        print(f"\nfull report written to {report_path}")
        return 0 if any_success else 1

    return 1


def main() -> None:
    sys.exit(run())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: all tests across every module (crypto, container, session, scanner, cli) PASS — no regressions from earlier tasks.

- [ ] **Step 6: Commit**

```bash
git add src/ssba/cli/main.py tests/test_cli.py
git commit -m "Add ssba scan CLI command"
```

---

### Task 7: Manual smoke test against the real backup (not committed)

**Files:** none created or modified — this task only runs the CLI built in Task 6 against real data to sanity-check Phase 1 end to end, per the spec's documented manual-only test path.

**Interfaces:**
- Consumes: `ssba` console script (Task 6), a real Smart Switch backup folder path supplied by the project owner.
- Produces: nothing committed to git — output goes to a local `out/` (already `.gitignore`d by Task 1).

- [ ] **Step 1: Run the CLI against the real backup**

Ask the project owner for the path to their real Smart Switch backup root
(the folder containing `backupHistoryInfo.xml` — e.g.
`D:\SAMSUNGNOTE\SM-A137F_20260922111112`), then run:

```bash
ssba scan "<real backup path>" --out ./out/real-scan
```

- [ ] **Step 2: Review the summary output with the project owner**

Check that:
- Every category listed in the backup root appears in the printed summary.
- Categories already validated by hand (Notes, Contacts, Call log) show `decrypted` and/or `plaintext_passthrough` counts greater than zero, and no `error` entries.
- `./out/real-scan/report.json` exists and is well-formed JSON.

- [ ] **Step 3: Record findings**

If any category behaves unexpectedly (all `undecoded`, or `error` entries),
note which one(s) — this becomes input for the Phase 2 category-parser
design, not something to fix silently here. No code changes in this task
unless a genuine bug in Tasks 1-6 is found (in which case: write a failing
test reproducing it against a synthetic fixture first, then fix, per the
same TDD flow as the earlier tasks).

- [ ] **Step 4: Confirm `./out/` was not staged**

Run: `git status`
Expected: `out/` does not appear (it's `.gitignore`d) — working tree is
otherwise clean after Task 6's commit.

---

## Self-review notes

- **Spec coverage:** `core/session.py` (spec §core/session.py) → Task 4. `core/crypto.py` (spec §core/crypto.py) → Task 2. `core/container.py` (spec §core/container.py) → Task 3. `core/scanner.py` (spec §core/scanner.py) → Task 5. `cli/main.py` (spec §cli/main.py) → Task 6. Error handling (spec "Error handling" section: per-category continuation, aborts only when the session dummy can't be recovered) → implemented in `scanner._process`/`_recurse_zip` (never raises past a single file) and `scan_backup` (lets `UnsupportedBackupError` from `get_session_dummy` propagate, which `cli.run` catches). Testing strategy (synthetic fixtures only, no real data) → `tests/crypto_helpers.py` plus every test file. Licensing/repo hygiene (spec's carried-over section) → Task 1. Manual real-backup smoke test (spec's non-CI test path) → Task 7.
- **Placeholder scan:** no TBD/TODO, no "add appropriate error handling"-style steps — every step has literal file content or a literal command.
- **Type consistency:** `FileStatus`/`FileResult`/`CategoryResult`/`BackupReport` are defined once in Task 5 and reused as-is by Task 6; `Kind`/`DecodedBlob` defined once in Task 3 and reused by Task 5; `UnsupportedBackupError` defined once in Task 2 and reused by Tasks 4-6 — no renamed duplicates across tasks.
