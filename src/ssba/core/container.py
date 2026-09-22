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

    stripped = data.lstrip()
    if stripped[:5] == b"<?xml" or (stripped[:1] == b"<" and b">" in stripped[:256]):
        return "xml"
    if stripped[:1] in (b"{", b"["):
        return "json"

    head = data[:256]
    if head:
        printable = sum(1 for b in head if 32 <= b < 127 or b in (9, 10, 13))
        if printable / len(head) >= 0.95:
            return "text"

    return "binary"


def decrypt_file(raw: bytes, key: bytes) -> DecodedBlob:
    """Decrypt raw (IV-prefixed AES-128-CBC) and identify the result.

    Raises ValueError (from decrypt_iv_prefixed) if raw is too small to be
    a valid IV+ciphertext payload.
    """
    plaintext = decrypt_iv_prefixed(raw, key)
    return DecodedBlob(data=plaintext, kind=sniff_kind(plaintext))
