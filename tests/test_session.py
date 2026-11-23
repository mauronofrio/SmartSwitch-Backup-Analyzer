from __future__ import annotations

import os

import pytest

import zipfile

from ssba.core.errors import UnsupportedBackupError
from ssba.core.session import get_session_dummy
from tests.crypto_helpers import encrypt_dummy_ecb, encrypt_ssm_dummy_exml


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


def test_get_session_dummy_permission_error(tmp_path):
    # Create a file that passes is_file() but raises OSError on read
    tmp_path.mkdir(parents=True, exist_ok=True)
    file_path = tmp_path / "backupHistoryInfo.xml"
    file_path.write_text("<test/>", encoding="utf-8")

    # Remove read permissions to trigger PermissionError when ET.parse opens it
    os.chmod(file_path, 0o000)

    try:
        with pytest.raises(UnsupportedBackupError):
            get_session_dummy(tmp_path)
    finally:
        # Restore permissions so cleanup doesn't fail
        os.chmod(file_path, 0o644)


def test_get_session_dummy_falls_back_to_ssm_dummy_exml(tmp_path):
    # Non-ECB <Dummy> (e.g., Android 15 / One UI 7+ backupHistoryInfo.xml)
    _write_history_xml(tmp_path, "AA" * 48)
    snote_dir = tmp_path / "SAMSUNGNOTE"
    snote_dir.mkdir()
    with zipfile.ZipFile(snote_dir / "SamsungNote.SNMM", "w") as zf:
        zf.writestr("SSMDummyValue.exml", encrypt_ssm_dummy_exml(FAKE_DUMMY))

    assert get_session_dummy(tmp_path) == FAKE_DUMMY
