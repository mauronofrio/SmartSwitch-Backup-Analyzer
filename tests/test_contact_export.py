from __future__ import annotations

import pytest
import vobject

from ssba.core.parsers.contact import (
    ContactExportError,
    export_contacts,
    find_contact_sources,
)
from tests.contact_fixtures import GOOGLE_NAME, GOOGLE_VCF, PHONE_NAME, build_scan_dir


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

    # Create files outside the CONTACT dir that path traversal might find
    (tmp_path / "outside.vcf").write_text(GOOGLE_VCF, encoding="utf-8", newline="")

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
