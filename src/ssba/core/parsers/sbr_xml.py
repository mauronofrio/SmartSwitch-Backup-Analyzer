"""Shared rules for writing SMS Backup & Restore XML files."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# Characters XML 1.0 forbids even as character references.
_INVALID_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\uFFFE\uFFFF\ud800-\udfff]")


class TextCleaner:
    """Replace characters XML 1.0 forbids with U+FFFD, counting them."""

    def __init__(self) -> None:
        self.replaced = 0

    def __call__(self, text: str) -> str:
        cleaned, count = _INVALID_XML_CHARS.subn("\uFFFD", text)
        self.replaced += count
        return cleaned


def write_document(
    root: ET.Element,
    out_path: Path,
    unsupported: list[dict],
    error: type[Exception],
) -> Path | None:
    """Write ``root`` to ``out_path`` and the rows that could not be converted
    to ``<stem>_unsupported.json`` beside it.

    Returns the side file's path when one was written. A side file left by an
    earlier run is deleted on a clean run, since it would claim rows are
    missing. Any write failure is raised as ``error``.
    """
    side_path = out_path.with_name(f"{out_path.stem}_unsupported.json")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(out_path, encoding="utf-8", xml_declaration=True)
        if not unsupported:
            side_path.unlink(missing_ok=True)
            return None
        # ensure_ascii keeps undecodable source bytes (lone surrogates) writable.
        side_path.write_text(json.dumps(unsupported, indent=2), encoding="utf-8")
        return side_path
    except OSError as exc:
        raise error(f"cannot write {exc.filename or out_path}: {exc}") from exc
