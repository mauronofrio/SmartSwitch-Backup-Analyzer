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


def test_sniff_kind_xml_with_trailing_null_padding():
    """Test that XML with trailing null-byte padding is correctly classified as XML.

    decrypt_iv_prefixed doesn't strip AES padding, and this project's padding scheme
    is zero-byte (see tests/crypto_helpers.py), so short genuine XML content often
    arrives with trailing \x00 bytes. This test ensures the printable-ratio check
    is computed on stripped data so legitimate content isn't rejected by padding.
    """
    assert sniff_kind(b"<a/>" + b"\x00" * 12) == "xml"


def test_sniff_kind_json_with_trailing_null_padding():
    """Test that JSON with trailing null-byte padding is correctly classified as JSON."""
    assert sniff_kind(b'{"a":1}' + b"\x00" * 9) == "json"


def test_decrypt_file_recovers_xml():
    plaintext = b"<?xml version='1.0'?><CallLogs></CallLogs>"
    raw = encrypt_iv_prefixed(plaintext, KEY)
    blob = decrypt_file(raw, KEY)
    assert blob.kind == "xml"
    assert blob.data.startswith(plaintext)


def test_sniff_kind_accented_latin_text():
    """Real Samsung Notes/Contacts content routinely contains accented Latin
    characters (e.g. names like 'Frédéric', 'José'). The old ASCII-range
    printable check (32 <= b < 127) rejected these as binary, causing the
    scanner to discard correctly-decrypted plaintext and write raw
    ciphertext instead.
    """
    text = "Café con José y Frédéric, très bien!".encode("utf-8")
    assert sniff_kind(text) == "text"


def test_sniff_kind_cjk_text():
    text = "こんにちは世界 你好世界".encode("utf-8")
    assert sniff_kind(text) == "text"


def test_sniff_kind_xml_with_non_ascii_content():
    xml = "<?xml version='1.0'?><note>café 世界</note>".encode("utf-8")
    assert sniff_kind(xml) == "xml"


def test_sniff_kind_json_with_non_ascii_content():
    payload = '{"name": "José", "greeting": "こんにちは"}'.encode("utf-8")
    assert sniff_kind(payload) == "json"


def test_sniff_kind_invalid_utf8_still_binary():
    """Pseudorandom AES output should essentially never decode as valid
    UTF-8, so it must still be classified as binary after the fix.
    """
    # 0x80-0xBF are UTF-8 continuation bytes; a run of them with no leading
    # byte is not valid UTF-8.
    data = bytes([0xFF, 0xFE, 0x80, 0x81, 0x82, 0x83] * 40)
    assert sniff_kind(data) == "binary"


def test_sniff_kind_long_cjk_text_over_256_bytes():
    """The UTF-8 validity gate slices the first 256 bytes of the (stripped)
    content BEFORE decoding. If a multi-byte UTF-8 character straddles that
    256-byte boundary, decoding the raw slice raises UnicodeDecodeError on
    the truncated trailing bytes even though the full content is perfectly
    valid UTF-8. Realistic CJK content well over 256 bytes must still be
    classified as text, not binary, regardless of where the cut lands.
    """
    sentence = "こんにちは世界、今日はとても良い天気ですね。お元気ですか。"
    text = (sentence * 5).encode("utf-8")
    assert len(text) > 300
    assert sniff_kind(text) == "text"


def test_sniff_kind_long_accented_text_over_256_bytes():
    """Same boundary-truncation bug, but for accented Latin text where the
    2-byte UTF-8 sequences are less dense than CJK, making it more likely a
    cut lands mid-character somewhere within a long run of content.
    """
    sentence = "Café con José y Frédéric, très bien! Ça va très bien, mêmes amis. "
    text = (sentence * 6).encode("utf-8")
    assert len(text) > 300
    assert sniff_kind(text) == "text"
