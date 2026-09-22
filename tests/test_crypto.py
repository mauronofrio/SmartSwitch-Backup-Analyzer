from __future__ import annotations

import hashlib

import pytest

from ssba.core.crypto import decrypt_dummy_ecb, decrypt_iv_prefixed, derive_key
from tests.crypto_helpers import encrypt_dummy_ecb, encrypt_iv_prefixed

FAKE_DUMMY = "AABBCCDDEEFF00112233445566778899AABB"


def test_derive_key_matches_formula():
    key = derive_key(FAKE_DUMMY)
    expected = hashlib.sha256(FAKE_DUMMY.encode("utf-8")).digest()[:16]
    assert key == expected
    assert len(key) == 16


def test_decrypt_iv_prefixed_round_trip():
    key = derive_key(FAKE_DUMMY)
    plaintext = b"hello smart switch, this is a fake payload!!!!"
    raw = encrypt_iv_prefixed(plaintext, key)
    decrypted = decrypt_iv_prefixed(raw, key)
    assert decrypted.startswith(plaintext)


def test_decrypt_iv_prefixed_rejects_too_short_payload():
    with pytest.raises(ValueError):
        decrypt_iv_prefixed(b"short", b"0" * 16)


def test_decrypt_dummy_ecb_round_trip():
    ciphertext_hex = encrypt_dummy_ecb(FAKE_DUMMY)
    assert decrypt_dummy_ecb(ciphertext_hex) == FAKE_DUMMY


def test_decrypt_dummy_ecb_rejects_bad_hex():
    with pytest.raises(ValueError):
        decrypt_dummy_ecb("not-hex-at-all")


def test_decrypt_dummy_ecb_rejects_wrong_block_size():
    with pytest.raises(ValueError):
        decrypt_dummy_ecb("aabbcc")
