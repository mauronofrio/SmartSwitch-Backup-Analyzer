from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

from ssba.core.crypto import derive_key
from ssba.core.scanner import list_categories, scan_backup, scan_category
from tests.crypto_helpers import encrypt_dummy_ecb, encrypt_iv_prefixed

FAKE_DUMMY = "AABBCCDDEEFF00112233445566778899AABB"
KEY = derive_key(FAKE_DUMMY)


def _write_history_xml(backup_root: Path) -> None:
    backup_root.mkdir(parents=True, exist_ok=True)
    ciphertext_hex = encrypt_dummy_ecb(FAKE_DUMMY)
    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<BatchInfomationItem xmlns="Kies.Common.Data">
    <BundleInfo><Dummy>{ciphertext_hex}</Dummy></BundleInfo>
</BatchInfomationItem>"""
    (backup_root / "backupHistoryInfo.xml").write_text(xml, encoding="utf-8")


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _build_fake_backup(backup_root: Path) -> None:
    _write_history_xml(backup_root)

    # Category A: a directly-encrypted file (like Notes' sdoc.bk / Calllog's exml)
    plaintext_a = b"<?xml version='1.0'?><FakeCallLogs><entry>fake</entry></FakeCallLogs>"
    (backup_root / "CATEGORY_A").mkdir()
    (backup_root / "CATEGORY_A" / "data.exml").write_bytes(
        encrypt_iv_prefixed(plaintext_a, KEY)
    )

    # Category B: a plain outer zip wrapping one encrypted entry and one
    # already-plaintext entry (like Contact.spbm)
    inner_encrypted = encrypt_iv_prefixed(b'{"contacts": ["fake person"]}', KEY)
    outer_zip = _zip_bytes(
        {
            "Contact.bk": inner_encrypted,
            "readme.txt": b"already plaintext, should pass through untouched",
        }
    )
    (backup_root / "CATEGORY_B").mkdir()
    (backup_root / "CATEGORY_B" / "Contact.spbm").write_bytes(outer_zip)

    # Category C: data that isn't really encrypted with this scheme at all
    (backup_root / "CATEGORY_C").mkdir()
    (backup_root / "CATEGORY_C" / "mystery.bin").write_bytes(bytes(range(256)) * 4)


def test_list_categories(tmp_path):
    _build_fake_backup(tmp_path)
    assert list_categories(tmp_path) == ["CATEGORY_A", "CATEGORY_B", "CATEGORY_C"]


def test_scan_category_direct_encrypted_file(tmp_path):
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_A", KEY, out_dir)
    assert result.counts()["decrypted"] == 1
    decrypted_path = out_dir / "CATEGORY_A" / "data.exml"
    assert decrypted_path.exists()
    assert b"FakeCallLogs" in decrypted_path.read_bytes()


def test_scan_category_wrapped_zip(tmp_path):
    """Contact.spbm is one of the known Smart Switch wrapper containers
    (KNOWN_SMART_SWITCH_CONTAINERS), so it must still be recursed into by
    exact-name catalog match, even though it isn't a recognized document
    by content and its extension carries no special meaning.
    """
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_B", KEY, out_dir)
    counts = result.counts()
    assert counts["plaintext_passthrough"] == 2  # Contact.spbm itself + readme.txt
    assert counts["decrypted"] == 1  # Contact.bk
    assert (out_dir / "CATEGORY_B" / "Contact.spbm" / "Contact.bk").exists()
    assert (out_dir / "CATEGORY_B" / "Contact.spbm" / "readme.txt").read_bytes() == (
        b"already plaintext, should pass through untouched"
    )


def test_scan_category_docx_preserved_as_opaque_file(tmp_path):
    """Regression test: a real end-user .docx (itself a zip container under
    the hood) must be recovered as a single, openable file - not exploded
    into a directory of its internal XML parts, even though sniff_kind
    correctly reports it as kind="zip".
    """
    _write_history_xml(tmp_path)

    docx_bytes = _zip_bytes(
        {
            "[Content_Types].xml": b"<?xml version='1.0'?><Types/>",
            "word/document.xml": b"<?xml version='1.0'?><w:document/>",
            "docProps/core.xml": b"<?xml version='1.0'?><coreProperties/>",
        }
    )

    (tmp_path / "CATEGORY_E").mkdir()
    (tmp_path / "CATEGORY_E" / "CASTELLANA_GENNAIO_2024649.docx").write_bytes(docx_bytes)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_E", KEY, out_dir)

    docx_out_path = out_dir / "CATEGORY_E" / "CASTELLANA_GENNAIO_2024649.docx"
    assert docx_out_path.is_file(), "expected the .docx to be written as a single file"
    assert docx_out_path.read_bytes() == docx_bytes

    # No exploded directory structure for the .docx's internal parts.
    assert not (docx_out_path / "word").exists()
    assert not (out_dir / "CATEGORY_E" / "CASTELLANA_GENNAIO_2024649.docx" / "[Content_Types].xml").exists()

    assert len(result.files) == 1
    file_result = result.files[0]
    assert file_result.relative_path == "CASTELLANA_GENNAIO_2024649.docx"
    assert file_result.status == "plaintext_passthrough"
    assert file_result.kind == "zip"


def test_scan_category_non_catalog_zip_preserved_not_recursed(tmp_path):
    """The conservative default: a zip-shaped file that is neither a
    recognized document by content (no "[Content_Types].xml" or
    "mimetype") NOR an exact-name match in KNOWN_SMART_SWITCH_CONTAINERS
    must be preserved as a single, opaque file - never recursed into. This
    covers both the user's own arbitrary .zip files and any Smart
    Switch-internal container we haven't specifically hand-verified, and
    is a real behavior change from the pre-this-change code (which
    recursed into any zip by default): the project owner explicitly
    preferred this safe, conservative default over unpacking anything not
    specifically catalogued.
    """
    _write_history_xml(tmp_path)

    wrapper_zip = _zip_bytes({"readme.txt": b"plain content inside wrapper"})

    (tmp_path / "CATEGORY_F").mkdir()
    (tmp_path / "CATEGORY_F" / "Contact.zip").write_bytes(wrapper_zip)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_F", KEY, out_dir)

    wrapper_out_path = out_dir / "CATEGORY_F" / "Contact.zip"
    assert wrapper_out_path.is_file(), (
        "non-catalogued, non-document zip must be preserved as a single file, not exploded"
    )
    assert wrapper_out_path.read_bytes() == wrapper_zip

    counts = result.counts()
    assert counts["plaintext_passthrough"] == 1  # Contact.zip itself, not recursed


def test_scan_category_encrypted_docx_preserved_as_opaque_file(tmp_path):
    """Guard point 2: an encrypted attachment that decrypts to zip bytes and
    is named like a document (e.g. invoice.docx) must also be preserved as
    a single file - not recursed into - once decrypted. This covers the
    `blob.kind == "zip"` branch in _process, the decrypted counterpart of
    test_scan_category_docx_preserved_as_opaque_file (which covers the
    plaintext_passthrough branch).
    """
    _write_history_xml(tmp_path)

    docx_bytes = _zip_bytes(
        {
            "[Content_Types].xml": b"<?xml version='1.0'?><Types/>",
            "word/document.xml": b"<?xml version='1.0'?><w:document/>",
        }
    )
    encrypted_docx = encrypt_iv_prefixed(docx_bytes, KEY)

    (tmp_path / "CATEGORY_G").mkdir()
    (tmp_path / "CATEGORY_G" / "invoice.docx").write_bytes(encrypted_docx)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_G", KEY, out_dir)

    docx_out_path = out_dir / "CATEGORY_G" / "invoice.docx"
    assert docx_out_path.is_file(), "expected the decrypted .docx to be written as a single file"
    # This fixture is zero-padded to a 16-byte block boundary, and decryption
    # doesn't strip zero padding (it's not reversible in general for
    # arbitrary binary content), so the written bytes are the original zip
    # plus trailing null padding - harmless to zip readers, which stop at
    # the end-of-central-directory record. Verify via the prefix and by
    # actually opening it as a zip, rather than requiring exact equality.
    written = docx_out_path.read_bytes()
    assert written.startswith(docx_bytes)
    assert written[len(docx_bytes) :] == b"\x00" * (len(written) - len(docx_bytes))
    with zipfile.ZipFile(docx_out_path) as zf:
        assert set(zf.namelist()) == {"[Content_Types].xml", "word/document.xml"}
        assert zf.read("word/document.xml") == b"<?xml version='1.0'?><w:document/>"

    # No exploded directory structure for the decrypted .docx's internal parts.
    assert not (docx_out_path / "word").exists()

    assert len(result.files) == 1
    file_result = result.files[0]
    assert file_result.relative_path == "invoice.docx"
    assert file_result.status == "decrypted"
    assert file_result.kind == "zip"


def test_scan_category_docx_extension_matched_case_insensitively(tmp_path):
    """Content-based document detection doesn't look at the extension at
    all, so it's inherently case-insensitive (and extension-insensitive) -
    this is a lightweight regression check that an uppercase ".DOCX" name
    doesn't somehow interfere with the content sniff.
    """
    _write_history_xml(tmp_path)

    docx_bytes = _zip_bytes({"[Content_Types].xml": b"<?xml version='1.0'?><Types/>"})

    (tmp_path / "CATEGORY_H").mkdir()
    (tmp_path / "CATEGORY_H" / "INVOICE.DOCX").write_bytes(docx_bytes)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_H", KEY, out_dir)

    docx_out_path = out_dir / "CATEGORY_H" / "INVOICE.DOCX"
    assert docx_out_path.is_file(), "expected uppercase .DOCX to be matched case-insensitively"
    assert docx_out_path.read_bytes() == docx_bytes
    assert len(result.files) == 1
    assert result.files[0].status == "plaintext_passthrough"
    assert result.files[0].kind == "zip"


def test_scan_category_ooxml_content_detected_despite_wrong_extension(tmp_path):
    """Real bug found against the project owner's own 49GB backup: several
    files had a .pdf extension but were actually PowerPoint/Word documents
    (confirmed via ppt/presentation.xml or word/document.xml inside).
    Extension-based matching can't catch this since the extension lies;
    content-based detection (a root-level "[Content_Types].xml" entry)
    must catch it regardless of the misleading name.
    """
    _write_history_xml(tmp_path)

    pptx_bytes = _zip_bytes(
        {
            "[Content_Types].xml": b"<?xml version='1.0'?><Types/>",
            "ppt/presentation.xml": b"<?xml version='1.0'?><p:presentation/>",
        }
    )

    (tmp_path / "CATEGORY_MISLABELED").mkdir()
    (tmp_path / "CATEGORY_MISLABELED" / "not_actually_a.pdf").write_bytes(pptx_bytes)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_MISLABELED", KEY, out_dir)

    out_path = out_dir / "CATEGORY_MISLABELED" / "not_actually_a.pdf"
    assert out_path.is_file(), (
        "mislabeled .pdf (actually pptx content) must be preserved as a single file"
    )
    assert out_path.read_bytes() == pptx_bytes
    assert len(result.files) == 1
    assert result.files[0].status == "plaintext_passthrough"
    assert result.files[0].kind == "zip"


def test_scan_category_odf_content_detected_via_mimetype(tmp_path):
    """Content-based ODF detection: a root-level "mimetype" entry whose
    bytes start with "application/vnd.oasis.opendocument." marks this as
    an OpenDocument file, which must be preserved as a single file.
    """
    _write_history_xml(tmp_path)

    odf_bytes = _zip_bytes(
        {
            "mimetype": b"application/vnd.oasis.opendocument.text",
            "content.xml": b"<?xml version='1.0'?><office:document-content/>",
        }
    )
    (tmp_path / "CATEGORY_ODF").mkdir()
    (tmp_path / "CATEGORY_ODF" / "notes.odt").write_bytes(odf_bytes)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_ODF", KEY, out_dir)

    out_path = out_dir / "CATEGORY_ODF" / "notes.odt"
    assert out_path.is_file()
    assert out_path.read_bytes() == odf_bytes
    assert len(result.files) == 1
    assert result.files[0].status == "plaintext_passthrough"
    assert result.files[0].kind == "zip"


def test_scan_category_epub_content_detected_via_mimetype(tmp_path):
    """Content-based EPUB detection: a root-level "mimetype" entry whose
    bytes are exactly "application/epub+zip" marks this as an EPUB, which
    must be preserved as a single file.
    """
    _write_history_xml(tmp_path)

    epub_bytes = _zip_bytes(
        {
            "mimetype": b"application/epub+zip",
            "META-INF/container.xml": b"<?xml version='1.0'?><container/>",
        }
    )
    (tmp_path / "CATEGORY_EPUB").mkdir()
    (tmp_path / "CATEGORY_EPUB" / "book.epub").write_bytes(epub_bytes)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_EPUB", KEY, out_dir)

    out_path = out_dir / "CATEGORY_EPUB" / "book.epub"
    assert out_path.is_file()
    assert out_path.read_bytes() == epub_bytes
    assert len(result.files) == 1
    assert result.files[0].status == "plaintext_passthrough"
    assert result.files[0].kind == "zip"


def test_scan_category_epub_mimetype_with_trailing_newline_still_detected(tmp_path):
    """Regression test (M2): some real-world EPUB producers append a
    trailing newline to the "mimetype" entry, even though the EPUB spec
    forbids it. A byte-exact comparison would miss this and wrongly treat
    the file as a generic zip; the comparison must strip surrounding
    whitespace first.
    """
    _write_history_xml(tmp_path)

    epub_bytes = _zip_bytes({"mimetype": b"application/epub+zip\n"})
    (tmp_path / "CATEGORY_EPUB_NEWLINE").mkdir()
    (tmp_path / "CATEGORY_EPUB_NEWLINE" / "book.epub").write_bytes(epub_bytes)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_EPUB_NEWLINE", KEY, out_dir)

    out_path = out_dir / "CATEGORY_EPUB_NEWLINE" / "book.epub"
    assert out_path.is_file()
    assert out_path.read_bytes() == epub_bytes
    assert len(result.files) == 1
    assert result.files[0].status == "plaintext_passthrough"
    assert result.files[0].kind == "zip"


def test_scan_category_generic_zip_not_recursed_regardless_of_surrounding_structure(tmp_path):
    """The catalog-based default doesn't care about the surrounding
    category's shape at all (an earlier design considered a "category is
    flat vs has subdirectories" structural signal, but that was dropped as
    too fragile - see KNOWN_SMART_SWITCH_CONTAINERS's docstring). This
    models a literal user .zip file (not catalogued, not a recognized
    document by content) sitting next to an unrelated real subfolder, e.g.
    the EtcFolder/EtcFile shape found in the real backup, and confirms the
    same "preserve, don't recurse" default applies there too.
    """
    _write_history_xml(tmp_path)

    category_dir = tmp_path / "EtcFolder_LIKE"
    category_dir.mkdir()
    (category_dir / "some_subdir").mkdir()
    (category_dir / "some_subdir" / "other.txt").write_bytes(
        encrypt_iv_prefixed(b"unrelated file inside a real subfolder", KEY)
    )
    generic_zip = _zip_bytes({"readme.txt": b"just a plain zip, not a document"})
    (category_dir / "myarchive.zip").write_bytes(generic_zip)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "EtcFolder_LIKE", KEY, out_dir)

    zip_out_path = out_dir / "EtcFolder_LIKE" / "myarchive.zip"
    assert zip_out_path.is_file(), (
        "non-catalogued generic zip must be preserved as a single file"
    )
    assert zip_out_path.read_bytes() == generic_zip

    matching = [f for f in result.files if f.relative_path == "myarchive.zip"]
    assert len(matching) == 1
    assert matching[0].status == "plaintext_passthrough"
    assert matching[0].kind == "zip"


def test_scan_category_apk_never_recursed_even_in_flat_category(tmp_path):
    """.apk (and .jar) files must never be unpacked, regardless of category
    shape - this is an explicit backstop independent of the structural
    rule, even in a flat category where the structural rule alone would
    otherwise say "recurse".
    """
    _write_history_xml(tmp_path)

    apk_bytes = _zip_bytes({"AndroidManifest.xml": b"fake manifest bytes"})
    (tmp_path / "CATEGORY_APK").mkdir()
    (tmp_path / "CATEGORY_APK" / "someapp.apk").write_bytes(apk_bytes)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_APK", KEY, out_dir)

    apk_out_path = out_dir / "CATEGORY_APK" / "someapp.apk"
    assert apk_out_path.is_file(), (
        "apk must be preserved as a single file even in a flat category"
    )
    assert apk_out_path.read_bytes() == apk_bytes
    assert len(result.files) == 1
    assert result.files[0].status == "plaintext_passthrough"


def test_scan_category_known_container_chain_recursed_end_to_end(tmp_path):
    """Regression-guards real Notes recovery, the project's single most
    important already-validated real-world case: sdoc.snmm and sdoc.bk are
    both exact-name entries in KNOWN_SMART_SWITCH_CONTAINERS, and
    b_1.sdocx (one of Notes' individual per-note attachment packages) is
    recognized by its .sdocx extension (KNOWN_SMART_SWITCH_EXTENSIONS,
    since per-note ids vary and can't be exact-name catalogued). So the
    full three-layer encrypted/nested chain (sdoc.snmm -> decrypts to a
    zip containing sdoc.bk -> decrypts to a zip containing
    SmartSwitchRestoreDB/marker.txt and b_1.sdocx -> b_1.sdocx itself a
    zip containing the real note media) must be opened all the way down.

    (An earlier design considered here made this decision from a one-time
    "is this category flat" structural flag computed once per category and
    threaded through recursion - that approach was reconsidered as too
    fragile and replaced by this small, explicit, hand-verified catalog.
    Since KNOWN_SMART_SWITCH_CONTAINERS/KNOWN_SMART_SWITCH_EXTENSIONS are
    stateless per-name/per-extension lookups with nothing to thread or
    accidentally re-derive, the "does the decision survive intermediate
    recursion output" concern that motivated the old design no longer
    applies here by construction.)
    """
    _write_history_xml(tmp_path)

    final_content = b"%PDF-1.4 fake pdf bytes for final note attachment"
    b1_sdocx_zip = _zip_bytes({"media/final.pdf": final_content})

    marker_content = b"restore db marker, not related to note content"

    # inner_zip is what sdoc.bk decrypts to: a loose plaintext file
    # (SmartSwitchRestoreDB/marker.txt) alongside a per-note package
    # (b_1.sdocx) that is itself zip-shaped, not exact-name catalogued,
    # but recognized by its .sdocx extension.
    inner_zip = _zip_bytes(
        {
            "SmartSwitchRestoreDB/marker.txt": marker_content,
            "b_1.sdocx": b1_sdocx_zip,
        }
    )
    sdoc_bk_encrypted = encrypt_iv_prefixed(inner_zip, KEY)

    snmm_zip = _zip_bytes({"sdoc.bk": sdoc_bk_encrypted})
    sdoc_snmm_encrypted = encrypt_iv_prefixed(snmm_zip, KEY)

    category_dir = tmp_path / "SAMSUNGNOTE_LIKE"
    category_dir.mkdir()
    (category_dir / "sdoc.snmm").write_bytes(sdoc_snmm_encrypted)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "SAMSUNGNOTE_LIKE", KEY, out_dir)

    assert result.counts()["error"] == 0, f"expected no errors, got {result.files}"

    # sdoc.snmm -> sdoc.bk chain opened correctly: the loose entry inside
    # sdoc.bk was reached and extracted.
    marker_out = (
        out_dir / "SAMSUNGNOTE_LIKE" / "sdoc.snmm" / "sdoc.bk"
        / "SmartSwitchRestoreDB" / "marker.txt"
    )
    assert marker_out.is_file()
    assert marker_out.read_bytes() == marker_content

    # b_1.sdocx must now also be recursed into (via the .sdocx extension
    # rule), reaching the real note media inside it.
    final_out = (
        out_dir / "SAMSUNGNOTE_LIKE" / "sdoc.snmm" / "sdoc.bk"
        / "b_1.sdocx" / "media" / "final.pdf"
    )
    assert final_out.is_file(), (
        "b_1.sdocx has a .sdocx extension, so it must be recursed into to "
        "reach media/final.pdf, not preserved as a single opaque file"
    )
    assert final_out.read_bytes() == final_content


def test_scan_category_sdocx_extension_recursed_as_known_container(tmp_path):
    """.sdocx is a proprietary Samsung Notes per-note package extension -
    never a format a real user would create themselves - so any file with
    that extension (case-insensitive) must always be recursed into, even
    though its per-note id makes it impossible to exact-name catalogue in
    KNOWN_SMART_SWITCH_CONTAINERS and it isn't a recognized document by
    content. This closes the gap flagged after the catalog-based design
    landed: b_<id>.sdocx packages were being preserved whole instead of
    having their contents (note.note, media/*) reached. Named with a
    realistic id (b_1665469124387.sdocx) to match the real pattern, not
    just a placeholder.
    """
    _write_history_xml(tmp_path)

    media_content = b"fake jpeg-ish media bytes for a note attachment"
    note_content = b'{"note": "some real note content"}'
    sdocx_zip = _zip_bytes(
        {
            "note.note": note_content,
            "media/photo.jpg": media_content,
        }
    )

    (tmp_path / "SAMSUNGNOTE_PACKAGES").mkdir()
    (tmp_path / "SAMSUNGNOTE_PACKAGES" / "b_1665469124387.sdocx").write_bytes(sdocx_zip)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "SAMSUNGNOTE_PACKAGES", KEY, out_dir)

    assert result.counts()["error"] == 0, f"expected no errors, got {result.files}"

    note_out = (
        out_dir / "SAMSUNGNOTE_PACKAGES" / "b_1665469124387.sdocx" / "note.note"
    )
    assert note_out.is_file(), ".sdocx must be recursed into to reach note.note"
    assert note_out.read_bytes() == note_content

    media_out = (
        out_dir / "SAMSUNGNOTE_PACKAGES" / "b_1665469124387.sdocx" / "media" / "photo.jpg"
    )
    assert media_out.is_file(), ".sdocx must be recursed into to reach media/*"
    assert media_out.read_bytes() == media_content


def test_scan_category_dotless_sdocx_filename_not_treated_as_extension_match(tmp_path):
    """Regression test (M1): a file literally named "sdocx" (no dot at
    all) must NOT be treated as having a ".sdocx" extension. This was a
    real bug in the first .sdocx fix: str.rpartition(".") on a dotless
    string returns ("", "", the_whole_string) rather than empty pieces,
    so a naive `_, _, ext = basename.rpartition("."); bool(ext) and ...`
    check misread a dotless "sdocx" as if its extension were "sdocx" and
    incorrectly recursed into it. It's also not in
    KNOWN_SMART_SWITCH_CONTAINERS and not a recognized document by
    content, so under every other rule it must be preserved as-is too.
    """
    _write_history_xml(tmp_path)

    generic_zip = _zip_bytes({"readme.txt": b"not a real note package"})

    (tmp_path / "CATEGORY_DOTLESS").mkdir()
    (tmp_path / "CATEGORY_DOTLESS" / "sdocx").write_bytes(generic_zip)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_DOTLESS", KEY, out_dir)

    out_path = out_dir / "CATEGORY_DOTLESS" / "sdocx"
    assert out_path.is_file(), (
        "a dotless file literally named 'sdocx' must be preserved as a "
        "single file, not misread as having a .sdocx extension"
    )
    assert out_path.read_bytes() == generic_zip


def test_scan_category_wrapper_named_after_category_is_recursed(tmp_path):
    """Important #1: ~90 real Smart Switch categories store their payload
    in a wrapper file named identically to the category folder itself
    (e.g. WIFICONFIG/WIFICONFIG.zip, SBROWSER/SBROWSER.zip,
    HOMESCREEN/HOMESCREEN.zip - verified against this repo's own earlier
    real-scan output at out/real-scan/). CALLLOG.zip was hand-catalogued
    as one specific instance of this, but the general pattern - the
    wrapper's name, minus extension, equals the category it lives in -
    was missing, so all ~90 other categories following the same pattern
    silently stopped being opened at all once the catalog-based design
    landed (a real, silent loss of decrypted data, not just an unpacking
    preference). This models the WIFICONFIG shape directly: a category
    whose sole top-level file is named exactly like the category itself,
    zip-shaped, not otherwise catalogued/content-matched, must be
    recursed into.
    """
    _write_history_xml(tmp_path)

    payload_zip = _zip_bytes(
        {
            "WifiConfigStore.xml": b"<?xml version='1.0'?><WifiConfigStoreData/>",
            "wpa_supplicant.conf": b"just some plain config text",
        }
    )

    (tmp_path / "WIFICONFIG").mkdir()
    (tmp_path / "WIFICONFIG" / "WIFICONFIG.zip").write_bytes(payload_zip)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "WIFICONFIG", KEY, out_dir)

    assert result.counts()["error"] == 0, f"expected no errors, got {result.files}"

    wrapper_out = out_dir / "WIFICONFIG" / "WIFICONFIG.zip"
    assert not wrapper_out.is_file(), (
        "WIFICONFIG.zip's name (minus extension) matches its category "
        "WIFICONFIG, so it must be recursed into, not preserved whole"
    )
    xml_out = wrapper_out / "WifiConfigStore.xml"
    assert xml_out.is_file()
    assert xml_out.read_bytes() == b"<?xml version='1.0'?><WifiConfigStoreData/>"
    conf_out = wrapper_out / "wpa_supplicant.conf"
    assert conf_out.is_file()
    assert conf_out.read_bytes() == b"just some plain config text"


def test_is_zip_shaped_document_rejects_oversized_mimetype_entry_without_reading(monkeypatch):
    """Important #2: a crafted zip can declare a "mimetype" entry whose
    declared/actual size is enormous relative to a real ODF/EPUB mimetype
    value (a few dozen bytes) - this peek runs on every zip-shaped file
    the scanner encounters, so it must reject an oversized entry via the
    cheap declared-size check BEFORE ever attempting to open/decompress
    it, staying bounded regardless of how large the entry's real content
    is.

    To prove this structurally rather than asserting on timing (which
    would be fragile) - and without relying on an exception that would be
    silently swallowed by _is_zip_shaped_document's own broad
    try/except (which would make a "raise if opened" assertion pass for
    the wrong reason under BOTH the old and new implementation) - this
    records whether zipfile.ZipFile.open() is ever invoked for the
    "mimetype" entry at all, without altering its behavior. Under the old,
    unbounded `zf.read("mimetype")` implementation this list would be
    non-empty (ZipFile.read() opens the entry internally before reading
    it fully); under the fixed implementation, the declared-size check
    rejects the entry before open() is ever reached, so the list stays
    empty.
    """
    from ssba.core.scanner import _is_zip_shaped_document

    # Highly compressible content: ~5MB of a repeated byte, deflated down
    # to a small on-disk size - moderately oversized (not maximally
    # extreme), but comfortably beyond any real mimetype value and enough
    # to demonstrate the bound matters (a naive zf.read("mimetype") would
    # decompress the full 5MB before ever comparing anything).
    oversized_mimetype = b"A" * (5 * 1024 * 1024)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", oversized_mimetype)
    data = buf.getvalue()

    opened_mimetype_entries: list[bool] = []
    original_open = zipfile.ZipFile.open

    def tracking_open(self, name, *args, **kwargs):
        entry_name = getattr(name, "filename", name)
        if entry_name == "mimetype":
            opened_mimetype_entries.append(True)
        return original_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", tracking_open)

    result = _is_zip_shaped_document(data)

    assert result is False
    assert opened_mimetype_entries == [], (
        "an oversized mimetype entry must be rejected via its declared "
        "size before ever being opened/decompressed at all - got "
        f"{len(opened_mimetype_entries)} open() call(s)"
    )


def _zip_bytes_with_bzip2_mimetype_and_lying_size(
    real_content: bytes, declared_size: int
) -> bytes:
    """Build a zip whose "mimetype" entry is BZIP2-compressed and whose
    declared (central-directory) uncompressed size lies: it claims
    `declared_size` bytes while the entry's real decompressed content is
    actually `len(real_content)` bytes.

    Used to prove that the "mimetype" peek's compress_type gate - not
    just its declared-size check - is what rejects non-DEFLATE/STORED
    entries: with a lying (small, in-bounds) declared size, the
    declared-size check alone would let this entry through, so only the
    compress_type check can be what stops it from being read.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_BZIP2) as zf:
        zf.writestr("mimetype", real_content)
    data = bytearray(buf.getvalue())

    cd_sig_offset = data.find(b"PK\x01\x02")
    assert cd_sig_offset != -1
    # Central directory file header: compression method at offset +10,
    # uncompressed size at offset +24 (both relative to the signature).
    assert data[cd_sig_offset + 10 : cd_sig_offset + 12] == struct.pack(
        "<H", zipfile.ZIP_BZIP2
    )
    data[cd_sig_offset + 24 : cd_sig_offset + 28] = struct.pack("<I", declared_size)
    return bytes(data)


def test_is_zip_shaped_document_rejects_bzip2_mimetype_entry_with_lying_size(monkeypatch):
    """Follow-up to the DEFLATE bomb test above: the declared-size check
    plus a bounded zf.open().read(N) is NOT actually bounded "independent
    of declared size" for every compression method CPython's zipfile
    supports. ZipExtFile's bounded-decompression path only applies to the
    DEFLATE branch - for BZIP2/LZMA-compressed entries, zipfile
    decompresses the entry FULLY internally before truncating the result,
    so a forged declared size paired with BZIP2/LZMA compression could
    still force a large decompression even with a read cap in place
    (independently measured: a lying-size bzip2 entry reached ~437MB
    peak, lzma ~64MB, despite the .read(N) cap). The fix adds an explicit
    compress_type gate: only ZIP_STORED/ZIP_DEFLATED are ever opened/read
    at all; anything else (including BZIP2) is rejected outright.

    Builds a real BZIP2-compressed "mimetype" entry with moderately
    oversized (not maximally extreme) real content, whose declared
    central-directory size is forged down to a small, in-bounds value -
    so the declared-size check alone would NOT reject it. Proves the
    rejection the same structural way as the DEFLATE bomb test: records
    whether zipfile.ZipFile.open() is ever invoked for the "mimetype"
    entry, rather than asserting on timing.
    """
    from ssba.core.scanner import _is_zip_shaped_document

    real_content = b"B" * (2 * 1024 * 1024)  # 2MB, moderately oversized
    data = _zip_bytes_with_bzip2_mimetype_and_lying_size(real_content, declared_size=10)

    opened_mimetype_entries: list[bool] = []
    original_open = zipfile.ZipFile.open

    def tracking_open(self, name, *args, **kwargs):
        entry_name = getattr(name, "filename", name)
        if entry_name == "mimetype":
            opened_mimetype_entries.append(True)
        return original_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", tracking_open)

    result = _is_zip_shaped_document(data)

    assert result is False
    assert opened_mimetype_entries == [], (
        "a BZIP2-compressed mimetype entry must be rejected via its "
        "compress_type before ever being opened/decompressed at all, "
        "even with a lying declared size that passes the size check - "
        f"got {len(opened_mimetype_entries)} open() call(s)"
    )


def test_scan_category_undecodable_file(tmp_path):
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_C", KEY, out_dir)
    assert result.counts()["undecoded"] == 1
    assert (out_dir / "CATEGORY_C" / "mystery.bin").read_bytes() == bytes(range(256)) * 4


def test_scan_category_decrypt_to_zip(tmp_path):
    """Test the real-world case: decrypt a file that decrypts to a zip,
    then recursively extract and process entries inside (like Notes sdoc.bk).
    """
    _write_history_xml(tmp_path)

    # Create a small zip with mixed content
    inner_zip = _zip_bytes(
        {
            "nested.xml": b"<?xml version='1.0'?><doc/>",
            "data.json": b'{"key": "value"}',
        }
    )
    # Encrypt the zip bytes
    encrypted_zip = encrypt_iv_prefixed(inner_zip, KEY)

    (tmp_path / "CATEGORY_D").mkdir()
    (tmp_path / "CATEGORY_D" / "sdoc.bk").write_bytes(encrypted_zip)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_D", KEY, out_dir)
    counts = result.counts()

    # Should have: 1 decrypted (sdoc.bk itself, kind=zip) + 2 plaintext (nested entries)
    # No errors!
    assert counts["decrypted"] == 1, f"expected 1 decrypted, got {counts}"
    assert counts["plaintext_passthrough"] == 2, f"expected 2 plaintext, got {counts}"
    assert counts["error"] == 0, f"expected 0 errors, got {counts}"

    # Verify the nested entries exist and are correctly extracted
    assert (out_dir / "CATEGORY_D" / "sdoc.bk" / "nested.xml").exists()
    assert (out_dir / "CATEGORY_D" / "sdoc.bk" / "data.json").exists()
    assert b"doc" in (out_dir / "CATEGORY_D" / "sdoc.bk" / "nested.xml").read_bytes()


def test_scan_backup_end_to_end(tmp_path):
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"
    report = scan_backup(tmp_path, out_dir)
    assert [c.category for c in report.categories] == [
        "CATEGORY_A",
        "CATEGORY_B",
        "CATEGORY_C",
    ]
    totals = {"decrypted": 0, "plaintext_passthrough": 0, "undecoded": 0, "error": 0}
    for category in report.categories:
        for status, count in category.counts().items():
            totals[status] += count
    assert totals == {
        "decrypted": 2,
        "plaintext_passthrough": 2,
        "undecoded": 1,
        "error": 0,
    }


def test_scan_category_recurses_into_subdirectories(tmp_path):
    """Finding 1: 10 of 67 real categories (e.g. Photo/) store their content
    only in subdirectories, not directly inside the category folder. The
    scanner must walk recursively and preserve the relative path.
    """
    _write_history_xml(tmp_path)
    category_dir = tmp_path / "Photo"
    nested_dir = category_dir / "sub" / "deeper"
    nested_dir.mkdir(parents=True)
    plaintext = b"just some plain ascii text content here"
    (nested_dir / "pic.txt").write_bytes(encrypt_iv_prefixed(plaintext, KEY))

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "Photo", KEY, out_dir)

    assert result.counts()["decrypted"] == 1, f"file in subdirectory was never scanned: {result}"
    paths = [f.relative_path for f in result.files]
    assert paths == ["sub/deeper/pic.txt"]
    assert (out_dir / "Photo" / "sub" / "deeper" / "pic.txt").exists()


def test_scan_category_zip_slip_dotdot_sanitized(tmp_path):
    """Finding 2: a zip entry named with '../' segments must never escape
    out_dir when its path is built. Named CALLLOG.zip (a known Smart
    Switch container) so this actually gets recursed into under the
    catalog-based recursion policy.
    """
    _write_history_xml(tmp_path)
    malicious_zip = _zip_bytes({"../../../PWNED.txt": b"pwned content"})
    (tmp_path / "CATEGORY_E").mkdir()
    (tmp_path / "CATEGORY_E" / "CALLLOG.zip").write_bytes(malicious_zip)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_E", KEY, out_dir)

    # Nothing must ever land outside out_dir.
    assert not (tmp_path / "PWNED.txt").exists()
    assert not (tmp_path.parent / "PWNED.txt").exists()

    written = list(out_dir.rglob("PWNED.txt"))
    assert len(written) == 1, f"expected exactly one PWNED.txt under out_dir, found {written}"
    assert out_dir.resolve() in written[0].resolve().parents
    assert written[0].read_bytes() == b"pwned content"
    assert result.counts()["error"] == 0


def test_scan_category_zip_slip_backslash_sanitized(tmp_path):
    """Zip entry names should be '/'-separated per spec, but a hostile or
    Windows-built zip might use backslashes; those must be normalized and
    sanitized too, not treated as a literal (and harmless-looking, but
    still wrong) filename component. Named CALLLOG.zip (a known Smart
    Switch container) so this actually gets recursed into under the
    catalog-based recursion policy.
    """
    _write_history_xml(tmp_path)
    # 3 "up" segments: entry lives at out_dir/CATEGORY_H/CALLLOG.zip/<entry>,
    # so 3 ".." would reach tmp_path (one level above out_dir) if the
    # backslashes were not normalized/sanitized - a genuine escape, not a
    # coincidental match of directory depth.
    malicious_zip = _zip_bytes({"..\\..\\..\\evil.txt": b"evil content"})
    (tmp_path / "CATEGORY_H").mkdir()
    (tmp_path / "CATEGORY_H" / "CALLLOG.zip").write_bytes(malicious_zip)

    out_dir = tmp_path / "out"
    scan_category(tmp_path, "CATEGORY_H", KEY, out_dir)

    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path.parent / "evil.txt").exists()
    written = list(out_dir.rglob("evil.txt"))
    assert len(written) == 1
    assert out_dir.resolve() in written[0].resolve().parents


def test_scan_category_unreadable_file_does_not_crash_scan(tmp_path, monkeypatch):
    """Finding 3: a single unreadable source file (permission error, locked
    file, I/O error) must never abort the whole category/scan.
    """
    _build_fake_backup(tmp_path)
    out_dir = tmp_path / "out"

    bad_file = (tmp_path / "CATEGORY_A" / "data.exml").resolve()
    original_read_bytes = Path.read_bytes

    def flaky_read_bytes(self, *args, **kwargs):
        if self.resolve() == bad_file:
            raise PermissionError("simulated unreadable file")
        return original_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", flaky_read_bytes)

    result = scan_category(tmp_path, "CATEGORY_A", KEY, out_dir)

    assert result.counts()["error"] == 1
    assert result.files[0].status == "error"
    assert "data.exml" in result.files[0].relative_path


def _truncated_zip_bytes() -> bytes:
    good = _zip_bytes({"a.txt": b"hello world, this is a real zip entry"})
    # Chop off the back half: this destroys the end-of-central-directory
    # record while leaving the local-file-header zip magic at the start
    # intact, so sniff_kind still calls it a zip but zipfile.ZipFile()
    # cannot open it.
    corrupt = good[: len(good) // 2]
    assert corrupt.startswith(b"PK\x03\x04")
    return corrupt


def _zip_bytes_with_mangled_version_needed() -> bytes:
    """A structurally well-formed zip (valid magic, valid end-of-central-
    directory record) but with the central directory's "version needed to
    extract" field mangled to a bogus value. zipfile.ZipFile() reads this
    at construction time and raises NotImplementedError - not
    zipfile.BadZipFile - for zip file version fields it doesn't recognize.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", b"hello world")
    data = bytearray(buf.getvalue())
    eocd = data.rfind(b"PK\x05\x06")
    assert eocd != -1
    cd_offset = struct.unpack("<I", data[eocd + 16 : eocd + 20])[0]
    assert data[cd_offset : cd_offset + 4] == b"PK\x01\x02"
    # central directory file header: version needed to extract is the 2
    # bytes at offset +6 from the header signature.
    data[cd_offset + 6 : cd_offset + 8] = struct.pack("<H", 0xFFFF)
    return bytes(data)


def _zip_bytes_with_unsupported_compression() -> bytes:
    """A zip that opens fine (valid central directory, valid version-needed
    field) but whose single entry declares an unsupported compression
    method. zipfile.ZipFile() construction succeeds and infolist() works,
    but zf.read() on that entry raises NotImplementedError.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("only.txt", b"some data that would normally compress just fine")
    data = bytearray(buf.getvalue())
    assert data[0:4] == b"PK\x03\x04"
    # Local file header: compression method is the 2 bytes at offset +8.
    data[8:10] = struct.pack("<H", 99)
    cd_sig_offset = data.find(b"PK\x01\x02")
    assert cd_sig_offset != -1
    # Central directory file header: compression method at offset +10.
    data[cd_sig_offset + 10 : cd_sig_offset + 12] = struct.pack("<H", 99)
    return bytes(data)


def test_scan_category_zip_construction_notimplementederror_single_result_and_fallback_write(
    tmp_path,
):
    """Finding 5, scenario 1: zipfile.ZipFile() can raise exceptions other
    than BadZipFile for malformed input - confirmed reproducible with a
    mangled "version needed to extract" field, which raises
    NotImplementedError at construction time. That must be treated the
    same as any other corrupt/unsupported zip: exactly one FileResult, and
    the original bytes written as a fallback rather than silently lost.
    Named CALLLOG.zip (a known Smart Switch container) so recursion is
    actually attempted under the catalog-based recursion policy - this
    corrupt-zip handling only runs once recursion is attempted at all.
    """
    _write_history_xml(tmp_path)
    corrupt = _zip_bytes_with_mangled_version_needed()
    (tmp_path / "CATEGORY_J").mkdir()
    (tmp_path / "CATEGORY_J" / "CALLLOG.zip").write_bytes(corrupt)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_J", KEY, out_dir)

    matching = [f for f in result.files if f.relative_path == "CALLLOG.zip"]
    assert len(matching) == 1, f"expected exactly one FileResult, got {matching}"
    assert matching[0].status == "error"
    written = out_dir / "CATEGORY_J" / "CALLLOG.zip"
    assert written.exists(), "original bytes must be written, not discarded"
    assert written.read_bytes() == corrupt


def test_scan_category_zip_entry_unsupported_compression_container_fallback(tmp_path):
    """Finding 5, scenario 2: the zip itself opens fine, but its only entry
    uses an unsupported compression method. zf.read() on that entry raises
    NotImplementedError, which the existing per-entry try/except correctly
    isolates as its own 'error' FileResult - but since that's the zip's
    only entry, nothing at all ends up written for the container's own
    path, so the container must not still be reported as a success
    ('plaintext_passthrough') with nothing on disk to show for it. Named
    CALLLOG.zip (a known Smart Switch container) so recursion is actually
    attempted under the catalog-based recursion policy.
    """
    _write_history_xml(tmp_path)
    corrupt = _zip_bytes_with_unsupported_compression()
    (tmp_path / "CATEGORY_K").mkdir()
    (tmp_path / "CATEGORY_K" / "CALLLOG.zip").write_bytes(corrupt)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_K", KEY, out_dir)

    matching = [f for f in result.files if f.relative_path == "CALLLOG.zip"]
    assert len(matching) == 1, (
        f"expected exactly one FileResult for the container path, got {matching}"
    )
    assert matching[0].status == "error"
    written = out_dir / "CATEGORY_K" / "CALLLOG.zip"
    assert written.exists(), (
        "container bytes must be written when nothing inside the zip could be extracted"
    )
    assert written.read_bytes() == corrupt


def test_scan_category_corrupt_raw_zip_single_result_and_fallback_write(tmp_path):
    """Finding 4, scenario 1: a raw file has zip magic bytes but a corrupt
    body. Exactly one FileResult must be recorded for it, and its bytes
    must be written somewhere rather than silently lost. Named CALLLOG.zip
    (a known Smart Switch container) so recursion is actually attempted
    under the catalog-based recursion policy - without that, this
    filename wouldn't be recursed into at all any more, and this test
    would stop exercising the corrupt-zip fallback path it's named for.
    """
    _write_history_xml(tmp_path)
    corrupt = _truncated_zip_bytes()
    (tmp_path / "CATEGORY_F").mkdir()
    (tmp_path / "CATEGORY_F" / "CALLLOG.zip").write_bytes(corrupt)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_F", KEY, out_dir)

    matching = [f for f in result.files if f.relative_path == "CALLLOG.zip"]
    assert len(matching) == 1, f"expected exactly one FileResult, got {matching}"
    written = out_dir / "CATEGORY_F" / "CALLLOG.zip"
    assert written.exists(), "corrupt zip's original bytes must be written, not discarded"
    assert written.read_bytes() == corrupt


def test_scan_category_corrupt_decrypted_zip_single_result_and_fallback_write(tmp_path):
    """Finding 4, scenario 2: the file decrypts successfully, and the
    decrypted result is a zip, but that zip is itself corrupt.
    """
    _write_history_xml(tmp_path)
    corrupt_inner = _truncated_zip_bytes()
    encrypted = encrypt_iv_prefixed(corrupt_inner, KEY)
    (tmp_path / "CATEGORY_G").mkdir()
    (tmp_path / "CATEGORY_G" / "sdoc.bk").write_bytes(encrypted)

    out_dir = tmp_path / "out"
    result = scan_category(tmp_path, "CATEGORY_G", KEY, out_dir)

    matching = [f for f in result.files if f.relative_path == "sdoc.bk"]
    assert len(matching) == 1, f"expected exactly one FileResult, got {matching}"
    written = out_dir / "CATEGORY_G" / "sdoc.bk"
    assert written.exists(), "corrupt decrypted zip bytes must be written, not discarded"
    # decrypt_iv_prefixed doesn't strip the zero-byte block padding applied
    # by encrypt_iv_prefixed, so the written (decrypted) bytes are
    # corrupt_inner plus zero padding up to the next 16-byte boundary, not
    # byte-for-byte identical to corrupt_inner.
    pad_len = (-len(corrupt_inner)) % 16
    assert written.read_bytes() == corrupt_inner + b"\x00" * pad_len
