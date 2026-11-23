"""Test-only helpers to build synthetic Smart Switch-shaped ciphertext.

Nothing here uses real backup data - everything is fabricated so the test
suite can run without a real Smart Switch backup.
"""

from __future__ import annotations

import os

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from ssba.core.crypto import FIXED_DUMMY_ECB_KEY, BNR_CHAIN_IV, BNR_SECURITY_KEY


def encrypt_iv_prefixed(plaintext: bytes, key: bytes, iv: bytes | None = None) -> bytes:
    """Inverse of ssba.core.crypto.decrypt_iv_prefixed, for building fixtures."""
    iv = iv or os.urandom(16)
    pad_len = (-len(plaintext)) % 16
    padded = plaintext + b"\x00" * pad_len
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return iv + cipher.encrypt(padded)


def encrypt_dummy_ecb(session_dummy: str) -> str:
    """Inverse of ssba.core.crypto.decrypt_dummy_ecb, for building fixtures."""
    plaintext = session_dummy.encode("ascii")
    pad_len = (-len(plaintext)) % 16
    padded = plaintext + b"\x00" * pad_len
    cipher = AES.new(FIXED_DUMMY_ECB_KEY, AES.MODE_ECB)
    return cipher.encrypt(padded).hex()


def encrypt_ssm_dummy_exml(session_dummy: str) -> bytes:
    """Encrypt a fake session dummy string into SSMDummyValue.exml format."""
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<SSM_DummyValue>{session_dummy}</SSM_DummyValue>"
    ).encode("utf-8")
    cipher = AES.new(BNR_SECURITY_KEY, AES.MODE_CBC, BNR_CHAIN_IV)
    return cipher.encrypt(pad(xml, 16))


def encrypt_iv_prefixed_pkcs7(plaintext: bytes, key: bytes) -> bytes:
    """Like encrypt_iv_prefixed, but with the PKCS#7 padding real backups use."""
    iv = os.urandom(16)
    pad_len = 16 - len(plaintext) % 16
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return iv + cipher.encrypt(plaintext + bytes([pad_len]) * pad_len)
