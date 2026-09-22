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

# Zip-based container formats that must always be preserved as a single,
# opaque file - never recursed into - even though sniff_kind correctly
# reports their raw (or decrypted) bytes as kind="zip". These are Office
# Open XML, legacy macro-enabled variants, OpenDocument formats, and EPUB:
# real end-user documents a phone backup might contain, where the zip
# structure is an implementation detail, not something a user wants exposed
# as a directory of exploded XML parts. Smart Switch's own wrapper
# containers (e.g. Contact.spbm, sdoc.snmm) are intentionally NOT in this
# list, since those are disposable wrappers whose useful content is what's
# inside them.
OPAQUE_ZIP_DOCUMENT_EXTENSIONS = frozenset({
    ".docx", ".docm", ".dotx", ".dotm",
    ".xlsx", ".xlsm", ".xltx", ".xltm",
    ".pptx", ".pptm", ".potx", ".potm", ".ppsx", ".ppsm",
    ".odt", ".ods", ".odp", ".odg",
    ".epub",
})


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


class _CorruptZipError(Exception):
    """Internal signal that a zip container itself couldn't be turned into
    usable output.

    This is distinct from a single bad member inside an otherwise-good zip
    (which _recurse_zip already handles correctly by recording a per-entry
    error and continuing for that member alone). Raised by _recurse_zip in
    two cases: (1) zipfile.ZipFile() fails at the whole-archive level - not
    just zipfile.BadZipFile, but any exception the parser can raise on
    malformed input (e.g. NotImplementedError for an unrecognized "version
    needed to extract" field); or (2) the zip opens and has at least one
    non-directory entry, but every single entry failed, so nothing was
    actually written anywhere for this container despite it "successfully"
    recursing. Either way, _process catches it *before* deciding whether to
    write the container's own bytes - avoiding both silent data loss
    (nothing written) and duplicate/contradictory results (one FileResult
    from _process, a second from _recurse_zip) for the same path.
    """


def _sanitize_entry_name(name: str) -> str | None:
    """Sanitize a zip-entry (or filesystem-walk) name before it becomes part
    of an output path.

    Zip entry names are attacker- or corruption-controllable (a hostile or
    malformed archive can contain "../../etc/passwd"-style entries), so this
    is the single choke point where a raw name is turned into something safe
    to join under an out_dir.

    Policy (documented choice - "skip the segment" rather than "reject the
    whole entry"): normalize backslashes to forward slashes, drop a leading
    Windows drive-letter prefix if present, then drop "." and ".." segments
    outright. So "../../../PWNED.txt" becomes "PWNED.txt" instead of being
    rejected wholesale. If nothing safe remains (e.g. the name was just ".."
    or "/"), return None so the caller can treat the entry as an error
    instead of writing anywhere.
    """
    normalized = name.replace("\\", "/")
    if len(normalized) >= 2 and normalized[1] == ":" and normalized[0].isalpha():
        normalized = normalized[2:]  # drop a "C:" style drive prefix
    parts = [segment for segment in normalized.split("/") if segment not in ("", ".", "..")]
    if not parts:
        return None
    return "/".join(parts)


def _is_opaque_zip_document(name: str) -> bool:
    """True if `name`'s extension marks it as a zip-based document format
    that must be preserved as a single file rather than recursed into (see
    OPAQUE_ZIP_DOCUMENT_EXTENSIONS). Extension matching is case-insensitive
    and looks only at the final path segment, so it works whether `name` is
    a plain filename or a zip entry path using "/" or "\\" separators.
    """
    normalized = name.replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    _, _, ext = basename.rpartition(".")
    if not ext or "." not in basename:
        return False
    return f".{ext.lower()}" in OPAQUE_ZIP_DOCUMENT_EXTENSIONS


def _write_output(out_dir: Path, rel_path: str, data: bytes) -> None:
    out_path = out_dir / rel_path
    # Defense in depth: even though rel_path is built from sanitized names,
    # assert the final path is still under out_dir before writing anything.
    resolved_root = out_dir.resolve()
    resolved_path = out_path.resolve()
    if resolved_root != resolved_path and resolved_root not in resolved_path.parents:
        raise ValueError(f"refusing to write outside output directory: {rel_path!r}")
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
    safe_name = _sanitize_entry_name(name)
    if safe_name is None:
        results.append(
            FileResult(f"{rel_prefix}{name}", "error", detail="unsafe entry name rejected")
        )
        return
    rel_path = f"{rel_prefix}{safe_name}"
    try:
        raw_kind = sniff_kind(raw)
        if raw_kind != "binary":
            if raw_kind == "zip" and not _is_opaque_zip_document(name):
                try:
                    _recurse_zip(raw, key, out_dir, rel_path + "/", results)
                except _CorruptZipError as exc:
                    _write_output(out_dir, rel_path, raw)
                    results.append(
                        FileResult(rel_path, "error", kind=raw_kind, detail=f"corrupt zip: {exc}")
                    )
                    return
                results.append(FileResult(rel_path, "plaintext_passthrough", kind=raw_kind))
                return
            _write_output(out_dir, rel_path, raw)
            results.append(FileResult(rel_path, "plaintext_passthrough", kind=raw_kind))
            return

        try:
            blob = decrypt_file(raw, key)
        except ValueError as exc:
            _write_output(out_dir, rel_path, raw)
            results.append(FileResult(rel_path, "undecoded", detail=str(exc)))
            return

        if blob.kind == "binary":
            _write_output(out_dir, rel_path, raw)
            results.append(
                FileResult(
                    rel_path, "undecoded", detail="decrypted output still unrecognized"
                )
            )
            return

        if blob.kind == "zip" and not _is_opaque_zip_document(name):
            try:
                _recurse_zip(blob.data, key, out_dir, rel_path + "/", results)
            except _CorruptZipError as exc:
                _write_output(out_dir, rel_path, blob.data)
                results.append(
                    FileResult(rel_path, "error", kind=blob.kind, detail=f"corrupt zip: {exc}")
                )
                return
            results.append(FileResult(rel_path, "decrypted", kind=blob.kind))
            return

        _write_output(out_dir, rel_path, blob.data)
        results.append(FileResult(rel_path, "decrypted", kind=blob.kind))
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
    except Exception as exc:  # noqa: BLE001 - opening a zip from bytes we
        # don't control (attacker- or corruption-influenced input) is
        # exactly the kind of boundary where a broad catch is appropriate:
        # zipfile.ZipFile() can fail with BadZipFile for a malformed
        # central directory, but also with other exceptions such as
        # NotImplementedError for a mangled "version needed to extract"
        # field. All of these mean the same thing to us - "this isn't a
        # zip we can recurse into" - so let the caller (_process) decide
        # what to write and record, instead of appending our own
        # FileResult here.
        raise _CorruptZipError(f"{type(exc).__name__}: {exc}") from exc
    had_entries = False
    any_entry_succeeded = False
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            had_entries = True
            try:
                raw = zf.read(info)
            except Exception as exc:  # noqa: BLE001 - per-file isolation
                results.append(
                    FileResult(
                        rel_prefix + info.filename,
                        "error",
                        detail=f"failed to read zip entry: {type(exc).__name__}: {exc}",
                    )
                )
                continue
            _process(info.filename, raw, key, out_dir, rel_prefix, results)
            # _process always appends exactly one FileResult for this
            # entry's own path as the last thing it does (any results from
            # further recursion into a nested zip are appended before it),
            # so the most recently appended result reflects this entry's
            # own outcome.
            if results[-1].status != "error":
                any_entry_succeeded = True

    if had_entries and not any_entry_succeeded:
        # The zip opened fine, but every single entry inside it failed
        # (e.g. an unsupported compression method) - the per-entry
        # try/except above already isolated each failure as its own
        # FileResult, but that leaves nothing at all written for this
        # zip's own path, which would otherwise still be reported a
        # success ("plaintext_passthrough"/"decrypted") by the caller.
        # Signal the same "corrupt/unsupported zip" failure used for a
        # whole-archive open failure, so _process falls back to writing
        # the container's own raw bytes and records a single error result
        # for the container's own path.
        raise _CorruptZipError("no entries could be extracted from this zip")


def scan_category(
    backup_root: Path, category: str, key: bytes, out_dir: Path
) -> CategoryResult:
    category_dir = backup_root / category
    result = CategoryResult(category=category)
    if not category_dir.is_dir():
        return result
    category_out_dir = out_dir / category
    for entry in sorted(p for p in category_dir.rglob("*") if p.is_file()):
        rel_name = entry.relative_to(category_dir).as_posix()
        try:
            raw = entry.read_bytes()
        except OSError as exc:
            result.files.append(
                FileResult(
                    rel_name,
                    "error",
                    detail=f"failed to read source file: {type(exc).__name__}: {exc}",
                )
            )
            continue
        _process(rel_name, raw, key, category_out_dir, "", result.files)
    return result


def scan_backup(
    backup_root: Path, out_dir: Path, categories: list[str] | None = None
) -> BackupReport:
    session_dummy = get_session_dummy(backup_root)
    key = derive_key(session_dummy)
    report = BackupReport()
    selected = list_categories(backup_root)
    if categories is not None:
        wanted = set(categories)
        selected = [c for c in selected if c in wanted]
    for category in selected:
        report.categories.append(scan_category(backup_root, category, key, out_dir))
    return report
