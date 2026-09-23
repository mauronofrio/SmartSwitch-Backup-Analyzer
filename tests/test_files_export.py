from __future__ import annotations

import os

import pytest

from ssba.core.parsers.files import export_files
from tests.files_fixtures import FILES, T, build_files_scan_dir

TREE = sorted([
    "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/w.jpg",
    "DCIM/Camera/a.jpg",
    "DCIM/Camera/v.mp4",
    "Download/doc.pdf",
    "Download/only.ics",
    "root.docx",
    "_Edited photo originals/DCIM/Camera/a.jpg",
    "_Edited photo originals/flat.jpg",
])


def _tree(out):
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())


def _export(tmp_path, mode, **kwargs):
    scan_dir = build_files_scan_dir(tmp_path / "scan", **kwargs)
    out = tmp_path / "out"
    return scan_dir, out, export_files(scan_dir, out, mode)


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_files_form_one_android_tree(tmp_path, mode):
    _, out, result = _export(tmp_path, mode)
    assert _tree(out) == TREE
    assert (out / "DCIM/Camera/a.jpg").read_bytes() == b"photo-a"
    assert (out / "_Edited photo originals/DCIM/Camera/a.jpg").read_bytes() == b"original-a"
    assert (result.placed, result.merged, result.conflicts, result.originals) == (8, 1, 0, 2)
    assert (result.dated, result.missing, result.bad_manifests, result.already_present) == (4, 1, 0, 0)


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_files_get_their_original_dates(tmp_path, mode):
    _, out, _ = _export(tmp_path, mode)
    assert abs(os.path.getmtime(out / "DCIM/Camera/a.jpg") - T / 1000) < 1
    assert abs(os.path.getmtime(out / "Download/doc.pdf") - (T + 1000) / 1000) < 1


def test_copy_keeps_the_category_folders(tmp_path):
    scan_dir, _, _ = _export(tmp_path, "copy")
    for category, files in FILES.items():
        for rel, data in files.items():
            assert (scan_dir / category / rel).read_bytes() == data


def test_move_empties_the_category_folders(tmp_path):
    scan_dir, _, _ = _export(tmp_path, "move")
    for category, files in FILES.items():
        for rel in files:
            assert not (scan_dir / category / rel).exists()
    assert not (scan_dir / "Video").exists()
    assert not (scan_dir / "PHOTO_ORIGIN").exists()
    assert (scan_dir / "Photo").is_dir()  # still holds its Smart Switch file list
    assert not (scan_dir / "Photo" / "DCIM").exists()


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_same_path_with_different_content_is_kept_as_a_numbered_copy(tmp_path, mode):
    files = {**FILES, "EtcFolder": {"Download/doc.pdf": b"other", "Download/only.ics": b"ics"}}
    _, out, result = _export(tmp_path, mode, files=files)
    assert (out / "Download/doc.pdf").read_bytes() == b"pdf"
    assert (out / "Download/doc (2).pdf").read_bytes() == b"other"
    assert (result.conflicts, result.merged, result.placed) == (1, 0, 9)


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_existing_output_files_are_never_overwritten(tmp_path, mode):
    out = tmp_path / "out"
    (out / "DCIM/Camera").mkdir(parents=True)
    (out / "DCIM/Camera/a.jpg").write_bytes(b"mine")
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    result = export_files(scan_dir, out, mode)
    assert (out / "DCIM/Camera/a.jpg").read_bytes() == b"mine"
    assert (out / "DCIM/Camera/a (2).jpg").read_bytes() == b"photo-a"
    assert result.conflicts == 1


def test_copy_rerun_writes_nothing_new(tmp_path):
    scan_dir, out, _ = _export(tmp_path, "copy")
    again = export_files(scan_dir, out, "copy")
    assert (again.placed, again.already_present, again.merged) == (0, 9, 0)
    assert _tree(out) == TREE


def test_move_deletes_a_duplicate_source_only_after_the_identity_check(tmp_path):
    scan_dir, out, result = _export(tmp_path, "move")
    assert result.merged == 1
    assert not (scan_dir / "EtcFolder/Download/doc.pdf").exists()
    assert (out / "Download/doc.pdf").read_bytes() == b"pdf"


def test_unknown_mode_raises(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    with pytest.raises(ValueError, match="mode"):
        export_files(scan_dir, tmp_path / "out", "none")
