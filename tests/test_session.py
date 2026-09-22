from __future__ import annotations

import pytest

from ssba.core.errors import UnsupportedBackupError
from ssba.core.session import get_session_dummy
from tests.crypto_helpers import encrypt_dummy_ecb

FAKE_DUMMY = "AABBCCDDEEFF00112233445566778899AABB"


def _write_history_xml(backup_root, dummy_ciphertext_hex, tag_count=1):
    backup_root.mkdir(parents=True, exist_ok=True)
    dummy_tags = ""
    if dummy_ciphertext_hex is not None:
        dummy_tags = f"<Dummy>{dummy_ciphertext_hex}</Dummy>" * tag_count
    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<BatchInfomationItem xmlns="Kies.Common.Data">
    <BundleInfo>
        {dummy_tags}
    </BundleInfo>
</BatchInfomationItem>"""
    (backup_root / "backupHistoryInfo.xml").write_text(xml, encoding="utf-8")


def test_get_session_dummy_happy_path(tmp_path):
    ciphertext_hex = encrypt_dummy_ecb(FAKE_DUMMY)
    _write_history_xml(tmp_path, ciphertext_hex)
    assert get_session_dummy(tmp_path) == FAKE_DUMMY


def test_get_session_dummy_missing_file(tmp_path):
    with pytest.raises(UnsupportedBackupError):
        get_session_dummy(tmp_path)


def test_get_session_dummy_missing_dummy_element(tmp_path):
    _write_history_xml(tmp_path, dummy_ciphertext_hex=None)
    with pytest.raises(UnsupportedBackupError):
        get_session_dummy(tmp_path)


def test_get_session_dummy_multiple_dummy_elements(tmp_path):
    ciphertext_hex = encrypt_dummy_ecb(FAKE_DUMMY)
    _write_history_xml(tmp_path, ciphertext_hex, tag_count=2)
    with pytest.raises(UnsupportedBackupError):
        get_session_dummy(tmp_path)


def test_get_session_dummy_invalid_xml(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "backupHistoryInfo.xml").write_text("<not valid xml", encoding="utf-8")
    with pytest.raises(UnsupportedBackupError):
        get_session_dummy(tmp_path)
