"""Locate and decrypt a Smart Switch backup's per-session key material."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
import zipfile

from ssba.core.crypto import decrypt_dummy_ecb, decrypt_ssm_dummy_exml
from ssba.core.errors import UnsupportedBackupError


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def get_session_dummy(backup_root: Path) -> str:
    """Read backupHistoryInfo.xml under backup_root and return the
    decrypted session dummy string.
    """
    history_path = backup_root / "backupHistoryInfo.xml"
    if not history_path.is_file():
        raise UnsupportedBackupError(
            f"backupHistoryInfo.xml not found under {backup_root}"
        )
    try:
        tree = ET.parse(history_path)
    except ET.ParseError as exc:
        raise UnsupportedBackupError(
            f"backupHistoryInfo.xml is not valid XML: {exc}"
        ) from exc
    except OSError as exc:
        raise UnsupportedBackupError(
            f"could not read backupHistoryInfo.xml: {exc}"
        ) from exc

    dummy_elements = [
        element
        for element in tree.iter()
        if _local_name(element.tag) == "Dummy" and (element.text or "").strip()
    ]
    if len(dummy_elements) != 1:
        raise UnsupportedBackupError(
            "expected exactly one <Dummy> element in backupHistoryInfo.xml, "
            f"found {len(dummy_elements)}"
        )

    ciphertext_hex = dummy_elements[0].text.strip()
    try:
        return decrypt_dummy_ecb(ciphertext_hex)
    except ValueError as exc:
        try:
            ssm_dummy = _fallback_ssm_dummy(backup_root)
        except ValueError:
            ssm_dummy = None
        if ssm_dummy is not None:
            return ssm_dummy
        raise UnsupportedBackupError(
            f"could not decrypt the session Dummy value: {exc}"
        ) from exc



def _fallback_ssm_dummy(backup_root: Path) -> str | None:
    """Look for SSMDummyValue.exml inside SAMSUNGNOTE/*.SNMM (used in One UI 7 /
    Android 15+ backups where backupHistoryInfo.xml <Dummy> is not ECB-encrypted).
    """
    snote_dir = backup_root / "SAMSUNGNOTE"
    if not snote_dir.is_dir():
        return None
    for candidate in snote_dir.iterdir():
        if candidate.suffix.lower() == ".snmm" and zipfile.is_zipfile(candidate):
            with zipfile.ZipFile(candidate, "r") as zf:
                for member in zf.namelist():
                    if Path(member).name.lower() == "ssmdummyvalue.exml":
                        return decrypt_ssm_dummy_exml(zf.read(member))
    return None
