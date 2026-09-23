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
