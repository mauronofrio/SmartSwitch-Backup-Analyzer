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
            if raw_kind != "zip":
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
