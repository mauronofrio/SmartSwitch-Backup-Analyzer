"""Find the Smart Switch backups on this PC and read their summary."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ssba.core.errors import UnsupportedBackupError

HISTORY_FILE = "backupHistoryInfo.xml"
# <root>\<model>\<model>_<n>\<model>_<timestamp>\backupHistoryInfo.xml
_MAX_DEPTH = 3


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    device_name: str
    model: str
    saved_at: datetime | None
    size: int | None
    items: dict[str, int] = field(default_factory=dict)  # category folder -> items


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]  # the file uses the "Kies.Common.Data" namespace


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _int(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def _time(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _summary(folder: Path, xml: Path) -> BackupInfo:
    try:
        root = ET.parse(xml).getroot()
    except (OSError, ET.ParseError):
        return BackupInfo(folder, "", folder.name, None, None, {})
    bundle = next((e for e in root.iter() if _local(e.tag) == "BundleInfo"), root)
    items: dict[str, int] = {}
    for element in root.iter():
        if _local(element.tag) != "BatchInformation":
            continue
        top = _child_text(element, "FileName").replace("\\", "/").split("/")[0]
        count = _int(_child_text(element, "ItemsCount"))
        if top and count is not None:
            items[top] = items.get(top, 0) + count
    return BackupInfo(
        path=folder,
        device_name=_child_text(bundle, "UserInputName"),
        model=_child_text(bundle, "ModelName") or folder.name,
        saved_at=_time(_child_text(bundle, "SavedTime")),
        size=_int(_child_text(bundle, "FileSize")),
        items=items,
    )


def read_backup(path: Path) -> BackupInfo:
    xml = path / HISTORY_FILE
    if not xml.is_file():
        raise UnsupportedBackupError(f"{path} is not a Smart Switch backup folder (no {HISTORY_FILE})")
    return _summary(path, xml)


def default_roots() -> list[Path]:
    home = Path.home()
    candidates = [
        home / "Samsung" / "SmartSwitch" / "backup",
        home / "Documents" / "Samsung" / "SmartSwitch" / "backup",
    ]
    return [c for c in candidates if c.is_dir()]


def _folders(folder: Path, depth: int) -> Iterator[Path]:
    yield folder
    if depth == 0:
        return
    try:
        children = sorted(p for p in folder.iterdir() if p.is_dir())
    except OSError:
        return
    for child in children:
        yield from _folders(child, depth - 1)


def find_backups(roots: list[Path] | None = None) -> list[BackupInfo]:
    """Every backup at most three folders below a root, newest first."""
    found: dict[Path, BackupInfo] = {}
    for root in default_roots() if roots is None else roots:
        if not root.is_dir():
            continue
        for folder in _folders(root, _MAX_DEPTH):
            xml = folder / HISTORY_FILE
            if xml.is_file():
                found.setdefault(folder.resolve(), _summary(folder, xml))
    return sorted(
        found.values(),
        key=lambda b: (b.saved_at is None, -b.saved_at.timestamp() if b.saved_at else 0.0, str(b.path)),
    )


def format_size(size: int | None) -> str:
    if size is None:
        return "?"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
