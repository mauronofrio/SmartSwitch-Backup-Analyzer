"""A small fabricated Smart Switch backup for GUI tests - no real data."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from tests.crypto_helpers import encrypt_dummy_ecb
from tests.discovery_fixtures import write_history

FAKE_DUMMY = "AABBCCDDEEFF00112233445566778899AABB"
JPEG = b"\xff\xd8\xff\xe0 fake jpeg"
ALARM_XML = b"<Alarms><alarm><active>1</active><alarmtime>530</alarmtime></alarm></Alarms>"


def build_backup(root: Path) -> Path:
    folder = write_history(
        root / "SM-X" / "SM-X_" / "SM-X_1",
        dummy=encrypt_dummy_ecb(FAKE_DUMMY),
        items=(("ALARM\\ALARM.zip", 1), ("Photo\\Photo.zip", 1)),
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("alarm.exml", ALARM_XML)
    (folder / "ALARM").mkdir()
    (folder / "ALARM" / "ALARM.zip").write_bytes(buf.getvalue())
    (folder / "Photo" / "DCIM" / "Camera").mkdir(parents=True)
    (folder / "Photo" / "DCIM" / "Camera" / "a.jpg").write_bytes(JPEG)
    return folder
