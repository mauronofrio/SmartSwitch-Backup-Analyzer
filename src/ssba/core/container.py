"""Decrypt a single Smart Switch payload and identify what it decoded to."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ssba.core.crypto import decrypt_iv_prefixed

Kind = Literal["zip", "sqlite", "xml", "json", "text", "media", "binary"]

ZIP_MAGIC = b"PK\x03\x04"
SQLITE_MAGIC = b"SQLite format 3\x00"
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
GIF_MAGICS = (b"GIF87a", b"GIF89a")
PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True)
class DecodedBlob:
    data: bytes
    kind: Kind


def sniff_kind(data: bytes) -> Kind:
    if data.startswith(ZIP_MAGIC):
        return "zip"
    if data.startswith(SQLITE_MAGIC):
        return "sqlite"
    if (
        data.startswith(JPEG_MAGIC)
        or data.startswith(PNG_MAGIC)
        or data.startswith(GIF_MAGICS)
        or data.startswith(PDF_MAGIC)
    ):
        return "media"

    # Strip trailing null bytes (from AES-CBC zero-byte padding) and any
    # leading/trailing whitespace, to ensure the text-detection check is accurate
    stripped = data.strip(b"\x00 \t\n\r\x0b\x0c")
    head = stripped[:256]
    if not head:
        return "binary"
    # Real backup content (Notes, Contacts, ...) is frequently non-ASCII
    # (accented Latin, CJK, etc.), so an ASCII printable-byte-range check
    # produces false negatives on genuine decrypted plaintext. Strict UTF-8
    # validity is a much stronger signal: pseudorandom AES output essentially
    # never decodes as valid UTF-8, while real UTF-8 text (ASCII or not)
    # always does.
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        # `head` is a raw byte slice taken before decoding, so a multi-byte
        # UTF-8 character can straddle the 256-byte cut. That produces a
        # UnicodeDecodeError on the truncated trailing bytes even when the
        # full content (and the untruncated prefix of this very slice) is
        # perfectly valid UTF-8. A genuine truncated sequence can only start
        # within the last 3 bytes of head (the longest continuation run),
        # so retry decoding just the prefix before the cut; if that prefix
        # decodes cleanly, the gate passes. An error further back in the
        # slice means the content is genuinely invalid UTF-8.
        if exc.start >= len(head) - 3:
            try:
                head[: exc.start].decode("utf-8")
            except UnicodeDecodeError:
                return "binary"
        else:
            return "binary"

    if stripped[:5] == b"<?xml" or (stripped[:1] == b"<" and b">" in stripped[:256]):
        return "xml"
    if stripped[:1] in (b"{", b"["):
        return "json"
    return "text"


def decrypt_file(raw: bytes, key: bytes) -> DecodedBlob:
    """Decrypt raw (IV-prefixed AES-128-CBC) and identify the result.

    Raises ValueError (from decrypt_iv_prefixed) if raw is too small to be
    a valid IV+ciphertext payload.
    """
    plaintext = decrypt_iv_prefixed(raw, key)
    return DecodedBlob(data=plaintext, kind=sniff_kind(plaintext))
