from __future__ import annotations

import quopri
import re

import pytest
import vobject

from ssba.core.parsers.contact import (
    ContactExportError,
    export_contacts,
    find_contact_sources,
)
from tests.contact_fixtures import (
    GOOGLE_NAME,
    GOOGLE_VCF,
    PHONE_NAME,
    TRICKY_VCF,
    build_scan_dir,
)


def test_find_sources_returns_vcf_files_profile_first(tmp_path):
    scan_dir = build_scan_dir(tmp_path / "scan")
    sources = find_contact_sources(scan_dir)
    assert [s.label for s in sources] == ["profile.vcf", GOOGLE_NAME, PHONE_NAME]
    assert [s.is_profile for s in sources] == [True, False, False]
    assert all(s.path.is_file() for s in sources)


def test_find_sources_without_report_raises(tmp_path):
    with pytest.raises(ContactExportError, match="report.json"):
        find_contact_sources(tmp_path)


def test_find_sources_without_contact_category_raises(tmp_path):
    (tmp_path / "report.json").write_text('{"categories": []}', encoding="utf-8")
    with pytest.raises(ContactExportError, match="CONTACT"):
        find_contact_sources(tmp_path)


def test_export_merges_all_sources_as_vcard3(tmp_path):
    scan_dir = build_scan_dir(tmp_path / "scan")
    out = tmp_path / "export" / "contacts.vcf"

    result = export_contacts(scan_dir, out)

    assert result.exported == 4
    assert result.per_source == {"profile.vcf": 1, GOOGLE_NAME: 2, PHONE_NAME: 1}
    assert result.unparsed == 0
    assert result.unparsed_path is None
    assert not (tmp_path / "export" / "contacts_unparsed.vcf").exists()

    cards = list(vobject.readComponents(out.read_text(encoding="utf-8")))
    assert [c.fn.value for c in cards] == ["Paolo Verdi", "Mario Rossi", "Ànna💋 Test", "Lucia Bianchi"]
    assert all(c.version.value == "3.0" for c in cards)


def test_export_writes_unparsed_cards_to_side_file(tmp_path):
    broken = "BEGIN:VCARD\r\nVERSION:2.1\r\nTHIS LINE HAS NO COLON\r\nEND:VCARD\r\n"
    scan_dir = build_scan_dir(tmp_path / "scan", google=GOOGLE_VCF + broken)
    out = tmp_path / "contacts.vcf"

    result = export_contacts(scan_dir, out)

    assert result.exported == 4
    assert result.unparsed == 1
    assert result.unparsed_path == tmp_path / "contacts_unparsed.vcf"
    assert "THIS LINE HAS NO COLON" in result.unparsed_path.read_text(encoding="utf-8")


def test_clean_export_removes_a_stale_unparsed_file(tmp_path):
    scan_dir = build_scan_dir(tmp_path / "scan")
    out = tmp_path / "contacts.vcf"
    stale = tmp_path / "contacts_unparsed.vcf"
    stale.write_text("BEGIN:VCARD\r\nfrom an earlier run\r\n", encoding="utf-8")

    result = export_contacts(scan_dir, out)

    assert result.unparsed == 0
    assert not stale.exists()


def test_export_to_a_directory_raises_contact_export_error(tmp_path):
    scan_dir = build_scan_dir(tmp_path / "scan")
    out = tmp_path / "contacts.vcf"
    out.mkdir()

    with pytest.raises(ContactExportError, match="cannot write"):
        export_contacts(scan_dir, out)


def test_unwritable_unparsed_side_file_raises_contact_export_error(tmp_path):
    broken = "BEGIN:VCARD\r\nVERSION:2.1\r\nTHIS LINE HAS NO COLON\r\nEND:VCARD\r\n"
    scan_dir = build_scan_dir(tmp_path / "scan", google=GOOGLE_VCF + broken)
    out = tmp_path / "contacts.vcf"
    (tmp_path / "contacts_unparsed.vcf").mkdir()

    with pytest.raises(ContactExportError, match="cannot write"):
        export_contacts(scan_dir, out)


def test_export_with_no_vcf_sources_raises(tmp_path):
    (tmp_path / "report.json").write_text(
        '{"categories": [{"category": "CONTACT", "counts": {}, "files": []}]}', encoding="utf-8"
    )
    with pytest.raises(ContactExportError, match="no contact"):
        export_contacts(tmp_path, tmp_path / "contacts.vcf")


def test_find_sources_with_invalid_report_structure_raises(tmp_path):
    """report.json that is a JSON array instead of object should raise ContactExportError."""
    (tmp_path / "report.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ContactExportError, match="not readable"):
        find_contact_sources(tmp_path)


def test_find_sources_with_non_utf8_report_raises(tmp_path):
    """report.json with invalid UTF-8 bytes should raise ContactExportError."""
    (tmp_path / "report.json").write_bytes(b"\xff\xfe{")
    with pytest.raises(ContactExportError, match="not readable"):
        find_contact_sources(tmp_path)


def test_find_sources_skips_malformed_entries(tmp_path):
    """CONTACT files with non-dict entries, null paths, etc. should be skipped, not crash."""
    contact_dir = tmp_path / "CONTACT" / "Container"
    contact_dir.mkdir(parents=True)
    (contact_dir / "valid.vcf").write_text(PHONE_NAME, encoding="utf-8", newline="")

    # Create report with various malformed entries
    import json
    files = [
        "not a dict",  # non-dict entry
        {"path": None, "status": "plaintext_passthrough"},  # null path
        {"status": "plaintext_passthrough"},  # missing path
        {"path": "Container/valid.vcf", "status": "plaintext_passthrough"},  # valid
    ]
    report = {
        "categories": [
            {"category": "CONTACT", "counts": {}, "files": files}
        ]
    }
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")

    sources = find_contact_sources(tmp_path)
    assert len(sources) == 1
    assert sources[0].label == "valid.vcf"


def test_find_sources_skips_path_traversal_attempts(tmp_path):
    """Paths escaping via .. or absolute paths should be skipped."""
    contact_dir = tmp_path / "CONTACT"
    contact_dir.mkdir(parents=True)

    # Create a valid VCF inside the CONTACT dir
    (contact_dir / "good.vcf").write_text(PHONE_NAME, encoding="utf-8", newline="")

    # Create files outside the CONTACT dir that path traversal might find; both
    # exist, so only the containment check can keep them out.
    (tmp_path / "outside.vcf").write_text(GOOGLE_VCF, encoding="utf-8", newline="")
    (tmp_path / "direct.vcf").write_text(GOOGLE_VCF, encoding="utf-8", newline="")

    # Create report with escaping attempts
    import json
    files = [
        {"path": "good.vcf", "status": "plaintext_passthrough"},  # valid
        {"path": "../outside.vcf", "status": "plaintext_passthrough"},  # escapes up
        {"path": str(tmp_path / "direct.vcf"), "status": "plaintext_passthrough"},  # absolute path
    ]
    report = {
        "categories": [
            {"category": "CONTACT", "counts": {}, "files": files}
        ]
    }
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")

    sources = find_contact_sources(tmp_path)
    # Only good.vcf should be included; the others should be skipped
    assert len(sources) == 1
    assert sources[0].label == "good.vcf"


def test_export_keeps_going_when_one_card_cannot_be_serialized(tmp_path):
    two_names = "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Uno;Primo;;;\r\nN:Due;Secondo;;;\r\nEND:VCARD\r\n"
    scan_dir = build_scan_dir(tmp_path / "scan", google=GOOGLE_VCF + two_names)
    out = tmp_path / "contacts.vcf"

    result = export_contacts(scan_dir, out)

    assert result.exported == 4
    assert result.unparsed == 1
    assert "N:Due;Secondo;;;" in result.unparsed_path.read_text(encoding="utf-8")


def test_export_keeps_unparsed_cards_byte_for_byte(tmp_path):
    truncated = "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Rossi;Mario;;;\r\nTEL;CELL:+39 333"
    scan_dir = build_scan_dir(tmp_path / "scan", google=GOOGLE_VCF + truncated)
    out = tmp_path / "contacts.vcf"

    result = export_contacts(scan_dir, out)

    assert result.unparsed == 1
    assert result.unparsed_path.read_bytes() == (truncated + "\r\n").encode("utf-8")


def _reference_values(card_text: str) -> list[tuple[str, list[str]]]:
    """Independent reference decoder for the fixture cards: unfold RFC folding
    and quoted-printable soft line breaks, split N/ORG on the literal ';'
    component separator, then QP-decode. (The fixtures hold no backslash
    escapes, so no escape handling is needed here.)"""
    props: list[list[str]] = []
    for line in re.split(r"\r\n|\r|\n", card_text):
        last = props[-1] if props else None
        if last and "QUOTED-PRINTABLE" in last[0].upper() and last[1].endswith("="):
            last[1] = last[1][:-1] + line
        elif last and line[:1] in (" ", "\t"):
            last[1] += line[1:]
        elif ":" in line:
            props.append(line.split(":", 1))
    values = []
    for header, value in props:
        name = header.split(";")[0].upper()
        parts = value.split(";") if name in ("N", "ORG") else [value]
        if "QUOTED-PRINTABLE" in header.upper():
            parts = [quopri.decodestring(p.encode("ascii")).decode("utf-8") for p in parts]
        values.append((name, parts))
    return values


def _exported_values(card) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for name, lines in card.contents.items():
        for line in lines:
            value = line.value
            if isinstance(value, vobject.vcard.Name):
                items = [value.family, value.given, value.additional, value.prefix, value.suffix]
            elif isinstance(value, list):
                items = value
            else:
                items = [value]
            values.setdefault(name.upper(), []).extend(items)
    return values


def test_every_decoded_source_value_appears_whole_in_the_export(tmp_path):
    scan_dir = build_scan_dir(tmp_path / "scan", google=GOOGLE_VCF + TRICKY_VCF)
    out = tmp_path / "contacts.vcf"

    result = export_contacts(scan_dir, out)

    assert result.unparsed == 0
    exported = [_exported_values(c) for c in vobject.readComponents(out.read_text(encoding="utf-8"))]
    sources = re.findall(r"BEGIN:VCARD.*?END:VCARD", GOOGLE_VCF + TRICKY_VCF, re.DOTALL)
    google = exported[1:1 + len(sources)]  # the profile comes first
    checked = 0
    for source, values in zip(sources, google, strict=True):
        for name, parts in _reference_values(source):
            if name in ("BEGIN", "END", "VERSION"):
                continue
            value = parts[0]
            if name in ("N", "ORG"):
                expected = [(name, part) for part in parts if part]
            elif name == "DEPARTMENT":
                expected = [("ORG", value)]
            elif name == "GROUP_MEMBER":
                expected = [("CATEGORIES", value)]
            else:
                expected = [(name, value)]
            for key, part in expected:
                assert part in values.get(key, []), (key, part)
                checked += 1
    assert checked == 23  # every source value of the 4 Google cards was compared
