from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from ssba.core.parsers.files import FilesExportError, found_categories, plan_files
from tests.files_fixtures import T, build_files_scan_dir, item
from tests.scan_fixtures import add_category


def _targets(plan):
    return {f.target.as_posix(): f for f in plan.files}


def test_categories_found_in_fixed_order(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    assert found_categories(scan_dir) == ["Photo", "Video", "Docs", "EtcFolder", "PHOTO_ORIGIN"]


def test_storage_files_keep_their_phone_paths_and_manifests_are_excluded(tmp_path):
    plan = plan_files(build_files_scan_dir(tmp_path / "scan"))
    storage = [f.target.as_posix() for f in plan.files if not f.original]
    assert storage == [
        "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/w.jpg",
        "DCIM/Camera/a.jpg",
        "DCIM/Camera/v.mp4",
        "Download/doc.pdf",
        "root.docx",
        "Download/doc.pdf",
        "Download/only.ics",
    ]


def test_original_dates_come_from_the_manifests_first_entry_wins(tmp_path):
    plan = plan_files(build_files_scan_dir(tmp_path / "scan"))
    dates = {f.target.as_posix(): f.mtime for f in plan.files if not f.original}
    assert dates["DCIM/Camera/a.jpg"] == T / 1000
    assert dates["Download/doc.pdf"] == (T + 1000) / 1000
    assert dates["root.docx"] == (T + 2000) / 1000
    assert dates["Download/only.ics"] == (T + 3000) / 1000
    assert dates["DCIM/Camera/v.mp4"] is None


def test_manifest_entries_without_a_file_are_counted(tmp_path):
    assert plan_files(build_files_scan_dir(tmp_path / "scan")).missing == 1


def test_unreadable_manifest_is_ignored_and_counted(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan", raw_manifests={"Video": "{not json"})
    plan = plan_files(scan_dir)
    assert plan.bad_manifests == 1
    assert "DCIM/Camera/v.mp4" in [f.target.as_posix() for f in plan.files]


def test_bad_manifest_values_are_skipped(tmp_path):
    manifests = {"Photo": [
        "not a dict",
        {"FilePath": 42, "DateModified": T},
        {"FilePath": "/elsewhere/DCIM/Camera/a.jpg", "DateModified": T},
        {"FilePath": "/mnt/sdcard/DCIM/Camera/a.jpg", "DateModified": "yesterday"},
        {"FilePath": "/mnt/sdcard/DCIM/Camera/a.jpg", "DateModified": True},
    ]}
    plan = plan_files(build_files_scan_dir(tmp_path / "scan", manifests=manifests))
    assert _targets(plan)["DCIM/Camera/a.jpg"].mtime is None
    assert (plan.missing, plan.bad_manifests) == (0, 0)


def test_manifest_matches_scanned_path_case_insensitively(tmp_path):
    # Android shared storage is case-insensitive; Smart Switch's manifest can spell a
    # folder differently than the scanned file path (real example: WhatsApp vs Whatsapp).
    scan_dir = build_files_scan_dir(
        tmp_path / "scan",
        files={"Photo": {"Pictures/Whatsapp/x.jpg": b"x"}},
        manifests={"Photo": [item("/mnt/sdcard/Pictures/WhatsApp/x.jpg", T)]},
    )
    plan = plan_files(scan_dir)
    planned = _targets(plan)["Pictures/Whatsapp/x.jpg"]
    assert planned.mtime == T / 1000
    assert plan.missing == 0


def test_originals_go_to_their_own_folder(tmp_path):
    plan = plan_files(build_files_scan_dir(tmp_path / "scan"))
    originals = [(f.target.as_posix(), f.mtime) for f in plan.files if f.original]
    # sorted by path inside the category: ".../0/flat.jpg" < ".../0/storage/..."
    assert originals == [
        ("_Edited photo originals/flat.jpg", None),
        ("_Edited photo originals/DCIM/Camera/a.jpg", None),
    ]
    assert all(isinstance(f.target, PurePosixPath) for f in plan.files)


def test_absent_categories_are_skipped(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan", files={"Music": {"Music/s.mp3": b"s"}}, manifests={})
    assert found_categories(scan_dir) == ["Music"]
    assert [f.target.as_posix() for f in plan_files(scan_dir).files] == ["Music/s.mp3"]


def test_category_in_the_report_without_its_folder_is_skipped(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan", files={"Music": {"Music/s.mp3": b"s"}}, manifests={})
    add_category(scan_dir, "Photo", [])
    assert found_categories(scan_dir) == ["Music"]


def test_no_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(FilesExportError, match="no file categories"):
        plan_files(tmp_path)


def test_missing_report_raises(tmp_path):
    with pytest.raises(FilesExportError, match="report.json"):
        found_categories(tmp_path)
