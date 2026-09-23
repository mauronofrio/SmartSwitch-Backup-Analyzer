"""Merge the file categories of a scan into one Android storage tree."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
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


def _same_path(a: Path, b: Path) -> bool:
    """True only when ``a`` and ``b`` name the very same path (not just the same file)."""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _remove(path: Path) -> None:
    """Delete ``path``, clearing a Windows read-only bit first if that is why it failed."""
    try:
        path.unlink()
    except PermissionError:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        path.unlink()


def _commit(source: Path, candidate: Path, mode: str) -> bool:
    """Create ``candidate`` from ``source`` without ever truncating or overwriting it.

    Returns True once ``candidate`` holds the file (``source`` is gone, in move
    mode). Returns False if ``candidate`` turned out to be taken by someone else
    between the existence check in ``_place`` and this call, so the caller falls
    through to the next candidate name.
    """
    if mode == "move":
        try:
            os.link(source, candidate)
        except FileExistsError:
            return False  # the name was taken concurrently
        except OSError:
            pass  # cross-volume, or this filesystem has no hard links: fall back below
        else:
            _remove(source)  # only after the link at ``candidate`` succeeded
            return True

    # Never write straight to ``candidate``, and never delete an existing file to
    # make room for staging: fill a uniquely-named, exclusively-created partial
    # file, then commit it with a no-clobber ``os.link`` (it fails instead of
    # overwriting) followed by dropping the partial name.
    partial = candidate.with_name(f".{candidate.name}.{uuid.uuid4().hex}.ssba-partial")
    try:
        with source.open("rb") as src, partial.open("xb") as dst:
            shutil.copyfileobj(src, dst)
    except BaseException:
        if partial.exists():
            partial.unlink()
        raise
    try:
        os.link(partial, candidate)
    except FileExistsError:
        partial.unlink()
        return False  # the name was taken concurrently
    except OSError:
        if candidate.exists() or candidate.is_symlink():
            partial.unlink()
            return False  # taken concurrently, and this filesystem has no hard links
        try:
            os.rename(partial, candidate)  # no hard-link support, but the name looked free
        except FileExistsError:
            # Windows raises here when the name was claimed in between; treat it like
            # any other taken name. POSIX's os.rename instead silently replaces an
            # existing file, so on a POSIX filesystem with no hard-link support a
            # narrow race remains: a file created at this exact instant can still be
            # overwritten. Hard links (the normal path above) do not have this gap.
            partial.unlink()
            return False  # the name was taken concurrently
    else:
        partial.unlink()
    if mode == "move":
        _remove(source)  # only after the commit at ``candidate`` succeeded
    return True


def _place(source: Path, target: Path, mode: str, placed_now: set[Path]) -> tuple[str, Path]:
    """Put ``source`` at ``target`` (or a numbered free name), never overwriting.

    Returns ("placed" | "conflict" | "merged" | "present", final path).
    """
    conflict = False
    for candidate in _candidates(target):
        if candidate.is_symlink():
            conflict = True  # a symlinked target is never followed or trusted
            continue
        if candidate.exists():
            if os.path.samefile(source, candidate):
                if _same_path(source, candidate):
                    raise FilesExportError(
                        "the output folder must not be inside or contain a scanned "
                        f"category folder: {candidate} is {source}"
                    )
                # Same bytes, different names: a hard link a previous, interrupted
                # move left behind (os.link succeeded, then removing the source
                # failed or the process stopped). The data is already safe at
                # ``candidate``; just finish cleaning up the source in move mode.
                if mode == "move":
                    _remove(source)
                return "present", candidate
            if candidate.is_file() and _identical(source, candidate):
                if mode == "move":
                    _remove(source)  # only after proving the target holds the same bytes
                return ("merged" if candidate in placed_now else "present"), candidate
            conflict = True
            continue
        candidate.parent.mkdir(parents=True, exist_ok=True)
        if _commit(source, candidate, mode):
            placed_now.add(candidate)
            return ("conflict" if conflict else "placed"), candidate
        conflict = True  # taken by someone else since the existence check above
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


def _check_no_overlap(scan_dir: Path, out_dir: Path, categories: list[str]) -> None:
    """Refuse an ``out_dir`` that would make a planned target equal its own source."""
    out_resolved = out_dir.resolve()
    for category in categories:
        cat_resolved = (scan_dir / category).resolve()
        if (
            out_resolved == cat_resolved
            or out_resolved.is_relative_to(cat_resolved)
            or cat_resolved.is_relative_to(out_resolved)
        ):
            raise FilesExportError(
                "the output folder must not be inside or contain a scanned "
                f"category folder: {cat_resolved}"
            )


def export_files(scan_dir: Path, out_dir: Path, mode: str) -> FilesExportResult:
    if mode not in ("copy", "move"):
        raise ValueError(f"unknown mode {mode!r}: expected 'copy' or 'move'")
    plan = plan_files(scan_dir)
    _check_no_overlap(scan_dir, out_dir, plan.categories)
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
