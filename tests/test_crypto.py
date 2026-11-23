from __future__ import annotations

import hashlib

import pytest

from ssba.core.crypto import (
    decrypt_dummy_ecb,
    decrypt_iv_prefixed,
    decrypt_ssm_dummy_exml,
    derive_key,
)
from tests.crypto_helpers import (
    encrypt_dummy_ecb,
    encrypt_iv_prefixed,
    encrypt_iv_prefixed_pkcs7,
    encrypt_ssm_dummy_exml,
)


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


@pytest.mark.parametrize("length", [0, 1, 15, 16, 17, 47])
def test_decrypt_iv_prefixed_strips_pkcs7_padding(length):
    key = derive_key(FAKE_DUMMY)
    plaintext = bytes(range(length))
    assert decrypt_iv_prefixed(encrypt_iv_prefixed_pkcs7(plaintext, key), key) == plaintext


def test_decrypt_iv_prefixed_keeps_zero_padding():
    key = derive_key(FAKE_DUMMY)
    decrypted = decrypt_iv_prefixed(encrypt_iv_prefixed(b"<a/>", key), key)
    assert decrypted == b"<a/>" + b"\x00" * 12


def test_decrypt_iv_prefixed_keeps_a_tail_that_is_not_valid_pkcs7():
    key = derive_key(FAKE_DUMMY)
    plaintext = b"0123456789abc\x03\x02\x03"
    assert decrypt_iv_prefixed(encrypt_iv_prefixed(plaintext, key), key) == plaintext


def test_decrypt_iv_prefixed_keeps_padding_of_a_truncated_ciphertext():
    # A cut-off file's last whole block is not its real last block, so what
    # looks like padding there is content.
    key = derive_key(FAKE_DUMMY)
    plaintext = b"0123456789abcdef0123456789abcd\x02\x02"
    raw = encrypt_iv_prefixed_pkcs7(plaintext, key)[:-16] + b"cut"
    assert decrypt_iv_prefixed(raw, key) == plaintext


def test_decrypt_dummy_ecb_round_trip():
    ciphertext_hex = encrypt_dummy_ecb(FAKE_DUMMY)
    assert decrypt_dummy_ecb(ciphertext_hex) == FAKE_DUMMY


def test_decrypt_dummy_ecb_rejects_bad_hex():
    with pytest.raises(ValueError):
        decrypt_dummy_ecb("not-hex-at-all")


def test_decrypt_dummy_ecb_rejects_wrong_block_size():
    with pytest.raises(ValueError):
        decrypt_dummy_ecb("aabbcc")


def test_decrypt_ssm_dummy_exml_round_trip():
    raw = encrypt_ssm_dummy_exml(FAKE_DUMMY)
    assert decrypt_ssm_dummy_exml(raw) == FAKE_DUMMY


def test_decrypt_ssm_dummy_exml_rejects_wrong_block_size():
    with pytest.raises(ValueError):
        decrypt_ssm_dummy_exml(b"short")
