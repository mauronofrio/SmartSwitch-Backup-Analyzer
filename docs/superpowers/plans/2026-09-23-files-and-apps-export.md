# Files Merge and App List Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ssba export files --mode none|copy|move` (merge the file categories into one Android storage tree, restoring original dates) and `ssba export apps` (installed apps with Play Store links), and add both to `ssba export all` (`--files`, default `none`).

**Architecture:** `src/ssba/core/parsers/files.py` plans every file (phone path, original date from the Smart Switch manifests, edited-photo originals under `_Edited photo originals/`) and then copies or moves them, merging byte-identical duplicates and never overwriting. `src/ssba/core/parsers/apps.py` turns `APKFILE/AppList.json` into a page. The CLI adds two subcommands and passes the files mode through `export all`.

**Tech Stack:** Python 3.10+ stdlib (`os`, `shutil`, `hashlib`, `json`, `urllib.parse`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-23-files-and-apps-export-design.md`

## Global Constraints

- Python 3.10+, no new dependency. `core/` never prints; only `cli/` does.
- `move` only ever deletes a source after it has been moved or proven identical (same size and SHA-256) to the file already at the target. Existing output files are never overwritten.
- No real personal data in the repository, tests or fixtures.
- No attribution lines in commit messages; nothing pushed; work directly on `master`.
- Run tests with `python -m pytest` from `D:/SmartSwitch-Backup-Analyzer`; pass paths to Python as `D:/...`.
- Create/edit files with editor tools, never through scripts or heredocs.

---

### Task 1: Planning the Android tree

**Files:**
- Create: `src/ssba/core/parsers/files.py` (planning part)
- Create: `tests/files_fixtures.py`
- Create: `tests/test_files_plan.py`

**Interfaces:**
- Consumes: `category_files`, `MissingCategoryError`, `ScanReportError` (`ssba.core.parsers.scan_report`); `add_category`, `entry` (`tests/scan_fixtures.py`).
- Produces:
  - `ssba.core.parsers.files`: `STORAGE_CATEGORIES`, `ORIGIN_CATEGORIES`, `ORIGINALS_FOLDER = "_Edited photo originals"`, `FilesExportError(Exception)`, `PlannedFile` (frozen dataclass: `source: Path`, `target: PurePosixPath`, `original: bool`, `mtime: float | None`), `FilesPlan` (dataclass: `files: list[PlannedFile]`, `categories: list[str]`, `missing: int = 0`, `bad_manifests: int = 0`), `found_categories(scan_dir: Path) -> list[str]`, `plan_files(scan_dir: Path) -> FilesPlan`.
  - `tests.files_fixtures`: `T`, `FILES`, `MANIFESTS`, `build_files_scan_dir(scan_dir: Path, *, files=FILES, manifests=MANIFESTS, raw_manifests=None) -> Path`, `MANIFEST_DIR`.

- [ ] **Step 1: Write the fixtures** — `tests/files_fixtures.py`:

```python
"""Fabricated Smart Switch file categories for tests - no real files."""

from __future__ import annotations

import json
from pathlib import Path

from tests.scan_fixtures import add_category, entry

T = 1600000000000  # ms
MANIFEST_DIR = "data/user/0/com.sec.android.easyMover/files/SmartSwitch/tmp"

# category -> {phone path inside the category: bytes}
FILES = {
    "Photo": {
        "DCIM/Camera/a.jpg": b"photo-a",
        "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/w.jpg": b"wa",
    },
    "Video": {"DCIM/Camera/v.mp4": b"video"},
    "Docs": {"Download/doc.pdf": b"pdf", "root.docx": b"docx"},
    "EtcFolder": {"Download/doc.pdf": b"pdf", "Download/only.ics": b"ics"},
    "PHOTO_ORIGIN": {
        "data/sec/photoeditor/0/storage/emulated/0/DCIM/Camera/a.jpg": b"original-a",
        "data/sec/photoeditor/0/flat.jpg": b"flat",
    },
}


def item(path: str, ms: int) -> dict:
    return {"FilePath": path, "FileName": path.rsplit("/", 1)[-1], "Length": 0, "DateModified": ms}


# category -> manifest entries
MANIFESTS = {
    "Photo": [item("/mnt/sdcard/DCIM/Camera/a.jpg", T), item("/mnt/sdcard/DCIM/Camera/gone.jpg", T)],
    "Docs": [item("/storage/emulated/0/Download/doc.pdf", T + 1000), item("/mnt/sdcard/root.docx", T + 2000)],
    "EtcFolder": [item("/mnt/sdcard/Download/doc.pdf", T + 9000), item("/mnt/sdcard/Download/only.ics", T + 3000)],
}


def build_files_scan_dir(scan_dir: Path, *, files=FILES, manifests=MANIFESTS, raw_manifests=None) -> Path:
    """Write fake category folders; ``raw_manifests`` maps a category to raw manifest text."""
    raw_manifests = raw_manifests or {}
    categories = list(dict.fromkeys([*files, *manifests, *raw_manifests]))
    for category in categories:
        root = scan_dir / category
        root.mkdir(parents=True, exist_ok=True)
        for rel, data in files.get(category, {}).items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        text = raw_manifests.get(category)
        if text is None and category in manifests:
            entries = manifests[category]
            text = json.dumps({"categoryType": category.upper(), "count": len(entries), "files": entries})
        if text is not None:
            manifest = root / MANIFEST_DIR / category.upper() / "list.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(text, encoding="utf-8")
        add_category(scan_dir, category, [entry("placeholder")])
    return scan_dir
```

- [ ] **Step 2: Write the failing tests** — `tests/test_files_plan.py`:

```python
from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from ssba.core.parsers.files import FilesExportError, found_categories, plan_files
from tests.files_fixtures import T, build_files_scan_dir
from tests.scan_fixtures import add_category


def _targets(plan):
    return {f.target.as_posix(): f for f in plan.files}


def test_categories_found_in_fixed_order(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    assert found_categories(scan_dir) == ["Photo", "Video", "Docs", "EtcFolder", "PHOTO_ORIGIN"]


def test_storage_files_keep_their_phone_paths_and_manifests_are_excluded(tmp_path):
    plan = plan_files(build_files_scan_dir(tmp_path / "scan"))
    storage = [f.target.as_posix() for f in plan.files if not f.original]
    assert storage == [
        "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/w.jpg",
        "DCIM/Camera/a.jpg",
        "DCIM/Camera/v.mp4",
        "Download/doc.pdf",
        "root.docx",
        "Download/doc.pdf",
        "Download/only.ics",
    ]


def test_original_dates_come_from_the_manifests_first_entry_wins(tmp_path):
    plan = plan_files(build_files_scan_dir(tmp_path / "scan"))
    dates = {f.target.as_posix(): f.mtime for f in plan.files if not f.original}
    assert dates["DCIM/Camera/a.jpg"] == T / 1000
    assert dates["Download/doc.pdf"] == (T + 1000) / 1000
    assert dates["root.docx"] == (T + 2000) / 1000
    assert dates["Download/only.ics"] == (T + 3000) / 1000
    assert dates["DCIM/Camera/v.mp4"] is None


def test_manifest_entries_without_a_file_are_counted(tmp_path):
    assert plan_files(build_files_scan_dir(tmp_path / "scan")).missing == 1


def test_unreadable_manifest_is_ignored_and_counted(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan", raw_manifests={"Video": "{not json"})
    plan = plan_files(scan_dir)
    assert plan.bad_manifests == 1
    assert "DCIM/Camera/v.mp4" in [f.target.as_posix() for f in plan.files]


def test_bad_manifest_values_are_skipped(tmp_path):
    manifests = {"Photo": [
        "not a dict",
        {"FilePath": 42, "DateModified": T},
        {"FilePath": "/elsewhere/DCIM/Camera/a.jpg", "DateModified": T},
        {"FilePath": "/mnt/sdcard/DCIM/Camera/a.jpg", "DateModified": "yesterday"},
        {"FilePath": "/mnt/sdcard/DCIM/Camera/a.jpg", "DateModified": True},
    ]}
    plan = plan_files(build_files_scan_dir(tmp_path / "scan", manifests=manifests))
    assert _targets(plan)["DCIM/Camera/a.jpg"].mtime is None
    assert (plan.missing, plan.bad_manifests) == (0, 0)


def test_originals_go_to_their_own_folder(tmp_path):
    plan = plan_files(build_files_scan_dir(tmp_path / "scan"))
    originals = [(f.target.as_posix(), f.mtime) for f in plan.files if f.original]
    # sorted by path inside the category: ".../0/flat.jpg" < ".../0/storage/..."
    assert originals == [
        ("_Edited photo originals/flat.jpg", None),
        ("_Edited photo originals/DCIM/Camera/a.jpg", None),
    ]
    assert all(isinstance(f.target, PurePosixPath) for f in plan.files)


def test_absent_categories_are_skipped(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan", files={"Music": {"Music/s.mp3": b"s"}}, manifests={})
    assert found_categories(scan_dir) == ["Music"]
    assert [f.target.as_posix() for f in plan_files(scan_dir).files] == ["Music/s.mp3"]


def test_category_in_the_report_without_its_folder_is_skipped(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan", files={"Music": {"Music/s.mp3": b"s"}}, manifests={})
    add_category(scan_dir, "Photo", [])
    assert found_categories(scan_dir) == ["Music"]


def test_no_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(FilesExportError, match="no file categories"):
        plan_files(tmp_path)


def test_missing_report_raises(tmp_path):
    with pytest.raises(FilesExportError, match="report.json"):
        found_categories(tmp_path)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_files_plan.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'ssba.core.parsers.files'`.

- [ ] **Step 4: Implement** — `src/ssba/core/parsers/files.py`:

```python
"""Merge the file categories of a scan into one Android storage tree."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ssba.core.parsers.scan_report import MissingCategoryError, ScanReportError, category_files

STORAGE_CATEGORIES = ("Photo", "Video", "Music", "Docs", "EtcFile", "EtcFolder")
ORIGIN_CATEGORIES = ("PHOTO_ORIGIN", "VIDEO_ORIGIN")
ORIGINALS_FOLDER = "_Edited photo originals"
# Smart Switch keeps its per-category file list here; it is not a phone file.
_MANIFEST_PARTS = PurePosixPath("data/user/0/com.sec.android.easyMover").parts
_STORAGE_PREFIXES = ("/mnt/sdcard/", "/storage/emulated/0/")
_ORIGIN_PREFIXES = ("data/sec/photoeditor/0/storage/emulated/0/", "data/sec/photoeditor/0/")


class FilesExportError(Exception):
    """Raised when the file categories cannot be merged."""


@dataclass(frozen=True)
class PlannedFile:
    source: Path
    target: PurePosixPath  # path inside the output folder
    original: bool  # an edited photo's original
    mtime: float | None  # original modification time, Unix seconds


@dataclass
class FilesPlan:
    files: list[PlannedFile] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    missing: int = 0
    bad_manifests: int = 0


def found_categories(scan_dir: Path) -> list[str]:
    """The file categories of the scan that exist on disk, in merge order."""
    found = []
    for category in STORAGE_CATEGORIES + ORIGIN_CATEGORIES:
        try:
            category_files(scan_dir, category)
        except MissingCategoryError:
            continue
        except ScanReportError as exc:
            raise FilesExportError(str(exc)) from exc
        if (scan_dir / category).is_dir():
            found.append(category)
    if not found:
        raise FilesExportError("no file categories found in the scan output")
    return found


def _walk(root: Path) -> list[PurePosixPath]:
    rels = []
    for dirpath, _, filenames in os.walk(root):  # symlinked folders are not followed
        base = Path(dirpath)
        for name in filenames:
            path = base / name
            if path.is_file() and not path.is_symlink():
                rels.append(PurePosixPath(path.relative_to(root).as_posix()))
    return sorted(rels)


def _is_manifest_path(rel: PurePosixPath) -> bool:
    return rel.parts[: len(_MANIFEST_PARTS)] == _MANIFEST_PARTS


def _manifest_entries(path: Path) -> list | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    files = data.get("files") if isinstance(data, dict) else None
    return files if isinstance(files, list) else None


def _phone_path(file_path) -> str | None:
    if not isinstance(file_path, str):
        return None
    for prefix in _STORAGE_PREFIXES:
        if file_path.startswith(prefix):
            return file_path[len(prefix):]
    return None


def _original_target(rel: PurePosixPath) -> PurePosixPath:
    text = rel.as_posix()
    for prefix in _ORIGIN_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return PurePosixPath(ORIGINALS_FOLDER) / text


def plan_files(scan_dir: Path) -> FilesPlan:
    plan = FilesPlan(categories=found_categories(scan_dir))
    dates: dict[str, float] = {}
    listed: set[str] = set()
    storage: list[tuple[Path, PurePosixPath]] = []
    originals: list[PlannedFile] = []

    for category in plan.categories:
        root = scan_dir / category
        for rel in _walk(root):
            if category in ORIGIN_CATEGORIES:
                originals.append(PlannedFile(root / rel, _original_target(rel), True, None))
            elif not _is_manifest_path(rel):
                storage.append((root / rel, rel))
            elif rel.suffix.lower() == ".json":
                entries = _manifest_entries(root / rel)
                if entries is None:
                    plan.bad_manifests += 1
                    continue
                for item in entries:
                    phone = _phone_path(item.get("FilePath")) if isinstance(item, dict) else None
                    if phone is None:
                        continue
                    listed.add(phone)
                    ms = item.get("DateModified")
                    if isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms > 0:
                        dates.setdefault(phone, ms / 1000)

    plan.missing = len(listed - {rel.as_posix() for _, rel in storage})
    plan.files = [
        PlannedFile(source, rel, False, dates.get(rel.as_posix())) for source, rel in storage
    ] + originals
    return plan
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_files_plan.py -v`, then `python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ssba/core/parsers/files.py tests/files_fixtures.py tests/test_files_plan.py
git commit -m "feat: plan the Android storage tree from the scanned file categories"
```

---

### Task 2: Copying or moving into the tree

**Files:**
- Modify: `src/ssba/core/parsers/files.py` (append; add `import hashlib` and `import shutil`)
- Create: `tests/test_files_export.py`

**Interfaces:**
- Consumes: `plan_files`, `FilesPlan`, `PlannedFile`, `FilesExportError` (Task 1); fixtures (Task 1).
- Produces: `ssba.core.parsers.files.FilesExportResult` (dataclass: `placed`, `merged`, `already_present`, `conflicts`, `originals`, `dated`, `missing`, `bad_manifests`, all `int = 0`), `export_files(scan_dir: Path, out_dir: Path, mode: str) -> FilesExportResult`.

- [ ] **Step 1: Write the failing tests** — `tests/test_files_export.py`:

```python
from __future__ import annotations

import os

import pytest

from ssba.core.parsers.files import export_files
from tests.files_fixtures import FILES, T, build_files_scan_dir

TREE = sorted([
    "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/w.jpg",
    "DCIM/Camera/a.jpg",
    "DCIM/Camera/v.mp4",
    "Download/doc.pdf",
    "Download/only.ics",
    "root.docx",
    "_Edited photo originals/DCIM/Camera/a.jpg",
    "_Edited photo originals/flat.jpg",
])


def _tree(out):
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())


def _export(tmp_path, mode, **kwargs):
    scan_dir = build_files_scan_dir(tmp_path / "scan", **kwargs)
    out = tmp_path / "out"
    return scan_dir, out, export_files(scan_dir, out, mode)


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_files_form_one_android_tree(tmp_path, mode):
    _, out, result = _export(tmp_path, mode)
    assert _tree(out) == TREE
    assert (out / "DCIM/Camera/a.jpg").read_bytes() == b"photo-a"
    assert (out / "_Edited photo originals/DCIM/Camera/a.jpg").read_bytes() == b"original-a"
    assert (result.placed, result.merged, result.conflicts, result.originals) == (8, 1, 0, 2)
    assert (result.dated, result.missing, result.bad_manifests, result.already_present) == (4, 1, 0, 0)


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_files_get_their_original_dates(tmp_path, mode):
    _, out, _ = _export(tmp_path, mode)
    assert abs(os.path.getmtime(out / "DCIM/Camera/a.jpg") - T / 1000) < 1
    assert abs(os.path.getmtime(out / "Download/doc.pdf") - (T + 1000) / 1000) < 1


def test_copy_keeps_the_category_folders(tmp_path):
    scan_dir, _, _ = _export(tmp_path, "copy")
    for category, files in FILES.items():
        for rel, data in files.items():
            assert (scan_dir / category / rel).read_bytes() == data


def test_move_empties_the_category_folders(tmp_path):
    scan_dir, _, _ = _export(tmp_path, "move")
    for category, files in FILES.items():
        for rel in files:
            assert not (scan_dir / category / rel).exists()
    assert not (scan_dir / "Video").exists()
    assert not (scan_dir / "PHOTO_ORIGIN").exists()
    assert (scan_dir / "Photo").is_dir()  # still holds its Smart Switch file list
    assert not (scan_dir / "Photo" / "DCIM").exists()


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_same_path_with_different_content_is_kept_as_a_numbered_copy(tmp_path, mode):
    files = {**FILES, "EtcFolder": {"Download/doc.pdf": b"other", "Download/only.ics": b"ics"}}
    _, out, result = _export(tmp_path, mode, files=files)
    assert (out / "Download/doc.pdf").read_bytes() == b"pdf"
    assert (out / "Download/doc (2).pdf").read_bytes() == b"other"
    assert (result.conflicts, result.merged, result.placed) == (1, 0, 9)


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_existing_output_files_are_never_overwritten(tmp_path, mode):
    out = tmp_path / "out"
    (out / "DCIM/Camera").mkdir(parents=True)
    (out / "DCIM/Camera/a.jpg").write_bytes(b"mine")
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    result = export_files(scan_dir, out, mode)
    assert (out / "DCIM/Camera/a.jpg").read_bytes() == b"mine"
    assert (out / "DCIM/Camera/a (2).jpg").read_bytes() == b"photo-a"
    assert result.conflicts == 1


def test_copy_rerun_writes_nothing_new(tmp_path):
    scan_dir, out, _ = _export(tmp_path, "copy")
    again = export_files(scan_dir, out, "copy")
    assert (again.placed, again.already_present, again.merged) == (0, 9, 0)
    assert _tree(out) == TREE


def test_move_deletes_a_duplicate_source_only_after_the_identity_check(tmp_path):
    scan_dir, out, result = _export(tmp_path, "move")
    assert result.merged == 1
    assert not (scan_dir / "EtcFolder/Download/doc.pdf").exists()
    assert (out / "Download/doc.pdf").read_bytes() == b"pdf"


def test_unknown_mode_raises(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    with pytest.raises(ValueError, match="mode"):
        export_files(scan_dir, tmp_path / "out", "none")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_files_export.py -v`
Expected: collection error `ImportError: cannot import name 'export_files'`.

- [ ] **Step 3: Implement.** Add `import hashlib` and `import shutil` to `src/ssba/core/parsers/files.py` and append:

```python
_MAX_TIME = 253402300800  # 9999-12-31: os.utime rejects later times on Windows


@dataclass
class FilesExportResult:
    placed: int = 0
    merged: int = 0
    already_present: int = 0
    conflicts: int = 0
    originals: int = 0
    dated: int = 0
    missing: int = 0
    bad_manifests: int = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _identical(a: Path, b: Path) -> bool:
    return a.stat().st_size == b.stat().st_size and _sha256(a) == _sha256(b)


def _candidates(target: Path):
    yield target
    n = 2
    while True:
        yield target.with_name(f"{target.stem} ({n}){target.suffix}")
        n += 1


def _place(source: Path, target: Path, mode: str, placed_now: set[Path]) -> tuple[str, Path]:
    """Put ``source`` at ``target`` (or a numbered free name), never overwriting.

    Returns ("placed" | "conflict" | "merged" | "present", final path).
    """
    conflict = False
    for candidate in _candidates(target):
        if not candidate.exists():
            candidate.parent.mkdir(parents=True, exist_ok=True)
            if mode == "move":
                shutil.move(str(source), str(candidate))
            else:
                shutil.copyfile(source, candidate)
            placed_now.add(candidate)
            return ("conflict" if conflict else "placed"), candidate
        if candidate.is_file() and _identical(source, candidate):
            if mode == "move":
                source.unlink()  # only after proving the target holds the same bytes
            return ("merged" if candidate in placed_now else "present"), candidate
        conflict = True
    raise AssertionError("unreachable")


def _set_mtime(path: Path, seconds: float | None) -> bool:
    if seconds is None or not 0 < seconds < _MAX_TIME:
        return False
    try:
        os.utime(path, (seconds, seconds))
    except OSError:
        return False
    return True


def _remove_empty_dirs(root: Path) -> None:
    for dirpath, _, _ in os.walk(root, topdown=False):
        try:
            Path(dirpath).rmdir()
        except OSError:
            pass  # not empty


def export_files(scan_dir: Path, out_dir: Path, mode: str) -> FilesExportResult:
    if mode not in ("copy", "move"):
        raise ValueError(f"unknown mode {mode!r}: expected 'copy' or 'move'")
    plan = plan_files(scan_dir)
    result = FilesExportResult(missing=plan.missing, bad_manifests=plan.bad_manifests)
    placed_now: set[Path] = set()
    for item in plan.files:
        target = out_dir.joinpath(*item.target.parts)
        try:
            status, final = _place(item.source, target, mode, placed_now)
        except OSError as exc:
            raise FilesExportError(f"cannot {mode} {item.source}: {exc}") from exc
        if status in ("placed", "conflict"):
            result.placed += 1
            result.conflicts += status == "conflict"
            result.originals += item.original
            result.dated += _set_mtime(final, item.mtime)
        elif status == "merged":
            result.merged += 1
        else:
            result.already_present += 1
    if mode == "move":
        for category in plan.categories:
            _remove_empty_dirs(scan_dir / category)
    return result
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_files_export.py -v`, then `python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ssba/core/parsers/files.py tests/test_files_export.py
git commit -m "feat: copy or move the scanned files into one Android tree"
```

---

### Task 3: App list

**Files:**
- Create: `src/ssba/core/parsers/apps.py`
- Create: `tests/test_apps_export.py` (fixture builder inside, plus `tests/apps_fixtures.py` for reuse by the CLI tests)
- Create: `tests/apps_fixtures.py`

**Interfaces:**
- Consumes: `category_files`, `ScanReportError`; `esc`, `format_time`, `page`, `safe_link`, `write_output`; `add_category`, `entry`.
- Produces: `ssba.core.parsers.apps.AppsExportError(Exception)`, `AppsExportResult` (dataclass: `apps: int`, `skipped: int = 0`), `export_apps(scan_dir: Path, out_path: Path) -> AppsExportResult`; `tests.apps_fixtures.build_apps_scan_dir(scan_dir: Path, apps=APPS, *, raw: str | None = None) -> Path`, `APPS`, `T`.

- [ ] **Step 1: Write the fixtures** — `tests/apps_fixtures.py`:

```python
"""Fabricated Smart Switch app list for tests - no real data."""

from __future__ import annotations

import json
from pathlib import Path

from tests.scan_fixtures import add_category, entry

T = 1700000000000
APPS = [
    {"ApkName": "Zeta <b>", "ApkPkgName": "com.zeta", "VersionName": "1.0",
     "InstPkgName": "com.android.vending", "LastTimeUsed": T},
    {"ApkName": "alfa", "ApkPkgName": "org.alfa", "VersionName": "2"},
    {"ApkPkgName": "com.noname"},
    {"ApkName": "Broken"},
    "not a dict",
]


def build_apps_scan_dir(scan_dir: Path, apps=APPS, *, raw: str | None = None) -> Path:
    folder = scan_dir / "APKFILE"
    folder.mkdir(parents=True)
    text = raw if raw is not None else json.dumps({"Apks": apps})
    (folder / "AppList.json").write_text(text, encoding="utf-8")
    add_category(scan_dir, "APKFILE", [entry("AppList.json", status="plaintext_passthrough", kind="json")])
    return scan_dir
```

- [ ] **Step 2: Write the failing tests** — `tests/test_apps_export.py`:

```python
from __future__ import annotations

import pytest

from ssba.core.parsers.apps import AppsExportError, export_apps
from ssba.core.parsers.html_page import format_time
from tests.apps_fixtures import T, build_apps_scan_dir
from tests.scan_fixtures import add_category


def _export(tmp_path, **kwargs):
    out = tmp_path / "apps.html"
    result = export_apps(build_apps_scan_dir(tmp_path / "scan", **kwargs), out)
    return result, out.read_text(encoding="utf-8")


def test_apps_are_listed_sorted_with_store_links(tmp_path):
    result, html = _export(tmp_path)
    assert (result.apps, result.skipped) == (2 + 1, 2)
    assert html.index("alfa") < html.index("com.noname") < html.index("Zeta &lt;b&gt;")
    assert '<a href="https://play.google.com/store/apps/details?id=com.zeta">' in html
    assert format_time(T / 1000) in html
    assert "com.android.vending" in html
    assert "<b>" not in html


def test_package_names_are_url_encoded_in_links(tmp_path):
    _, html = _export(tmp_path, apps=[{"ApkName": "X", "ApkPkgName": "a&b"}])
    assert 'href="https://play.google.com/store/apps/details?id=a%26b"' in html


def test_missing_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(AppsExportError, match="APKFILE"):
        export_apps(tmp_path, tmp_path / "apps.html")


def test_no_app_list_raises(tmp_path):
    add_category(tmp_path, "APKFILE", [])
    with pytest.raises(AppsExportError, match="AppList.json"):
        export_apps(tmp_path, tmp_path / "apps.html")


def test_invalid_json_raises(tmp_path):
    with pytest.raises(AppsExportError, match="cannot read"):
        _export(tmp_path, raw="{not json")


def test_json_without_an_apps_list_raises(tmp_path):
    with pytest.raises(AppsExportError, match="Apks"):
        _export(tmp_path, raw='{"Other": []}')


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_apps_scan_dir(tmp_path / "scan")
    out = tmp_path / "apps.html"
    out.mkdir()
    with pytest.raises(AppsExportError, match="cannot write"):
        export_apps(scan_dir, out)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_apps_export.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'ssba.core.parsers.apps'`.

- [ ] **Step 4: Implement** — `src/ssba/core/parsers/apps.py`:

```python
"""List the apps the phone had, with a link to reinstall each from the Play Store."""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from ssba.core.parsers.html_page import esc, format_time, page, safe_link, write_output
from ssba.core.parsers.scan_report import ScanReportError, category_files

_APP_LIST = "AppList.json"
_PLAY_URL = "https://play.google.com/store/apps/details?id="


class AppsExportError(Exception):
    """Raised when the app list cannot be exported."""


@dataclass
class AppsExportResult:
    apps: int
    skipped: int = 0


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _last_used(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return format_time(value / 1000)
    return ""


def export_apps(scan_dir: Path, out_path: Path) -> AppsExportResult:
    try:
        paths = category_files(scan_dir, "APKFILE")
    except ScanReportError as exc:
        raise AppsExportError(str(exc)) from exc
    source = next((p for p in paths if p.name == _APP_LIST), None)
    if source is None:
        raise AppsExportError(f"no app list ({_APP_LIST}) found in the scan output")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppsExportError(f"cannot read {source}: {exc}") from exc
    items = data.get("Apks") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise AppsExportError(f"{source} has no Apks list")

    rows = []
    skipped = 0
    for item in items:
        package = _text(item.get("ApkPkgName")) if isinstance(item, dict) else ""
        if not package:
            skipped += 1
            continue
        rows.append((
            _text(item.get("ApkName")) or package,
            package,
            _text(item.get("VersionName")),
            _text(item.get("InstPkgName")),
            _last_used(item.get("LastTimeUsed")),
        ))
    rows.sort(key=lambda row: (row[0].casefold(), row[1]))

    table = "".join(
        f"<tr><td>{esc(name)}</td><td>{esc(package)}</td><td>{esc(version)}</td>"
        f"<td>{esc(installer)}</td><td>{esc(last_used)}</td>"
        f"<td>{safe_link(_PLAY_URL + urllib.parse.quote(package, safe='.'), 'Play Store')}</td></tr>\n"
        for name, package, version, installer, last_used in rows
    )
    body = (
        '<p class="note">Reinstall these apps from their store: their data is not in the '
        "backup in a form that can be restored.</p>\n<table>\n"
        "<tr><th>App</th><th>Package</th><th>Version</th><th>Installed from</th>"
        "<th>Last used</th><th>Link</th></tr>\n" + table + "</table>"
    )
    write_output(out_path, page("Apps", body), AppsExportError)
    return AppsExportResult(apps=len(rows), skipped=skipped)
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_apps_export.py -v`, then `python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ssba/core/parsers/apps.py tests/apps_fixtures.py tests/test_apps_export.py
git commit -m "feat: list the installed apps with Play Store links"
```

---

### Task 4: CLI

**Files:**
- Modify: `src/ssba/cli/main.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `export_files`, `found_categories`, `FilesExportError`, `ORIGINALS_FOLDER` (Tasks 1-2); `export_apps`, `AppsExportError` (Task 3); fixtures `build_files_scan_dir` (`tests/files_fixtures.py`), `build_apps_scan_dir` (`tests/apps_fixtures.py`).
- Produces: `ssba export files <scan_dir> --out <dir> --mode none|copy|move`; `ssba export apps <scan_dir> --out <file>`; `ssba export all … [--files none|copy|move]` (11 kinds).

- [ ] **Step 1: Write the failing tests.** In `tests/test_cli.py`:
  - add imports `from tests.apps_fixtures import build_apps_scan_dir` and `from tests.files_fixtures import build_files_scan_dir`;
  - in the two `for kind in (…, "notes")` tuples of the existing `export all` tests, append `"apps", "files"`;
  - change every `"… of 9 exports written…"` assertion to `of 11` (the counts `2`, `1`, `0`, `1` stay the same);
  - append:

```python
def test_export_files_none_leaves_the_files_where_they_are(tmp_path, capsys):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    out = tmp_path / "files"
    assert run(["export", "files", str(scan_dir), "--out", str(out), "--mode", "none"]) == 0
    assert (
        f"files left in their category folders in {scan_dir}: Photo, Video, Docs, EtcFolder, PHOTO_ORIGIN"
        in capsys.readouterr().out
    )
    assert not out.exists()


@pytest.mark.parametrize("mode, verb", [("copy", "copied"), ("move", "moved")])
def test_export_files_merge(tmp_path, capsys, mode, verb):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    out = tmp_path / "files"
    assert run(["export", "files", str(scan_dir), "--out", str(out), "--mode", mode]) == 0
    printed = capsys.readouterr().out
    assert f"8 files {verb} into {out}" in printed
    assert "1 duplicate files of the backup merged" in printed
    assert f"2 originals of edited photos in {out / '_Edited photo originals'}" in printed
    assert "4 files got their original date back" in printed
    assert "1 files listed by Smart Switch were not found in the scan" in printed
    assert "already there" not in printed
    assert "different content" not in printed


def test_export_files_requires_a_mode(tmp_path):
    with pytest.raises(SystemExit):
        run(["export", "files", str(tmp_path), "--out", str(tmp_path / "f")])


def test_export_files_error(tmp_path, capsys):
    assert run(["export", "files", str(tmp_path), "--out", str(tmp_path / "f"), "--mode", "copy"]) == 1
    assert capsys.readouterr().err.startswith("error: report.json not found")


def test_export_apps_success(tmp_path, capsys):
    scan_dir = build_apps_scan_dir(tmp_path / "scan")
    out = tmp_path / "apps.html"
    assert run(["export", "apps", str(scan_dir), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert f"3 apps listed in {out}" in printed
    assert "2 entries without a package skipped" in printed


def test_export_all_merges_files_only_when_asked(tmp_path, capsys):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    build_apps_scan_dir(scan_dir)
    out = tmp_path / "all"
    assert run(["export", "all", str(scan_dir), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "files left in their category folders" in printed
    assert not (out / "files").exists()
    assert (out / "apps.html").is_file()
    assert f"2 of 11 exports written to {out}" in printed

    assert run(["export", "all", str(scan_dir), "--out", str(out), "--files", "copy"]) == 0
    assert (out / "files" / "DCIM" / "Camera" / "a.jpg").is_file()
```

(Add `import pytest` at the top of `tests/test_cli.py` if it is not imported yet.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: the new and edited tests FAIL (`invalid choice: 'files'`, `of 9`); others PASS.

- [ ] **Step 3: Implement** — in `src/ssba/cli/main.py`:

Imports (alphabetical among the parser imports; add `import functools` to the stdlib imports):

```python
from ssba.core.parsers.apps import AppsExportError, export_apps
from ssba.core.parsers.files import (
    ORIGINALS_FOLDER,
    FilesExportError,
    export_files,
    found_categories,
)
```

In `build_arg_parser`, add to the `exports` tuple, before `("all", …)`:

```python
        ("apps", "list the installed apps with Play Store links", "the .html file to write"),
        ("files", "merge photos, videos, music and documents into one Android folder tree", "the directory to write"),
```

Change the subparser loop so it keeps each parser, and add the two extra options after it:

```python
    kind_parsers = {}
    for name, help_text, out_help in exports:
        kind_parser = export_kinds.add_parser(name, help=help_text)
        kind_parser.add_argument(
            "scan_dir", type=Path, help="directory written by `ssba scan --out`"
        )
        kind_parser.add_argument("--out", type=Path, required=True, help=out_help)
        kind_parsers[name] = kind_parser
    kind_parsers["files"].add_argument(
        "--mode",
        choices=("none", "copy", "move"),
        required=True,
        help="move or copy the files into one Android tree, or leave them in their category folders",
    )
    kind_parsers["all"].add_argument(
        "--files",
        choices=("none", "copy", "move"),
        default="none",
        help="what `export files` does inside --out (default: none)",
    )
```

After `_run_export_notes`, add:

```python
def _run_export_apps(scan_dir: Path, out: Path) -> int:
    try:
        result = export_apps(scan_dir, out)
    except AppsExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{result.apps} apps listed in {out}")
    if result.skipped:
        print(f"{result.skipped} entries without a package skipped")
    return 0


def _run_export_files(scan_dir: Path, out: Path, mode: str) -> int:
    if mode == "none":
        try:
            categories = found_categories(scan_dir)
        except FilesExportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"files left in their category folders in {scan_dir}: {', '.join(categories)}")
        return 0
    try:
        result = export_files(scan_dir, out, mode)
    except FilesExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    verb = "moved" if mode == "move" else "copied"
    print(f"{result.placed} files {verb} into {out}")
    if result.merged:
        print(f"{result.merged} duplicate files of the backup merged")
    if result.already_present:
        print(f"{result.already_present} files were already there")
    if result.conflicts:
        print(
            f"{result.conflicts} files had the same path but different content; "
            "kept as '<name> (2)'"
        )
    if result.originals:
        print(f"{result.originals} originals of edited photos in {out / ORIGINALS_FOLDER}")
    if result.dated:
        print(f"{result.dated} files got their original date back")
    if result.missing:
        print(f"{result.missing} files listed by Smart Switch were not found in the scan")
    if result.bad_manifests:
        print(f"{result.bad_manifests} Smart Switch file lists could not be read")
    return 0
```

Add `("apps", _run_export_apps, "apps.html"),` as the last entry of `_ALL_EXPORTS`, and replace `_run_export_all`, `_EXPORT_RUNNERS` and the export branch of `run` with:

```python
def _run_export_all(scan_dir: Path, out: Path, files_mode: str = "none") -> int:
    if not (scan_dir / "report.json").is_file():
        print(f"error: report.json not found in {scan_dir}", file=sys.stderr)
        return 1
    jobs = list(_ALL_EXPORTS) + [
        ("files", functools.partial(_run_export_files, mode=files_mode), "files"),
    ]
    written = 0
    for name, runner, target in jobs:
        print(f"== {name} ==")
        try:
            if runner(scan_dir, out / target) == 0:
                written += 1
        except Exception as exc:  # an unexpected bug in one exporter must not stop the rest
            print(f"error: {name} failed unexpectedly: {exc}", file=sys.stderr)
    print(f"\n{written} of {len(jobs)} exports written to {out}")
    return 0 if written else 1


_EXPORT_RUNNERS = {name: runner for name, runner, _ in _ALL_EXPORTS}
```

```python
    if args.command == "export":
        if args.export_kind == "all":
            return _run_export_all(args.scan_dir, args.out, args.files)
        if args.export_kind == "files":
            return _run_export_files(args.scan_dir, args.out, args.mode)
        return _EXPORT_RUNNERS[args.export_kind](args.scan_dir, args.out)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ssba/cli/main.py tests/test_cli.py
git commit -m "feat: add ssba export files and ssba export apps"
```

---

## After the tasks (controller, not a subagent task)

Local-only validation (outputs under the git-ignored `out/`):
- `copy` on `out/real-scan-v4` into `out/files-copy`: 16,231 storage paths + 401 originals placed, 940 merged, 0 conflicts, every placed file's SHA-256 equal to its source, 16,231 dated, missing 0.
- `move` on a **copy** of the scan folder (never on `out/real-scan-v4` itself): same counts; the storage and origin category folders keep only the Smart Switch file lists.
- `apps` → 129 apps.
