"""Merge the file categories of a scan into one Android storage tree."""

from __future__ import annotations

import fnmatch
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
    dated: int = 0  # placed files that got their original date (already-present ones are re-dated, not counted)
    missing: int = 0
    bad_manifests: int = 0
    leftover_partials: int = 0  # ``.ssba-*.partial`` files in out_dir, e.g. from a crashed run; never deleted


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


def _is_same_entry(a: Path, b: Path) -> bool:
    """True when ``a`` and ``b`` are the very same directory entry: the same parent
    directory and the same name (case-insensitively) -- not just the same file
    reached through a different alias (a second hard link, a junction, an 8.3
    short name, a UNC loopback path, a symlinked ancestor, ...). Path-string
    comparison (even ``resolve()``-based) cannot be trusted to tell these apart,
    since not every alias normalizes to the same string; ``os.path.samefile``
    (file-index based) can.
    """
    return os.path.samefile(a.parent, b.parent) and a.name.casefold() == b.name.casefold()


def _remove(path: Path) -> None:
    """Delete ``path``, clearing a Windows read-only bit first if that is why it failed."""
    try:
        path.unlink()
    except PermissionError:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        path.unlink()


def _new_partial_name() -> str:
    """A short, fixed-length staging name, independent of the file it will hold."""
    return f".ssba-{uuid.uuid4().hex[:8]}.partial"


def _commit(source: Path, candidate: Path, mode: str) -> bool:
    """Create ``candidate`` from ``source`` without ever truncating or overwriting it.

    Returns True once ``candidate`` holds the file; ``source`` is always left in
    place (the caller dates ``candidate`` and only then removes ``source`` in
    move mode). Returns False if ``candidate`` turned out to be taken by someone
    else between the existence check in ``_place`` and this call, so the caller
    falls through to the next candidate name.
    """
    if mode == "move":
        try:
            os.link(source, candidate)
        except FileExistsError:
            return False  # the name was taken concurrently
        except OSError:
            pass  # cross-volume, or this filesystem has no hard links: fall back below
        else:
            return True

    # Never write straight to ``candidate``, and never delete an existing file to
    # make room for staging: fill a short, randomly-named, exclusively-created
    # partial file (its name does not encode ``candidate``'s, so this can't push
    # a long filename past the filesystem's path-length limit), then commit it
    # with a no-clobber ``os.link`` (it fails instead of overwriting) followed by
    # dropping the partial name.
    partial = candidate.parent / _new_partial_name()
    created = False  # only unlink the partial below if this call is the one that
    # made it -- a name collision with an unrelated, pre-existing file must never
    # delete that file.
    try:
        with source.open("rb") as src, partial.open("xb") as dst:
            created = True
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())  # on disk before the commit (and before a move removes the source)
        # Keep the source's timestamps, as a hard-link move does. Only the times:
        # shutil.copystat would also copy a read-only bit, and a read-only partial
        # could then not be dropped after the commit on Windows.
        st = source.stat()
        os.utime(partial, ns=(st.st_atime_ns, st.st_mtime_ns))
    except BaseException:
        if created:
            try:
                partial.unlink()
            except OSError:
                pass  # never mask the original error
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
    return True


def _place(
    source: Path, target: Path, mode: str, placed_now: set[Path], mtime: float | None = None
) -> tuple[str, Path, bool]:
    """Put ``source`` at ``target`` (or a numbered free name), never overwriting.

    ``mtime`` (the original date, if known) is set on the final file right after
    the commit -- or on a file found already present -- and always before a
    move removes ``source``, so an interruption can never lose the date.

    Returns ("placed" | "conflict" | "merged" | "present", final path, whether a
    newly placed file got ``mtime``).
    """
    conflict = False
    for candidate in _candidates(target):
        if candidate.is_symlink():
            conflict = True  # a symlinked target is never followed or trusted
            continue
        if candidate.exists():
            if os.path.samefile(source, candidate):
                # Only trust this as "a hard link a previous, interrupted move left
                # behind" (its os.link succeeded, then removing the source failed or
                # the process stopped) when there really are >= 2 links to the data
                # AND source/candidate are not literally the same directory entry.
                # Path-string comparison (even resolve()-based) cannot reliably tell
                # a real self-reference apart from an alias (8.3 short name,
                # junction, UNC loopback, symlinked ancestor, ...); st_nlink can.
                # Anything else -- a single-link file, or the same entry -- means
                # out_dir resolves back onto its own source: never delete.
                if os.stat(source).st_nlink >= 2 and not _is_same_entry(source, candidate):
                    _set_mtime(candidate, mtime)  # an interrupted run may not have dated it
                    if mode == "move":
                        _remove(source)
                    return "present", candidate, False
                raise FilesExportError(
                    "the output folder must not be inside or contain a scanned "
                    f"category folder: {candidate} is {source}"
                )
            if candidate.is_file() and _identical(source, candidate):
                if candidate in placed_now:
                    status = "merged"  # dated when it was placed earlier in this run
                else:
                    status = "present"
                    _set_mtime(candidate, mtime)  # an interrupted run may not have dated it
                if mode == "move":
                    _remove(source)  # only after proving the target holds the same bytes
                return status, candidate, False
            conflict = True
            continue
        candidate.parent.mkdir(parents=True, exist_ok=True)
        if _commit(source, candidate, mode):
            placed_now.add(candidate)
            dated = _set_mtime(candidate, mtime)  # before the source is removed
            if mode == "move":
                _remove(source)  # only after the commit at ``candidate`` succeeded
            return ("conflict" if conflict else "placed"), candidate, dated
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


def _ancestors(path: Path):
    """``path`` itself, then each of its parent directories, closest first."""
    yield path
    yield from path.parents


def _check_no_overlap(scan_dir: Path, out_dir: Path, categories: list[str]) -> None:
    """Refuse an ``out_dir`` that would make a planned target equal its own source.

    Checked two ways: a nominal overlap via ``resolve()``/``is_relative_to`` (cheap,
    catches most cases without touching the filesystem), and a same-file overlap
    reached through a different spelling of the same directory -- an 8.3 short
    name, a directory junction, a symlinked ancestor, a UNC loopback path, etc. --
    via ``os.path.samefile`` along whichever side's ancestors actually exist
    (``resolve()`` does not reliably normalize every such alias away).
    """
    # Absolute paths, so the samefile ancestor walk reaches the real parents of a
    # relative path (not just ".") without depending on resolve().
    out_dir = out_dir.absolute()
    scan_dir = scan_dir.absolute()
    out_resolved = out_dir.resolve()
    out_exists = out_dir.exists()

    def overlap(cat_dir: Path, cat_resolved: Path) -> bool:
        if (
            out_resolved == cat_resolved
            or out_resolved.is_relative_to(cat_resolved)
            or cat_resolved.is_relative_to(out_resolved)
        ):
            return True
        if any(a.exists() and os.path.samefile(a, cat_dir) for a in _ancestors(out_dir)):
            return True
        return out_exists and any(os.path.samefile(a, out_dir) for a in _ancestors(cat_dir))

    for category in categories:
        cat_dir = scan_dir / category
        if overlap(cat_dir, cat_dir.resolve()):
            raise FilesExportError(
                "the output folder must not be inside or contain a scanned "
                f"category folder: {cat_dir}"
            )


def check_out_dir(scan_dir: Path, out_dir: Path) -> None:
    """Raise ``FilesExportError`` if merging into ``out_dir`` is not safe (checked
    before anything is written, e.g. by ``export all``).

    A scan without file categories (or with an unreadable report) is not an
    overlap: nothing will be merged, and ``export_files`` reports that itself.
    """
    try:
        categories = found_categories(scan_dir)
    except FilesExportError:
        return
    _check_no_overlap(scan_dir, out_dir, categories)


def _count_partials(out_dir: Path) -> int:
    count = 0
    for _, _, filenames in os.walk(out_dir):  # symlinked folders are not followed
        count += sum(fnmatch.fnmatchcase(name, ".ssba-*.partial") for name in filenames)
    return count


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
            status, _, dated = _place(item.source, target, mode, placed_now, item.mtime)
        except OSError as exc:
            raise FilesExportError(f"cannot {mode} {item.source}: {exc}") from exc
        if status in ("placed", "conflict"):
            result.placed += 1
            result.conflicts += status == "conflict"
            result.originals += item.original
            result.dated += dated
        elif status == "merged":
            result.merged += 1
        else:
            result.already_present += 1
    if mode == "move":
        for category in plan.categories:
            _remove_empty_dirs(scan_dir / category)
    result.leftover_partials = _count_partials(out_dir)
    return result
