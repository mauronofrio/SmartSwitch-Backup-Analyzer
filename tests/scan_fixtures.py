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
