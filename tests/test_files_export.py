from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest

from ssba.core.parsers.files import FilesExportError, export_files
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


def _assert_sources_untouched(scan_dir):
    for category, files in FILES.items():
        for rel, data in files.items():
            assert (scan_dir / category / rel).read_bytes() == data


def test_output_folder_matching_a_category_folder_is_rejected(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    with pytest.raises(FilesExportError, match="output folder"):
        export_files(scan_dir, scan_dir / "Photo", "move")
    _assert_sources_untouched(scan_dir)


def test_output_folder_inside_a_category_folder_is_rejected(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    with pytest.raises(FilesExportError, match="output folder"):
        export_files(scan_dir, scan_dir / "EtcFolder" / "sub", "move")
    _assert_sources_untouched(scan_dir)


def test_output_folder_containing_the_category_folders_is_rejected(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    with pytest.raises(FilesExportError, match="output folder"):
        export_files(scan_dir, scan_dir, "move")
    _assert_sources_untouched(scan_dir)


def test_same_size_but_different_content_is_kept_as_a_numbered_copy_in_move_mode(tmp_path):
    # "pdf" and "xyz" are the same length but differ byte for byte.
    files = {**FILES, "EtcFolder": {"Download/doc.pdf": b"xyz", "Download/only.ics": b"ics"}}
    scan_dir, out, result = _export(tmp_path, "move", files=files)
    assert (out / "Download/doc.pdf").read_bytes() == b"pdf"
    assert (out / "Download/doc (2).pdf").read_bytes() == b"xyz"
    assert result.conflicts == 1
    assert not (scan_dir / "EtcFolder/Download/doc.pdf").exists()


def test_an_interrupted_copy_leaves_no_file_at_the_final_name(tmp_path, monkeypatch):
    # Staging fills a uniquely-named partial via shutil.copyfileobj on manually
    # opened handles, so the interruption is simulated at that level.
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    out = tmp_path / "out"
    real_copyfileobj = shutil.copyfileobj

    def flaky_copyfileobj(fsrc, fdst, length=1024 * 1024):
        if "a.jpg" in Path(fdst.name).name:
            fdst.write(b"x")  # a truncated write, then the failure
            raise OSError("simulated interruption")
        return real_copyfileobj(fsrc, fdst, length)

    monkeypatch.setattr(shutil, "copyfileobj", flaky_copyfileobj)
    with pytest.raises(FilesExportError):
        export_files(scan_dir, out, "copy")
    assert not (out / "DCIM/Camera/a.jpg").exists()
    assert (scan_dir / "Photo/DCIM/Camera/a.jpg").exists()
    assert not list(out.rglob("*ssba-partial*"))  # cleaned up after the failed fill

    monkeypatch.setattr(shutil, "copyfileobj", real_copyfileobj)
    export_files(scan_dir, out, "copy")
    assert (out / "DCIM/Camera/a.jpg").read_bytes() == b"photo-a"
    assert not (out / "DCIM/Camera/a (2).jpg").exists()


def test_a_target_created_by_someone_else_is_not_overwritten(tmp_path, monkeypatch):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    out = tmp_path / "out"
    real_link = os.link
    fired = []

    def racy_link(src, dst, *a, **kw):
        if not fired and Path(dst).name == "a.jpg":
            fired.append(True)
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            Path(dst).write_bytes(b"someone else")
            raise FileExistsError()
        return real_link(src, dst, *a, **kw)

    monkeypatch.setattr(os, "link", racy_link)
    export_files(scan_dir, out, "copy")
    assert (out / "DCIM/Camera/a.jpg").read_bytes() == b"someone else"
    assert (out / "DCIM/Camera/a (2).jpg").read_bytes() == b"photo-a"


def test_a_symlinked_target_is_treated_as_occupied(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    out = tmp_path / "out"
    link_dir = out / "DCIM" / "Camera"
    link_dir.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere.jpg"
    elsewhere.write_bytes(b"elsewhere")
    try:
        (link_dir / "a.jpg").symlink_to(elsewhere)
    except OSError:
        pytest.skip("cannot create symlinks in this environment")

    export_files(scan_dir, out, "copy")
    assert (link_dir / "a.jpg").is_symlink()
    assert elsewhere.read_bytes() == b"elsewhere"  # the symlink's target was left alone
    assert (link_dir / "a (2).jpg").read_bytes() == b"photo-a"


def test_a_read_only_source_is_still_moved(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    out = tmp_path / "out"
    src = scan_dir / "Photo/DCIM/Camera/a.jpg"
    os.chmod(src, stat.S_IREAD)
    try:
        export_files(scan_dir, out, "move")
    finally:
        if src.exists():  # keep tmp_path cleanup from tripping over a read-only leftover
            os.chmod(src, stat.S_IWRITE | stat.S_IREAD)
    assert not src.exists()
    assert (out / "DCIM/Camera/a.jpg").read_bytes() == b"photo-a"


@pytest.mark.parametrize("mode", ["move", "copy"])
def test_a_hard_link_left_by_an_interrupted_move_resumes_cleanly(tmp_path, mode):
    # os.link(source, target) can succeed and then the source removal fail (or the
    # process can stop) before a move finishes: source and target become two names
    # for the same file. A later run must recognize this as already-placed, not as
    # the output folder overlapping a category (samefile is true, but the paths
    # differ from a real self-reference).
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    out = tmp_path / "out"
    src = scan_dir / "Photo/DCIM/Camera/a.jpg"
    target = out / "DCIM/Camera/a.jpg"
    target.parent.mkdir(parents=True)
    os.link(src, target)

    result = export_files(scan_dir, out, mode)
    assert target.read_bytes() == b"photo-a"
    assert result.already_present == 1
    if mode == "move":
        assert not src.exists()
    else:
        assert src.exists()


def test_an_existing_partial_named_file_is_left_alone(tmp_path):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    out = tmp_path / "out"
    stray = out / "DCIM/Camera/a.jpg.ssba-partial"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"do not touch")

    export_files(scan_dir, out, "copy")
    assert stray.read_bytes() == b"do not touch"
    assert (out / "DCIM/Camera/a.jpg").read_bytes() == b"photo-a"


def test_a_rename_collision_in_the_no_hard_link_fallback_tries_the_next_name(tmp_path, monkeypatch):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    out = tmp_path / "out"
    real_link = os.link
    real_rename = os.rename
    fired = []

    def no_hardlink_for_a_jpg(src, dst, *a, **kw):
        if Path(dst).name in ("a.jpg", "a (2).jpg"):
            raise OSError("no hard links")
        return real_link(src, dst, *a, **kw)

    def racy_rename(src, dst, *a, **kw):
        if not fired and Path(dst).name == "a.jpg":
            fired.append(True)
            raise FileExistsError()
        return real_rename(src, dst, *a, **kw)

    monkeypatch.setattr(os, "link", no_hardlink_for_a_jpg)
    monkeypatch.setattr(os, "rename", racy_rename)
    export_files(scan_dir, out, "copy")

    assert not (out / "DCIM/Camera/a.jpg").exists()
    assert (out / "DCIM/Camera/a (2).jpg").read_bytes() == b"photo-a"
    assert not list(out.rglob("*ssba-partial*"))
