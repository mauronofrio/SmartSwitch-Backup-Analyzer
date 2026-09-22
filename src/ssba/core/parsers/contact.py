"""Merge the contacts Phase 1 recovered into one importable vCard 3.0 file."""

from __future__ import annotations

import re

import vobject

_CARD_RE = re.compile(r"BEGIN:VCARD.*?END:VCARD", re.DOTALL)


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
    card.version.value = "3.0"
    return card


def parse_cards(text: str) -> tuple[list, list[str]]:
    """Parse every vCard in ``text`` independently.

    Returns the normalized vCard 3.0 components and the raw text of every card
    that could not be parsed, so a single bad card never loses the others.
    """
    cards, unparsed = [], []
    for raw in _CARD_RE.findall(text):
        try:
            card = vobject.readOne(_sanitize(raw))
        except Exception:
            unparsed.append(raw)
            continue
        cards.append(_normalize(card))
    return cards, unparsed
