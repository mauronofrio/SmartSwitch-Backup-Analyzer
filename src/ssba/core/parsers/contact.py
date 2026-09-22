"""Merge the contacts Phase 1 recovered into one importable vCard 3.0 file."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import vobject

# A card runs from BEGIN:VCARD to the first END:VCARD with no other BEGIN:VCARD
# in between, so a truncated card cannot swallow the card after it.
_CARD_RE = re.compile(r"BEGIN:VCARD(?:(?!BEGIN:VCARD).)*?END:VCARD", re.DOTALL | re.IGNORECASE)
_BEGIN_RE = re.compile(r"BEGIN:VCARD", re.IGNORECASE)
_EXPORTABLE_STATUSES = {"decrypted", "plaintext_passthrough"}


class ContactExportError(Exception):
    """Raised when no contacts can be exported from a scan output directory."""


@dataclass(frozen=True)
class ContactSource:
    path: Path
    label: str
    is_profile: bool


@dataclass
class ContactExportResult:
    exported: int
    per_source: dict[str, int] = field(default_factory=dict)
    unparsed: int = 0
    unparsed_path: Path | None = None


def _sanitize(card: str) -> str:
    # Samsung writes headers like "PHOTO;ENCODING=BASE64;PREF;JPEG; :" and
    # "BDAY;;:--12-25"; vobject rejects the empty parameters.
    out = []
    for line in card.splitlines():
        if line[:1] in (" ", "\t") or ":" not in line:
            out.append(line)
            continue
        header, value = line.split(":", 1)
        name, *params = header.split(";")
        params = [p for p in params if p.strip()]
        out.append(";".join([name, *params]) + ":" + value)
    return "\r\n".join(out)


def _params_to_v3(line) -> None:
    line.params.pop("CHARSET", None)
    encoding = line.params.get("ENCODING")
    if encoding and encoding[0].upper() in ("BASE64", "B"):
        line.params["ENCODING"] = ["b"]
    if line.singletonparams:
        types = line.params.setdefault("TYPE", [])
        for param in line.singletonparams:
            if param not in types:
                types.append(param)
        line.singletonparams = []


def _formatted_name(card) -> str:
    if "n" in card.contents:
        name = card.n.value
        pieces = []
        for part in (name.prefix, name.given, name.additional, name.family, name.suffix):
            pieces.extend(part if isinstance(part, (list, tuple)) else [part])
        joined = " ".join(" ".join(p.split()) for p in pieces if p and p.strip())
        if joined:
            return joined
    if "org" in card.contents and card.org.value and card.org.value[0].strip():
        return card.org.value[0].strip()
    for key in ("email", "tel"):
        if key in card.contents and card.contents[key][0].value.strip():
            return card.contents[key][0].value.strip()
    return "Unknown"


def _normalize(card):
    categories: list[str] = []
    for group in card.contents.pop("group-member", []):
        if group.value not in categories:
            categories.append(group.value)
    if categories:
        card.add("categories").value = categories

    departments = card.contents.pop("department", [])
    if departments:
        department = departments[0].value
        if "org" in card.contents:
            first = card.org.value[0] if card.org.value else ""
            card.org.value = [first, department]
        else:
            card.add("org").value = [department]

    if "fn" not in card.contents:
        card.add("fn").value = _formatted_name(card)

    for lines in card.contents.values():
        for line in lines:
            _params_to_v3(line)
    if "version" in card.contents:
        card.version.value = "3.0"
    # Otherwise vobject adds VERSION:3.0 itself when serializing.
    return card


def _export_card(raw: str) -> str:
    card = vobject.readOne(_sanitize(raw))
    return _normalize(card).serialize()


def parse_cards(text: str) -> tuple[list[str], list[str]]:
    """Convert every vCard in ``text`` independently to vCard 3.0.

    Returns the serialized vCard 3.0 cards and the raw text of every card that
    could not be converted (including a card cut off before its END:VCARD), so a
    single bad card never loses the others and nothing is dropped silently.
    """
    cards: list[str] = []
    unparsed: list[str] = []

    def keep_leftover(gap: str) -> None:
        begin = _BEGIN_RE.search(gap)
        if begin:
            unparsed.append(gap[begin.start():].rstrip("\r\n"))

    position = 0
    for match in _CARD_RE.finditer(text):
        keep_leftover(text[position:match.start()])
        position = match.end()
        raw = match.group(0)
        try:
            cards.append(_export_card(raw))
        except Exception:
            unparsed.append(raw)
    keep_leftover(text[position:])
    return cards, unparsed


def find_contact_sources(scan_dir: Path) -> list[ContactSource]:
    report_path = scan_dir / "report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContactExportError(f"report.json not found in {scan_dir}") from exc
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ContactExportError(f"report.json is not readable: {exc}") from exc

    # Validate report structure: top level must be dict, categories must be list
    if not isinstance(report, dict):
        raise ContactExportError(f"report.json is not readable: top level is not an object")
    categories = report.get("categories", [])
    if not isinstance(categories, list):
        raise ContactExportError(f"report.json is not readable: categories is not a list")

    category = next(
        (c for c in categories if isinstance(c, dict) and c.get("category") == "CONTACT"),
        None,
    )
    if category is None:
        raise ContactExportError("the scan report has no CONTACT category")

    # Validate files is a list
    files = category.get("files", [])
    if not isinstance(files, list):
        files = []

    sources = []
    contact_root = scan_dir / "CONTACT"
    try:
        contact_root_resolved = contact_root.resolve()
    except (OSError, ValueError):
        contact_root_resolved = contact_root

    for entry in files:
        # Skip non-dict entries
        if not isinstance(entry, dict):
            continue
        rel = entry.get("path", "")
        # Skip entries with non-string or empty paths
        if not isinstance(rel, str) or not rel:
            continue
        if not rel.lower().endswith(".vcf") or entry.get("status") not in _EXPORTABLE_STATUSES:
            continue
        path = contact_root / rel
        # Check that resolved path stays within contact_root (defense against path traversal)
        try:
            path_resolved = path.resolve()
            if not path_resolved.is_relative_to(contact_root_resolved):
                continue
        except (OSError, ValueError):
            continue
        if not path.is_file():
            continue
        label = path.name
        sources.append(ContactSource(path=path, label=label, is_profile=label.lower() == "profile.vcf"))
    sources.sort(key=lambda s: (not s.is_profile, s.label))
    return sources


def export_contacts(scan_dir: Path, out_path: Path) -> ContactExportResult:
    sources = find_contact_sources(scan_dir)
    if not sources:
        raise ContactExportError("no contact .vcf files found in the scan output")

    serialized: list[str] = []
    unparsed: list[str] = []
    result = ContactExportResult(exported=0)
    for source in sources:
        # Decoded without newline translation so unparsed cards stay byte-exact.
        text = source.path.read_bytes().decode("utf-8", errors="replace")
        cards, bad = parse_cards(text)
        serialized.extend(cards)
        unparsed.extend(bad)
        result.per_source[source.label] = len(cards)
        result.exported += len(cards)

    if result.exported == 0:
        raise ContactExportError("no contacts could be parsed from the recovered .vcf files")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(serialized), encoding="utf-8", newline="")
    if unparsed:
        unparsed_path = out_path.with_name(f"{out_path.stem}_unparsed.vcf")
        unparsed_path.write_text("\r\n".join(unparsed) + "\r\n", encoding="utf-8", newline="")
        result.unparsed = len(unparsed)
        result.unparsed_path = unparsed_path
    return result
