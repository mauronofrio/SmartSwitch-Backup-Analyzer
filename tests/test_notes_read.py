from __future__ import annotations

import sqlite3

import pytest

from ssba.core.parsers.html_page import format_time
from ssba.core.parsers.notes import NotesExportError, read_notes
from tests.notes_fixtures import T0, UNCAT, build_notes_scan_dir
from tests.scan_fixtures import add_category

DB = ("SAMSUNGNOTE", "sdoc.snmm", "sdoc.bk", "SmartSwitchRestoreDB", "sdoc.db")


def _read(tmp_path, **kwargs):
    return {n.title: n for n in read_notes(build_notes_scan_dir(tmp_path / "scan", **kwargs))}


def test_notes_are_read_in_creation_order_with_title_fallbacks(tmp_path):
    notes = read_notes(build_notes_scan_dir(tmp_path / "scan"))
    untitled = f"Untitled {format_time((T0 + 13000) / 1000)[:10]}"
    assert [n.title for n in notes] == [
        "Lista spesa", "Contratto", "Verbale", "Schizzo", "Solo anteprima", "Vecchia", untitled,
    ]


def test_folders_follow_the_category_tree(tmp_path):
    notes = _read(tmp_path)
    assert notes["Lista spesa"].folder == ("Uncategorized",)
    assert notes["Contratto"].folder == ("Lavoro",)
    assert notes["Verbale"].folder == ("Lavoro", "Progetti")
    assert notes["Schizzo"].folder == ("Old notebooks", "Quaderno 2019")
    assert notes["Vecchia"].folder == ("Trash",)


def test_unknown_category_goes_to_uncategorized(tmp_path):
    note = ("n", "Orfana", None, b"x", "no-such-category", "1", 0, T0, T0)
    notes = _read(tmp_path, notes=[note], index=[], media={})
    assert notes["Orfana"].folder == ("Uncategorized",)


def test_parent_cycle_and_empty_folder_name_do_not_hang(tmp_path):
    categories = [("a", "b", "", "x"), ("b", "a", "B", "x")]
    note = ("n", "Nota", None, b"x", "a", "1", 0, T0, T0)
    notes = _read(tmp_path, notes=[note], categories=categories, index=[], media={})
    assert notes["Nota"].folder == ("B", "Untitled folder")


def test_untitled_note_fallback_when_title_and_created_at_are_both_missing(tmp_path):
    note = ("n", "", None, None, UNCAT, "1", 0, None, T0)
    notes = _read(tmp_path, notes=[note], index=[], media={})
    assert "Untitled note" in notes


def test_text_comes_from_the_index_then_the_preview(tmp_path):
    notes = _read(tmp_path)
    assert (notes["Lista spesa"].text, notes["Lista spesa"].text_source) == ("Latte\nPane\nUova", "index")
    assert (notes["Solo anteprima"].text, notes["Solo anteprima"].text_source) == ("Anteprima tronc", "preview")
    assert (notes["Contratto"].text, notes["Contratto"].text_source) == (None, None)


def test_attachments_are_ordered_and_exclude_media_info_and_drawings(tmp_path):
    notes = _read(tmp_path)
    assert [p.name for p in notes["Verbale"].attachments] == ["0@paste_1.jpg", "1@paste_2.png"]
    assert [p.name for p in notes["Contratto"].attachments] == ["0@pdf_1.pdf"]
    assert notes["Lista spesa"].attachments == []
    assert notes["Contratto"].has_drawings is True
    assert notes["Schizzo"].has_drawings is True
    assert notes["Verbale"].has_drawings is False


def test_media_without_an_index_prefix_comes_last(tmp_path):
    note = ("n", "Nota", None, None, UNCAT, "1", 0, T0, T0)
    media = {"1": {"cover.jpg": b"c", "2@b.jpg": b"b", "10@a.jpg": b"a"}}
    notes = _read(tmp_path, notes=[note], index=[], media=media)
    assert [p.name for p in notes["Nota"].attachments] == ["2@b.jpg", "10@a.jpg", "cover.jpg"]


def test_missing_note_folder_is_flagged(tmp_path):
    notes = _read(tmp_path)
    assert notes["Vecchia"].file_missing is True
    assert notes["Vecchia"].deleted is True
    assert notes["Solo anteprima"].file_missing is False


def test_unsafe_file_path_stem_is_never_followed(tmp_path):
    note = ("n", "Nota", None, b"x", UNCAT, "y z", 0, T0, T0)
    notes = _read(tmp_path, notes=[note], index=[], media={"y z": {"0@pdf_1.pdf": b"%PDF"}})
    assert notes["Nota"].file_missing is True
    assert notes["Nota"].attachments == []


def test_invalid_utf8_in_a_title_does_not_stop_the_export(tmp_path):
    scan_dir = build_notes_scan_dir(tmp_path / "scan")
    con = sqlite3.connect(scan_dir.joinpath(*DB))
    con.execute("UPDATE sdoc SET title = CAST(? AS TEXT) WHERE UUID = 'n-text'", (b"Nota \xff",))
    con.commit()
    con.close()

    notes = read_notes(scan_dir)

    assert len(notes) == 7
    assert any("Nota �" in n.title for n in notes)


def test_rows_only_in_the_wal_are_read_and_the_original_is_untouched(tmp_path):
    wal_note = ("n-wal", "Solo nel WAL", None, b"x", UNCAT, "1700000000009", 0, T0 + 20000, T0 + 21000)
    scan_dir = build_notes_scan_dir(tmp_path / "scan", wal_notes=[wal_note])
    db_dir = scan_dir.joinpath(*DB).parent
    before = {p.name: p.read_bytes() for p in db_dir.iterdir()}
    assert "Solo nel WAL" in [n.title for n in read_notes(scan_dir)]
    assert {p.name: p.read_bytes() for p in db_dir.iterdir()} == before


def test_a_file_that_is_not_a_wal_is_ignored(tmp_path):
    scan_dir = build_notes_scan_dir(tmp_path / "scan")
    scan_dir.joinpath(*DB).with_name("sdoc.db-wal").write_bytes(b"garbage")
    assert len(read_notes(scan_dir)) == 7


def test_missing_table_raises(tmp_path):
    scan_dir = build_notes_scan_dir(tmp_path / "scan")
    con = sqlite3.connect(scan_dir.joinpath(*DB))
    con.execute("DROP TABLE category_tree")
    con.commit()
    con.close()
    with pytest.raises(NotesExportError, match="category_tree"):
        read_notes(scan_dir)


def test_corrupt_database_raises(tmp_path):
    scan_dir = build_notes_scan_dir(tmp_path / "scan")
    scan_dir.joinpath(*DB).write_bytes(b"not a database at all" * 100)
    with pytest.raises(NotesExportError, match="cannot read"):
        read_notes(scan_dir)


def test_no_database_raises(tmp_path):
    add_category(tmp_path, "SAMSUNGNOTE", [])
    with pytest.raises(NotesExportError, match="no Samsung Notes database"):
        read_notes(tmp_path)


def test_missing_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(NotesExportError, match="SAMSUNGNOTE"):
        read_notes(tmp_path)


def test_placeholder_title_falls_back_to_the_first_line_of_text(tmp_path):
    # Samsung Notes stores b"\x01\x00..." as the title of notes the user never named.
    note = ("n", "\x01" + "\x00" * 11, None, b"  Coca.      Rinascita ,\n punto di.", UNCAT, "1", 0, T0, T0)
    notes = read_notes(build_notes_scan_dir(tmp_path / "scan", notes=[note], index=[], media={}))
    assert [n.title for n in notes] == ["Coca. Rinascita ,"]


def test_long_first_line_is_cut_at_a_word(tmp_path):
    text = ("parola " * 20).encode()
    note = ("n", "", None, text, UNCAT, "1", 0, T0, T0)
    notes = read_notes(build_notes_scan_dir(tmp_path / "scan", notes=[note], index=[], media={}))
    title = notes[0].title
    assert title.endswith("parola\u2026")
    assert len(title) <= 51


def test_placeholder_title_without_text_is_untitled_with_its_date(tmp_path):
    note = ("n", "\x01\x00\x00", b"\x00\x00", None, UNCAT, "1", 0, T0, T0)
    notes = read_notes(build_notes_scan_dir(tmp_path / "scan", notes=[note], index=[], media={}))
    assert notes[0].title == f"Untitled {format_time(T0 / 1000)[:10]}"
