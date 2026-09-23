"""Fabricated Smart Switch file categories for tests - no real files."""

from __future__ import annotations

import json
from pathlib import Path

from tests.scan_fixtures import add_category, entry

T = 1600000000000  # ms
MANIFEST_DIR = "data/user/0/com.sec.android.easyMover/files/SmartSwitch/tmp"

# category -> {phone path inside the category: bytes}
FILES = {
    "Photo": {
        "DCIM/Camera/a.jpg": b"photo-a",
        "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/w.jpg": b"wa",
    },
    "Video": {"DCIM/Camera/v.mp4": b"video"},
    "Docs": {"Download/doc.pdf": b"pdf", "root.docx": b"docx"},
    "EtcFolder": {"Download/doc.pdf": b"pdf", "Download/only.ics": b"ics"},
    "PHOTO_ORIGIN": {
        "data/sec/photoeditor/0/storage/emulated/0/DCIM/Camera/a.jpg": b"original-a",
        "data/sec/photoeditor/0/flat.jpg": b"flat",
    },
}


def item(path: str, ms: int) -> dict:
    return {"FilePath": path, "FileName": path.rsplit("/", 1)[-1], "Length": 0, "DateModified": ms}


# category -> manifest entries
MANIFESTS = {
    "Photo": [item("/mnt/sdcard/DCIM/Camera/a.jpg", T), item("/mnt/sdcard/DCIM/Camera/gone.jpg", T)],
    "Docs": [item("/storage/emulated/0/Download/doc.pdf", T + 1000), item("/mnt/sdcard/root.docx", T + 2000)],
    "EtcFolder": [item("/mnt/sdcard/Download/doc.pdf", T + 9000), item("/mnt/sdcard/Download/only.ics", T + 3000)],
}


def build_files_scan_dir(scan_dir: Path, *, files=FILES, manifests=MANIFESTS, raw_manifests=None) -> Path:
    """Write fake category folders; ``raw_manifests`` maps a category to raw manifest text."""
    raw_manifests = raw_manifests or {}
    categories = list(dict.fromkeys([*files, *manifests, *raw_manifests]))
    for category in categories:
        root = scan_dir / category
        root.mkdir(parents=True, exist_ok=True)
        for rel, data in files.get(category, {}).items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        text = raw_manifests.get(category)
        if text is None and category in manifests:
            entries = manifests[category]
            text = json.dumps({"categoryType": category.upper(), "count": len(entries), "files": entries})
        if text is not None:
            manifest = root / MANIFEST_DIR / category.upper() / "list.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(text, encoding="utf-8")
        add_category(scan_dir, category, [entry("placeholder")])
    return scan_dir
