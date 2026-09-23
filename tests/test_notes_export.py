from __future__ import annotations

import os

import pytest

from ssba.core.parsers.html_page import format_time
from ssba.core.parsers.notes import NotesExportError, export_notes, safe_name
from tests.notes_fixtures import JPEG, PDF, PNG, T0, UNCAT, build_notes_scan_dir

PREVIEW = "Only a preview of this note's text was kept; it may be cut short."
TRASHED = "Deleted note from the Samsung Notes trash; its file is not in the backup."


def _export(tmp_path, **kwargs):
    out = tmp_path / "notes"
    result = export_notes(build_notes_scan_dir(tmp_path / "scan", **kwargs), out)
    return result, out


def _files(out):
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())


def test_every_note_becomes_files_in_its_folder(tmp_path):
    _, out = _export(tmp_path)
    untitled = f"Untitled {format_time((T0 + 13000) / 1000)[:10]}"
    assert _files(out) == sorted([
        "Uncategorized/Lista spesa.txt",
        "Uncategorized/Solo anteprima.txt",
        "Lavoro/Contratto.pdf",
        "Lavoro/Progetti/Verbale.txt",
        "Lavoro/Progetti/Verbale.jpg",
        "Lavoro/Progetti/Verbale_2.png",
        "Old notebooks/Quaderno 2019/Schizzo.txt",
        "Trash/Vecchia.txt",
        f"Trash/{untitled}.txt",
    ])


def test_text_files_hold_the_full_text(tmp_path):
    _, out = _export(tmp_path)
    assert (out / "Uncategorized/Lista spesa.txt").read_bytes() == b"Latte\nPane\nUova\n"
    assert (out / "Lavoro/Progetti/Verbale.txt").read_bytes() == b"Riunione\ncompleta\n"


def test_placeholders_and_headers(tmp_path):
    _, out = _export(tmp_path)
    read = lambda rel: (out / rel).read_text(encoding="utf-8")
    assert read("Old notebooks/Quaderno 2019/Schizzo.txt") == (
        "(This note contains only handwriting or drawings, which cannot be exported.)\n"
    )
    assert read("Uncategorized/Solo anteprima.txt") == f"{PREVIEW}\n\nAnteprima tronc\n"
    assert read("Trash/Vecchia.txt") == (
        f"{TRASHED}\nCreated: {format_time((T0 + 11000) / 1000)}\n"
        f"Modified: {format_time((T0 + 12000) / 1000)}\n{PREVIEW}\n\nTesto cestinato\n"
    )
    untitled = f"Untitled {format_time((T0 + 13000) / 1000)[:10]}"
    assert read(f"Trash/{untitled}.txt").endswith("\n\n(no text)\n")


def test_attachments_are_byte_identical(tmp_path):
    _, out = _export(tmp_path)
    assert (out / "Lavoro/Contratto.pdf").read_bytes() == PDF
    assert (out / "Lavoro/Progetti/Verbale.jpg").read_bytes() == JPEG
    assert (out / "Lavoro/Progetti/Verbale_2.png").read_bytes() == PNG


def test_files_carry_the_note_modification_time(tmp_path):
    _, out = _export(tmp_path)
    assert abs(os.path.getmtime(out / "Uncategorized/Lista spesa.txt") - (T0 + 2000) / 1000) < 1
    assert abs(os.path.getmtime(out / "Lavoro/Contratto.pdf") - (T0 + 4000) / 1000) < 1


def test_out_of_range_modification_time_does_not_stop_the_export(tmp_path):
    notes = [("a", "Nota", None, b"testo", UNCAT, "1", 0, T0, 1_700_000_000_000_000)]
    result, out = _export(tmp_path, notes=notes, index=[], media={})
    assert result.notes == 1
    assert (out / "Uncategorized/Nota.txt").is_file()


def test_counts(tmp_path):
    result, _ = _export(tmp_path)
    assert (result.notes, result.text_notes, result.preview_only, result.attachments) == (7, 4, 2, 3)
    assert (result.handwriting_only, result.missing_files, result.with_drawings, result.trashed) == (1, 2, 2, 2)


def test_child_folder_name_clashing_with_a_note_file_name_does_not_stop_the_export(tmp_path):
    work, child = "cat-work2", "cat-notatxt"
    categories = [(work, None, "Lavoro", "x"), (child, work, "Nota.txt", "x")]
    notes = [
        ("a", "Nota", None, b"testo", work, "1", 0, T0, T0),
        ("b", "Sotto", None, b"testo2", child, "2", 0, T0 + 1, T0 + 1),
    ]
    _, out = _export(tmp_path, notes=notes, categories=categories, index=[], media={})
    assert _files(out) == sorted([
        "Lavoro/Nota (2).txt",
        "Lavoro/Nota.txt/Sotto.txt",
    ])


def test_same_titles_in_one_folder_do_not_overwrite_each_other(tmp_path):
    notes = [
        ("a", "Doppio", None, b"primo", UNCAT, "1", 0, T0, T0),
        ("b", "Doppio", None, None, UNCAT, "2", 0, T0 + 1, T0),
        ("c", "doppio", None, b"terzo", UNCAT, "3", 0, T0 + 2, T0),
    ]
    _, out = _export(tmp_path, notes=notes, index=[], media={"2": {"0@pdf_1.pdf": PDF}})
    assert _files(out) == sorted([
        "Uncategorized/Doppio.txt", "Uncategorized/Doppio (2).pdf", "Uncategorized/doppio (3).txt",
    ])


def test_attachment_named_like_the_text_file_gets_its_own_name(tmp_path):
    notes = [("a", "Nota", None, b"testo", UNCAT, "1", 0, T0, T0)]
    _, out = _export(tmp_path, notes=notes, index=[], media={"1": {"0@files_1.txt": b"allegato"}})
    assert _files(out) == ["Uncategorized/Nota.txt", "Uncategorized/Nota_attachment.txt"]
    assert (out / "Uncategorized/Nota_attachment.txt").read_bytes() == b"allegato"


def test_attachment_without_a_file_extension_gets_the_title_as_its_name(tmp_path):
    notes = [("a", "Nota", None, None, UNCAT, "1", 0, T0, T0)]
    _, out = _export(tmp_path, notes=notes, index=[], media={"1": {"0@blob": b"raw bytes"}})
    assert _files(out) == ["Uncategorized/Nota"]
    assert (out / "Uncategorized/Nota").read_bytes() == b"raw bytes"


def test_line_breaks_are_normalized(tmp_path):
    notes = [("a", "Nota", None, None, UNCAT, "1", 0, T0, T0)]
    _, out = _export(tmp_path, notes=notes, index=[("a", "uno\r\ndue\rtre")], media={"1": {}})
    assert (out / "Uncategorized/Nota.txt").read_bytes() == b"uno\ndue\ntre\n"


@pytest.mark.parametrize("raw, safe", [
    ('a<b>c:d"e/f\\g|h?i*j', "a_b_c_d_e_f_g_h_i_j"),
    ("  Nota.  ", "Nota"),
    ("", "Untitled"),
    ("...", "Untitled"),
    ("a\x01b", "a_b"),
    ("CON", "_CON"),
    ("con.txt", "_con.txt"),
    ("Lpt9", "_Lpt9"),
    ("x" * 150, "x" * 100),
])
def test_safe_name(raw, safe):
    assert safe_name(raw) == safe


def test_unsafe_titles_and_folders_are_made_safe(tmp_path):
    categories = [(UNCAT, None, "Uncategorized", "uncategorized:///"), ("w", UNCAT, "A/B", "x")]
    notes = [("a", "Q: 1/2?", None, b"x", "w", "1", 0, T0, T0)]
    _, out = _export(tmp_path, notes=notes, categories=categories, index=[], media={})
    assert _files(out) == ["A_B/Q_ 1_2_.txt"]


def test_no_notes_raises(tmp_path):
    with pytest.raises(NotesExportError, match="has no notes"):
        _export(tmp_path, notes=[], index=[], media={})


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_notes_scan_dir(tmp_path / "scan")
    out = tmp_path / "notes"
    out.write_text("a file, not a directory", encoding="utf-8")
    with pytest.raises(NotesExportError, match="cannot export"):
        export_notes(scan_dir, out)
