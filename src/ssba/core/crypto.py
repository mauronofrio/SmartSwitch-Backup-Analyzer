"""AES primitives for Samsung Smart Switch's backup encryption scheme."""

from __future__ import annotations

import hashlib

from Crypto.Cipher import AES

FIXED_DUMMY_ECB_KEY: bytes = b"0b1e96db05d64ea4"


def derive_key(session_dummy: str) -> bytes:
    """Derive the AES-128 key used for a backup's encrypted payloads.

    The key is the first 16 bytes of SHA-256 of the session dummy string
    (itself recovered via decrypt_dummy_ecb).
    """
    return hashlib.sha256(session_dummy.encode("utf-8")).digest()[:16]


def decrypt_iv_prefixed(raw: bytes, key: bytes) -> bytes:
    """Decrypt a Smart Switch payload: first 16 bytes are the IV, the rest
    is AES-128-CBC ciphertext (truncated to a whole number of blocks).

    Real backups use PKCS#7 padding, which is removed. It is kept when it is
    not valid PKCS#7 (some apps zero-pad instead) or when the ciphertext was
    cut off, since then the last whole block is not the real last block.
    """
    if len(raw) < 32:
        raise ValueError("payload too small to contain an IV and ciphertext")
    iv = raw[:16]
    ciphertext = raw[16:]
    aligned_len = len(ciphertext) - (len(ciphertext) % 16)
    ciphertext = ciphertext[:aligned_len]
    if not ciphertext:
        raise ValueError("no AES-block-aligned ciphertext after the IV")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plaintext = cipher.decrypt(ciphertext)
    if aligned_len == len(raw) - 16:
        pad_len = plaintext[-1]
        if 1 <= pad_len <= 16 and plaintext.endswith(bytes([pad_len]) * pad_len):
            return plaintext[:-pad_len]
    return plaintext


def decrypt_dummy_ecb(ciphertext_hex: str) -> str:
    """Decrypt the <Dummy> element of backupHistoryInfo.xml.

    It is AES-128-ECB ciphertext (fixed key, hex-encoded), zero-padded.
    Returns the plaintext session dummy as a hex string.
    """
    try:
        ciphertext = bytes.fromhex(ciphertext_hex)
    except ValueError as exc:
        raise ValueError("Dummy value is not valid hexadecimal") from exc
    if not ciphertext or len(ciphertext) % 16 != 0:
        raise ValueError(
            "Dummy ciphertext is not a non-empty multiple of the AES block size"
        )
    cipher = AES.new(FIXED_DUMMY_ECB_KEY, AES.MODE_ECB)
    plaintext = cipher.decrypt(ciphertext).rstrip(b"\x00")
    try:
        text = plaintext.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("decrypted Dummy is not ASCII") from exc
    if not (32 <= len(text) <= 128) or len(text) % 2 != 0:
        raise ValueError(f"decrypted Dummy has an unexpected length ({len(text)})")
    if any(c not in "0123456789abcdefABCDEF" for c in text):
        raise ValueError("decrypted Dummy is not hexadecimal")
    return text
