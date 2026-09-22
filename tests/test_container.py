from __future__ import annotations

from ssba.core.container import decrypt_file, sniff_kind
from ssba.core.crypto import derive_key
from tests.crypto_helpers import encrypt_iv_prefixed

KEY = derive_key("AABBCCDDEEFF00112233445566778899AABB")


def test_sniff_kind_zip():
    assert sniff_kind(b"PK\x03\x04rest of a fake zip") == "zip"


def test_sniff_kind_sqlite():
    assert sniff_kind(b"SQLite format 3\x00rest") == "sqlite"


def test_sniff_kind_xml():
    assert sniff_kind(b"<?xml version='1.0'?><root/>") == "xml"


def test_sniff_kind_json_object():
    assert sniff_kind(b'{"a": 1}') == "json"


def test_sniff_kind_json_array():
    assert sniff_kind(b"[1, 2, 3]") == "json"


def test_sniff_kind_media_jpeg():
    assert sniff_kind(b"\xff\xd8\xff\xe0rest of jpeg") == "media"


def test_sniff_kind_media_png():
    assert sniff_kind(b"\x89PNG\r\n\x1a\nrest") == "media"


def test_sniff_kind_text():
    assert sniff_kind(b"just some plain ascii text content here") == "text"


def test_sniff_kind_binary_fallback():
    assert sniff_kind(bytes(range(256))) == "binary"


def test_sniff_kind_empty():
    assert sniff_kind(b"") == "binary"


def test_sniff_kind_binary_starts_with_xml_tag():
    """Test that binary data starting with < but mostly non-printable is classified as binary.

    This reproduces the bug where pseudorandom AES-CBC output (from decrypting
    non-encrypted .page binary files) gets misclassified as XML just because
    it happens to start with < and contain > somewhere.
    """
    # Binary data starting with < and containing > but mostly non-printable
    data = b"<" + bytes(range(200))
    assert sniff_kind(data) == "binary", (
        "Binary data starting with < should be classified as binary, "
        "not XML, even if it contains >"
    )


def test_sniff_kind_binary_starts_with_json_brace():
    """Test that binary data starting with { but mostly non-printable is classified as binary."""
    data = b"{" + bytes(range(200))
    assert sniff_kind(data) == "binary", (
        "Binary data starting with { should be classified as binary, "
        "not JSON"
    )


def test_decrypt_file_recovers_xml():
    plaintext = b"<?xml version='1.0'?><CallLogs></CallLogs>"
    raw = encrypt_iv_prefixed(plaintext, KEY)
    blob = decrypt_file(raw, KEY)
    assert blob.kind == "xml"
    assert blob.data.startswith(plaintext)
