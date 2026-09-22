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

# Extensions that must NEVER be recursed into, full stop - independent of
# content sniffing and independent of the container catalog below. Android
# application/library packages are zip containers, but unpacking them is
# never useful output for this tool and the project owner was explicit
# these should stay opaque regardless of where they turn up in a backup.
NEVER_RECURSE_EXTENSIONS = frozenset({".apk", ".jar"})

# OpenDocument formats' mimetype prefix/value, read from a zip's root-level
# "mimetype" entry (see _is_zip_shaped_document below).
_ODF_MIMETYPE_PREFIX = b"application/vnd.oasis.opendocument."
_EPUB_MIMETYPE = b"application/epub+zip"

# A real ODF/EPUB "mimetype" entry is a small, fixed string well under 64
# bytes - there is never a legitimate reason to read more than this many
# bytes of it. Used to bound both the declared-size pre-check and the
# actual read in _is_recognized_mimetype_entry, so a crafted zip can't
# force a large decompression just by being peeked at (see that
# function's docstring).
_MIMETYPE_PEEK_LIMIT = 256

# Smart Switch's own internal wrapper containers, reverse-engineered by
# hand against a real backup (see docs/superpowers/specs/
# 2026-09-22-core-decrypt-engine-design.md, Background section, for how
# each of these was identified). These are Smart Switch's own packaging,
# not the user's files, and must be opened to reach real recoverable data.
#
# Anything NOT recognized by this catalog, by KNOWN_SMART_SWITCH_EXTENSIONS,
# or by the category-name wrapper pattern (see _is_known_smart_switch_container)
# defaults to "preserve as-is, don't unpack" - the safe choice for content
# we don't have specific, verified knowledge about. This replaces an
# earlier, more general "category is flat vs has subdirectories"
# structural heuristic: that approach was reconsidered as too fragile (it
# had a real edge case around SAMSUNGNOTE's own SmartSwitchRestoreDB/
# subdirectory appearing mid-recursion) in favor of this small, explicit,
# hand-verified list.
#
# CALLLOG.zip is kept here even though it's also subsumed by the general
# category-name wrapper pattern below (it lives under a category literally
# named CALLLOG in every real backup) - purely so it keeps being recognized
# under the arbitrarily-named test categories the existing test suite uses
# it under as a stand-in "known container" filename. No functional
# difference for real backups either way.
KNOWN_SMART_SWITCH_CONTAINERS = frozenset({
    "sdoc.snmm",       # SAMSUNGNOTE: outer wrapper, contains sdoc.bk and small metadata files
    "sdoc.bk",         # SAMSUNGNOTE: the actual encrypted note database + note packages
    "Contact.spbm",    # CONTACT: outer wrapper, contains Contact.bk
    "Contact.bk",      # CONTACT: the actual encrypted contact database (-> profile.vcf etc.)
    "CALLLOG.zip",     # CALLLOG: outer wrapper, contains call_log.exml
})

# Known Smart Switch internal container EXTENSIONS, as opposed to the
# exact-filename catalog above. .sdocx is SAMSUNGNOTE's own per-note
# package format (one b_<id>.sdocx per note, inside sdoc.bk) - the id
# varies per note, so these can't be exact-name catalogued the way
# sdoc.snmm/sdoc.bk can. This is still safe to recurse unconditionally:
# .sdocx is a proprietary Samsung Notes internal extension, never a
# format a real end user would create themselves (unlike a generic
# .zip), so there's no risk of exploding a user's own file here.
KNOWN_SMART_SWITCH_EXTENSIONS = frozenset({".sdocx"})


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


def _basename(name: str) -> str:
    """Final path segment of `name`, whether it's a plain filename or a zip
    entry path using "/" or "\\" separators.
    """
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def _extension(basename: str) -> str | None:
    """The lowercased, dot-prefixed final extension of `basename` (e.g.
    ".sdocx"), or None if `basename` has no "." at all.

    Deliberately NOT implemented with str.rpartition("."): rpartition
    returns ("", "", basename) - not empty pieces - when the separator
    isn't present at all, so a dotless name like "sdocx" would otherwise
    be misread as having extension "sdocx" (its rpartition "after" piece
    equals the whole string). This explicit "." in basename check is the
    fix for that.
    """
    if "." not in basename:
        return None
    return f".{basename.rsplit('.', 1)[1].lower()}"


def _stem(basename: str) -> str:
    """`basename` with its final extension (if any) stripped. A dotless
    name is returned unchanged (there's nothing to strip).
    """
    if "." not in basename:
        return basename
    return basename.rsplit(".", 1)[0]


def _has_never_recurse_extension(name: str) -> bool:
    """True if `name` ends in an extension from NEVER_RECURSE_EXTENSIONS
    (currently .apk/.jar), case-insensitive. This is an explicit backstop
    that wins regardless of content or category shape.
    """
    basename = _basename(name).lower()
    return any(basename.endswith(ext) for ext in NEVER_RECURSE_EXTENSIONS)


def _is_zip_shaped_document(data: bytes) -> bool:
    """Peek inside zip-shaped bytes - without extracting anything - to
    decide by CONTENT (not by the file's own name/extension) whether this
    is an Office Open XML document (docx/xlsx/pptx/... - identified by a
    root-level "[Content_Types].xml" entry, which every valid OOXML zip
    has) or an OpenDocument/EPUB document (identified by a root-level
    "mimetype" entry whose bytes start with "application/vnd.oasis.
    opendocument." or equal "application/epub+zip" exactly). Either way,
    the file must be preserved as a single opaque file, never recursed
    into.

    This exists because a file's extension can lie: real files were found
    in the wild with a .pdf extension whose actual content was a
    PowerPoint or Word document. Extension matching can't catch that -
    content sniffing can, and it works regardless of what the file is
    named.

    If the zip can't even be opened here, this returns False ("not a
    recognized document by content") rather than raising - this is a
    cheap, best-effort additional signal layered before the real
    recursion attempt, not a replacement for the existing corrupt-zip
    handling (_CorruptZipError etc.) that already runs when a genuinely
    malformed zip is actually recursed into.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "[Content_Types].xml" in names:
                return True
            if "mimetype" in names:
                return _is_recognized_mimetype_entry(zf)
    except Exception:
        return False
    return False


def _is_recognized_mimetype_entry(zf: zipfile.ZipFile) -> bool:
    """Bounded peek at an already-open zip's root "mimetype" entry, used by
    _is_zip_shaped_document to recognize ODF/EPUB content.

    This peek runs on every zip-shaped file the scanner encounters, even
    ones that end up not being recursed - so it must never fully
    decompress an attacker-controlled entry. A naive `zf.read("mimetype")`
    does exactly that: it decompresses the whole entry into memory before
    any comparison happens, which is a real memory-exhaustion vector for
    what's supposed to be a cheap peek (a crafted zip well under 100KB can
    carry a "mimetype" entry that deflates to tens of megabytes or more).
    A real ODF/EPUB mimetype value is always small and fixed (see
    _MIMETYPE_PEEK_LIMIT), so there's no legitimate reason to ever need
    more than that many bytes.

    Two layers of bounding, both against _MIMETYPE_PEEK_LIMIT:
    1. A cheap check of the entry's declared (central-directory)
       file_size, to reject an obviously-oversized entry without opening
       it at all.
    2. Even if that declared size were somehow wrong, the actual read
       goes through zf.open("mimetype").read(N) rather than zf.read(...):
       ZipExtFile.read(n) decompresses incrementally and stops once n
       bytes have been produced, regardless of what the entry's header
       claims - so this stays bounded independent of the size check.
    """
    try:
        info = zf.getinfo("mimetype")
    except KeyError:
        return False
    if info.file_size > _MIMETYPE_PEEK_LIMIT:
        return False
    try:
        with zf.open("mimetype") as fh:
            mimetype = fh.read(_MIMETYPE_PEEK_LIMIT)
    except Exception:
        return False
    mimetype = mimetype.strip()
    return mimetype.startswith(_ODF_MIMETYPE_PREFIX) or mimetype == _EPUB_MIMETYPE


def _is_known_smart_switch_container(name: str, category: str) -> bool:
    """True if `name` is recognized as one of Smart Switch's own internal
    wrapper containers, by any of three distinct mechanisms:

    - Exact filename match against KNOWN_SMART_SWITCH_CONTAINERS,
      case-sensitive: a handful of specific, individually hand-verified
      Smart-Switch-generated names (fixed names, not user-supplied ones,
      so case-sensitivity is correct here - unlike the document-extension
      case below, which needs case-insensitivity because users and apps
      produce inconsistently-cased filenames).
    - Extension match against KNOWN_SMART_SWITCH_EXTENSIONS,
      case-insensitive: a whole proprietary-extension family (currently
      just .sdocx) where the filenames themselves vary per instance (e.g.
      a note id) and can't be exact-name catalogued, but the extension
      alone is enough to know it's Smart Switch's own internal packaging.
    - Category-name wrapper pattern: `name`'s basename, with its
      extension stripped, exactly matches `category`. This is the general
      form of a pattern CALLLOG.zip (under category CALLLOG) is one
      hand-verified instance of - Smart Switch stores roughly 90
      categories' payload in a wrapper file named identically to the
      category folder itself (e.g. WIFICONFIG/WIFICONFIG.zip,
      SBROWSER/SBROWSER.zip, HOMESCREEN/HOMESCREEN.zip - verified against
      this repo's own earlier real-scan output). Rather than hardcode
      every one of those ~90 names, this recognizes the pattern
      generally. Matching is exact/case-sensitive, like the exact-name
      catalog (both the category folder and its wrapper file are
      Smart-Switch-generated). This only looks at the file's own
      basename, not its nesting depth, so it applies at any recursion
      depth reached while scanning a category - `category` is threaded
      down unchanged regardless of how deep the recursion goes.
    """
    basename = _basename(name)
    if basename in KNOWN_SMART_SWITCH_CONTAINERS:
        return True
    ext = _extension(basename)
    if ext is not None and ext in KNOWN_SMART_SWITCH_EXTENSIONS:
        return True
    return _stem(basename) == category


def _should_recurse_into_zip(name: str, data: bytes, category: str) -> bool:
    """Decide whether zip-shaped content (raw-already-zip, or
    successfully-decrypted-to-zip) should be recursed into, combining the
    three detection mechanisms in order:

    1. .apk/.jar backstop - always wins, never recurse, regardless of
       everything else.
    2. Content-based document detection - always wins if matched (OOXML /
       ODF / EPUB), never recurse, regardless of the file's name.
    3. Known Smart Switch container recognition
       (_is_known_smart_switch_container) - only consulted if neither of
       the above matched: recurse if `name` is in the small, hand-verified
       exact-name catalog (KNOWN_SMART_SWITCH_CONTAINERS), OR its
       extension is in KNOWN_SMART_SWITCH_EXTENSIONS (currently .sdocx),
       OR its name (minus extension) matches the category it's being
       scanned under (the general "<CATEGORY>/<CATEGORY>.zip"-shaped
       wrapper pattern). Everything else - unknown zips, the user's own
       plain .zip files, anything not specifically recognized - is
       preserved as a single file, never recursed into. This is a
       deliberately conservative default: only unwrap what has been
       specifically verified (by exact name, extension family, or the
       category-name pattern) to need unwrapping.
    """
    if _has_never_recurse_extension(name):
        return False
    if _is_zip_shaped_document(data):
        return False
    return _is_known_smart_switch_container(name, category)


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
    category: str,
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
            if raw_kind == "zip" and _should_recurse_into_zip(name, raw, category):
                try:
                    _recurse_zip(raw, key, out_dir, rel_path + "/", results, category)
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

        if blob.kind == "zip" and _should_recurse_into_zip(name, blob.data, category):
            try:
                _recurse_zip(blob.data, key, out_dir, rel_path + "/", results, category)
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
    category: str,
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
            _process(info.filename, raw, key, out_dir, rel_prefix, results, category)
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
        _process(rel_name, raw, key, category_out_dir, "", result.files, category)
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
