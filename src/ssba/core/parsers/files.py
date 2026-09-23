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
                    # Android's shared storage is case-insensitive, and Smart Switch's
                    # manifest sometimes spells a folder differently than the scanned path
                    # (e.g. "WhatsApp" vs "Whatsapp"): match case-insensitively.
                    key = phone.casefold()
                    listed.add(key)
                    ms = item.get("DateModified")
                    if isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms > 0:
                        dates.setdefault(key, ms / 1000)

    scanned = {rel.as_posix().casefold() for _, rel in storage}
    plan.missing = len(listed - scanned)
    plan.files = [
        PlannedFile(source, rel, False, dates.get(rel.as_posix().casefold())) for source, rel in storage
    ] + originals
    return plan
