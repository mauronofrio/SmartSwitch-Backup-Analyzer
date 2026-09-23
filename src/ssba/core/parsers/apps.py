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
