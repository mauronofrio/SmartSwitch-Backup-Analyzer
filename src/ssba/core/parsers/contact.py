"""Merge the contacts Phase 1 recovered into one importable vCard 3.0 file."""

from __future__ import annotations

import json
import quopri
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


# Only CR/LF end a line: str.splitlines() would also split on U+2028, U+0085,
# \x0b and \x0c, which can legitimately appear inside UTF-8 values.
_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")
# Properties whose value is a ';'-separated list of components (Android writes
# X-ANDROID-CUSTOM as "<mimetype>;<column 1>;<column 2>;...").
_STRUCTURED = {"N", "ADR", "ORG", "X-ANDROID-CUSTOM"}
# Properties whose value is a ','-separated list, which vobject keeps as a list.
_LISTS = {"CATEGORIES"}
# Most components vobject keeps for N and ADR; more would be dropped silently.
_MAX_COMPONENTS = {"N": 5, "ADR": 7}
# Values vobject passes through without unescaping: never escape them.
_VERBATIM = {"BEGIN", "END", "VERSION", "GEO"}
# Backslash escapes decoded in plain (not quoted-printable) vCard 2.1 values: the
# ones Android's own 2.1 parser unescapes, plus \n, which its writer emits for
# newlines. Any other backslash is a literal character.
_V21_ESCAPES = {"\\": "\\", ";": ";", ",": ",", ":": ":", "n": "\n", "N": "\n"}
# Image formats a PHOTO/LOGO TYPE may name (vCard 2.1's list, plus PNG).
_IMAGE_FORMATS = {
    "GIF", "CGM", "WMF", "BMP", "MET", "PMB", "DIB", "PICT", "TIFF", "PS", "PDF",
    "JPEG", "MPEG", "MPEG2", "AVI", "QTIME", "PNG",
}
_TRANSFER_PARAMS = {
    "QUOTED-PRINTABLE", "ENCODING=QUOTED-PRINTABLE",
    "8BIT", "ENCODING=8BIT", "7BIT", "ENCODING=7BIT",
}


def _split_line(line: str) -> tuple[str, list[str], str]:
    # Samsung writes headers like "PHOTO;ENCODING=BASE64;PREF;JPEG; :" and
    # "BDAY;;:--12-25"; vobject rejects the empty parameters, so drop them.
    header, value = line.split(":", 1)
    name, *params = header.split(";")
    return name, [p for p in params if p.strip()], value


def _norm_param(param: str) -> str:
    return param.replace(" ", "").upper()


def _is_quoted_printable(params: list[str]) -> bool:
    return any(_norm_param(p) in ("QUOTED-PRINTABLE", "ENCODING=QUOTED-PRINTABLE") for p in params)


def _is_base64(params: list[str]) -> bool:
    return any(_norm_param(p) in ("BASE64", "ENCODING=BASE64", "ENCODING=B") for p in params)


def _charset(params: list[str]) -> str:
    for param in params:
        key, _, value = param.partition("=")
        if key.strip().upper() == "CHARSET" and value.strip().strip('"'):
            return value.strip().strip('"')
    return "utf-8"


def _logical_lines(card: str) -> list[list[str]]:
    """Group the raw lines of ``card`` into properties.

    A line continues the previous property if it starts with a space or tab
    (RFC folding), or if the previous property is quoted-printable and its last
    line ends with ``=`` (a soft line break; Android puts no space after it).
    """
    groups: list[list[str]] = []
    for line in _LINE_BREAK_RE.split(card):
        if groups and _continues(groups[-1], line):
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups


def _continues(group: list[str], line: str) -> bool:
    if line[:1] in (" ", "\t"):
        return True
    first = group[0]
    if ":" not in first:
        return False
    _, params, value = _split_line(first)
    last = value if len(group) == 1 else group[-1]
    return last.endswith("=") and _is_quoted_printable(params)


def _unfold(value: str, continuations: list[str], quoted_printable: bool) -> str:
    for line in continuations:
        if quoted_printable and value.endswith("="):
            value = value[:-1] + line  # soft line break: "=" + CRLF vanish
        else:
            value += line[1:]  # RFC folding: CRLF + one space/tab vanish
    return value


def _unescape_v21(value: str, separator: str | None) -> list[str]:
    parts, current, i = [], [], 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value) and value[i + 1] in _V21_ESCAPES:
            current.append(_V21_ESCAPES[value[i + 1]])
            i += 2
            continue
        if char == separator:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        i += 1
    parts.append("".join(current))
    return parts


def _escape_v3(text: str) -> str:
    text = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return _LINE_BREAK_RE.sub(r"\\n", text)


def _value_to_v3(prop: str, value: str, quoted_printable: bool, charset: str) -> str:
    """Decode a vCard 2.1 value and re-encode it as vCard 3.0 text."""
    separator = ";" if prop in _STRUCTURED else "," if prop in _LISTS else None
    if quoted_printable:
        # Android QP-encodes each component on its own, keeping ';' literal, and
        # does not backslash-escape QP text.
        parts = value.split(separator) if separator else [value]
        parts = [quopri.decodestring(p.encode("utf-8")).decode(charset) for p in parts]
    else:
        parts = _unescape_v21(value, separator)
    limit = _MAX_COMPONENTS.get(prop)
    if limit:
        while len(parts) > limit and parts[-1] == "":
            parts.pop()
        if len(parts) > limit:
            raise ValueError(f"{prop} has more than {limit} components")
    return (separator or "").join(_escape_v3(p) for p in parts)


def _prepare(card: str) -> tuple[str, list[str]]:
    """Turn a vCard 2.1 card into text vobject parses without losing any value.

    Text values are unfolded, quoted-printable-decoded and escaped as vCard 3.0
    text, so vobject cannot cut them at an unescaped comma. Binary values and
    BEGIN/END/VERSION/GEO lines keep their raw lines. Returns the prepared text
    and the vCard 3.0 value of every X-ANDROID-CUSTOM property, in order.
    """
    out: list[str] = []
    custom: list[str] = []
    for group in _logical_lines(card):
        first = group[0]
        if ":" not in first:
            out.extend(group)  # blank or broken line: vobject decides
            continue
        name, params, value = _split_line(first)
        prop = name.rsplit(".", 1)[-1].strip().upper()
        if prop in _VERBATIM or _is_base64(params):
            out.append(";".join([name, *params]) + ":" + value)
            out.extend(group[1:])
            continue
        quoted_printable = _is_quoted_printable(params)
        charset = _charset(params)
        value = _unfold(value, group[1:], quoted_printable)
        params = [
            p for p in params
            if _norm_param(p) not in _TRANSFER_PARAMS and not _norm_param(p).startswith("CHARSET=")
        ]
        value = _value_to_v3(prop, value, quoted_printable, charset)
        if prop == "X-ANDROID-CUSTOM":
            custom.append(value)
        out.append(";".join([name, *params]) + ":" + value)
    return "\r\n".join(out), custom


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
    if line.name.upper() in ("PHOTO", "LOGO") and "TYPE" in line.params:
        # In vCard 3.0 a PHOTO/LOGO TYPE is the image format, nothing else
        # (Samsung adds PREF and SUPREF).
        formats = [t for t in line.params["TYPE"] if t.strip().upper() in _IMAGE_FORMATS]
        if formats:
            line.params["TYPE"] = formats
        else:
            del line.params["TYPE"]


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


def _normalize(card, custom: list[str]):
    # vobject would re-escape X-ANDROID-CUSTOM's ';' column separators as text;
    # write the prepared vCard 3.0 value as it is instead.
    custom_lines = card.contents.get("x-android-custom", [])
    if len(custom_lines) != len(custom):
        raise ValueError("X-ANDROID-CUSTOM properties do not match")
    for line, value in zip(custom_lines, custom):
        line.value = value
        line.encoded = True

    categories: list[str] = []
    names = [v for line in card.contents.get("categories", []) for v in line.value]
    names += [line.value for line in card.contents.pop("group-member", [])]
    for name in names:
        if name not in categories:
            categories.append(name)
    if categories:
        card.contents.pop("categories", None)
        card.add("categories").value = categories

    departments = [line.value for line in card.contents.pop("department", [])]
    if departments:
        if "org" in card.contents:
            card.org.value = [*card.org.value, *departments]
        else:
            card.add("org").value = departments

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
    prepared, custom = _prepare(raw)
    card = vobject.readOne(prepared)
    return _normalize(card, custom).serialize()


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
        raise ContactExportError("report.json is not readable: top level is not an object")
    categories = report.get("categories", [])
    if not isinstance(categories, list):
        raise ContactExportError("report.json is not readable: categories is not a list")

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
        try:
            data = source.path.read_bytes()
        except OSError as exc:
            raise ContactExportError(f"cannot read {source.path}: {exc}") from exc
        # Decoded without newline translation so unparsed cards stay byte-exact.
        cards, bad = parse_cards(data.decode("utf-8", errors="replace"))
        serialized.extend(cards)
        unparsed.extend(bad)
        result.per_source[source.label] = len(cards)
        result.exported += len(cards)

    if result.exported == 0:
        raise ContactExportError("no contacts could be parsed from the recovered .vcf files")

    unparsed_path = out_path.with_name(f"{out_path.stem}_unparsed.vcf")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("".join(serialized), encoding="utf-8", newline="")
        if unparsed:
            unparsed_path.write_text("\r\n".join(unparsed) + "\r\n", encoding="utf-8", newline="")
        else:
            # A side file left by an earlier run would claim cards are missing.
            unparsed_path.unlink(missing_ok=True)
    except OSError as exc:
        raise ContactExportError(f"cannot write {exc.filename or out_path}: {exc}") from exc
    if unparsed:
        result.unparsed = len(unparsed)
        result.unparsed_path = unparsed_path
    return result
