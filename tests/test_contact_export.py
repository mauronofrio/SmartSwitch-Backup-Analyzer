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
