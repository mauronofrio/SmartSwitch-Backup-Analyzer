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
