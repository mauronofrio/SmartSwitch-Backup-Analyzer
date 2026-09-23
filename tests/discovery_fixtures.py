"""Fabricated backupHistoryInfo.xml files for tests - no real data."""

from __future__ import annotations

from pathlib import Path


def write_history(folder: Path, *, model="SM-X", name="Telefono", saved="2026-01-02T03:04:05",
                  size=1234, items=(("CONTACT\\Contact.spbm", 3),), dummy="") -> Path:
    batches = "".join(
        "<BatchInformation><BNRInformation><BnRType>platform</BnRType></BNRInformation>"
        f"<FileName>{file_name}</FileName><ItemsCount>{count}</ItemsCount></BatchInformation>"
        for file_name, count in items
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" ?>'
        '<BatchInfomationItem xmlns="Kies.Common.Data"><BundleInfo>'
        f"<FileSize>{size}</FileSize><UserInputName>{name}</UserInputName>"
        f"<ModelName>{model}</ModelName><SavedTime>{saved}</SavedTime>"
        f"<PhoneNumber>000</PhoneNumber><Dummy>{dummy}</Dummy>"
        f"</BundleInfo><ItemsInfo>{batches}</ItemsInfo></BatchInfomationItem>"
    )
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "backupHistoryInfo.xml").write_text(xml, encoding="utf-8")
    return folder
