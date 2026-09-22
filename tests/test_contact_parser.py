from __future__ import annotations

import base64

import pytest
import vobject

from ssba.core.parsers.contact import parse_cards
from tests.contact_fixtures import FAKE_JPEG, PROFILE_VCF, QP, TRICKY_VCF, android_qp


def _exported(text: str) -> str:
    cards, unparsed = parse_cards(text)
    assert unparsed == []
    assert len(cards) == 1
    assert isinstance(cards[0], str)
    return cards[0]


def _one(text: str):
    """Export ``text`` and re-parse the vCard 3.0 result, as an importer would."""
    return vobject.readOne(_exported(text))


def _card(*lines: str) -> str:
    return "BEGIN:VCARD\r\nVERSION:2.1\r\n" + "".join(l + "\r\n" for l in lines) + "END:VCARD\r\n"


def test_malformed_photo_header_parses_and_keeps_bytes():
    b64 = base64.b64encode(FAKE_JPEG).decode()
    card = _one(_card("N:Rossi;Mario;;;", f"PHOTO;ENCODING=BASE64;PREF;JPEG; :{b64}"))
    assert card.photo.value == FAKE_JPEG


def test_empty_parameter_birthday_parses():
    card = _one(_card("N:Rossi;Mario;;;", "BDAY;;:--12-25"))
    assert card.bday.value == "--12-25"


def test_quoted_printable_utf8_name_with_emoji_is_decoded():
    card = _one(_card("N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:;=C3=80nna=F0=9F=92=8B Test;;;"))
    assert card.n.value.given == "Ànna💋 Test"
    assert card.fn.value == "Ànna💋 Test"
    assert "CHARSET" not in card.n.params


def test_group_member_becomes_deduplicated_categories():
    card = _one(_card(
        "N:Rossi;Mario;;;",
        "GROUP_MEMBER;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=4D=79=20=43=6F=6E=74=61=63=74=73",
        "GROUP_MEMBER:Famiglia",
        "GROUP_MEMBER:Famiglia",
    ))
    assert card.categories.value == ["My Contacts", "Famiglia"]
    assert "group-member" not in card.contents


def test_department_is_appended_to_existing_org():
    card = _one(_card("N:Rossi;Mario;;;", "ORG:Example Srl", "DEPARTMENT:Vendite"))
    assert card.org.value == ["Example Srl", "Vendite"]
    assert "department" not in card.contents


def test_department_alone_becomes_org():
    card = _one(_card("N:Rossi;Mario;;;", "DEPARTMENT:Vendite"))
    assert card.org.value == ["Vendite"]


def test_missing_name_falls_back_to_phone_for_fn():
    card = _one(_card("TEL;CELL:+39 333 000 0009"))
    assert card.fn.value == "+39 333 000 0009"


def test_v21_parameters_become_v3_type_and_encoding():
    out = _exported(_card("N:Rossi;Mario;;;", "TEL;CELL;PREF:+39 333 000 0001"))
    card = vobject.readOne(out)
    assert card.tel.params.get("TYPE") == ["CELL", "PREF"]
    assert card.tel.singletonparams == []
    assert "VERSION:3.0" in out
    assert "TEL;TYPE=CELL,PREF:+39 333 000 0001" in out


def test_unparseable_card_is_kept_raw_and_neighbours_still_parse():
    bad = _card("THIS LINE HAS NO COLON")
    text = _card("N:Uno;Primo;;;") + bad + _card("N:Due;Secondo;;;")
    cards, unparsed = parse_cards(text)
    assert [vobject.readOne(c).fn.value for c in cards] == ["Primo Uno", "Secondo Due"]
    assert unparsed == [bad.rstrip("\r\n")]


def test_card_without_version_is_exported_as_vcard3():
    again = _one("BEGIN:VCARD\r\nN:Rossi;Mario;;;\r\nEND:VCARD\r\n")
    assert again.version.value == "3.0"
    assert again.fn.value == "Mario Rossi"


def test_card_that_cannot_be_serialized_is_kept_raw_and_neighbours_still_export():
    # vCard 3.0 allows one N: vobject parses this card but refuses to serialize it.
    bad = _card("N:Uno;Primo;;;", "N:Due;Secondo;;;")
    text = _card("N:Tre;Terzo;;;") + bad + _card("N:Quattro;Quarto;;;")
    cards, unparsed = parse_cards(text)
    assert [vobject.readOne(c).fn.value for c in cards] == ["Terzo Tre", "Quarto Quattro"]
    assert unparsed == [bad.rstrip("\r\n")]


def test_truncated_trailing_card_goes_to_unparsed():
    truncated = "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Rossi;Mario;;;\r\nTEL;CELL:+39 333"
    cards, unparsed = parse_cards(_card("N:Uno;Primo;;;") + truncated)
    assert len(cards) == 1
    assert unparsed == [truncated]


def test_truncated_card_in_the_middle_goes_to_unparsed_and_the_next_card_exports():
    truncated = "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Rossi;Mario;;;"
    text = _card("N:Uno;Primo;;;") + truncated + "\r\n" + _card("N:Due;Secondo;;;")
    cards, unparsed = parse_cards(text)
    assert [vobject.readOne(c).fn.value for c in cards] == ["Primo Uno", "Secondo Due"]
    assert unparsed == [truncated]


def test_profile_fixture_round_trips_as_vcard3():
    again = _one(PROFILE_VCF)
    assert again.version.value == "3.0"
    assert again.fn.value == "Paolo Verdi"
    assert again.photo.value == FAKE_JPEG
    assert again.org.value == ["Example Srl", "Ufficio Test"]
    assert again.bday.value == "--12-25"


# --- value fidelity: vCard 2.1 text must survive the 3.0 conversion exactly ---


@pytest.mark.parametrize("name", ["NOTE", "TITLE", "X-FOO"])
@pytest.mark.parametrize("value", ["hello, world", "CEO, founder, owner", "a;b, c"])
def test_plain_text_value_with_commas_survives(name, value):
    card = _one(_card("N:Rossi;Mario;;;", f"{name}:{value}"))
    assert card.contents[name.lower()][0].value == value


@pytest.mark.parametrize("name", ["NOTE", "TITLE", "X-FOO"])
@pytest.mark.parametrize("value", [
    "hello, world",
    "a;b, c",
    "a long value, long enough to need several Android soft line breaks 😀, really",
    "exactly 23 bytes, yes!!",  # fills the QP line: the value ends with a soft break
])
def test_quoted_printable_text_value_survives(name, value):
    card = _one(_card("N:Rossi;Mario;;;", f"{name};{QP}:{android_qp(value)}"))
    assert card.contents[name.lower()][0].value == value


def test_quoted_printable_value_ending_on_a_soft_break_does_not_eat_the_next_line():
    value = "exactly 23 bytes, yes!!"
    assert android_qp(value).endswith("=\r\n")
    card = _one(_card("N:Rossi;Mario;;;", f"NOTE;{QP}:{android_qp(value)}", "TITLE:Boss"))
    assert card.note.value == value
    assert card.title.value == "Boss"


def test_quoted_printable_newlines_become_vcard3_newlines():
    card = _one(_card("N:Rossi;Mario;;;", f"NOTE;{QP}:{android_qp('uno' + chr(13) + chr(10) + 'due')}"))
    assert card.note.value == "uno\ndue"


def test_quoted_printable_uses_the_charset_parameter():
    card = _one(_card("N:Rossi;Mario;;;", "NOTE;CHARSET=ISO-8859-1;ENCODING=QUOTED-PRINTABLE:caff=E8=2C s=EC"))
    assert card.note.value == "caffè, sì"


def test_bare_quoted_printable_parameter_is_decoded():
    card = _one(_card("N:Rossi;Mario;;;", "NOTE;QUOTED-PRINTABLE:hello=2C world"))
    assert card.note.value == "hello, world"


def test_rfc_folded_text_value_is_unfolded():
    card = _one("BEGIN:VCARD\r\nVERSION:2.1\r\nN:Rossi;Mario;;;\r\nNOTE:hello,\r\n  world\r\nEND:VCARD\r\n")
    assert card.note.value == "hello, world"


def test_android_backslash_escapes_are_decoded_and_other_backslashes_kept():
    card = _one(_card("N:Rossi;Mario;;;", r"NOTE:uno\;due\, tre", r"TITLE:C:\Temp\Dir"))
    assert card.note.value == "uno;due, tre"
    assert card.title.value == r"C:\Temp\Dir"


def test_quoted_printable_backslash_is_kept_literally():
    value = r"back\;slash"
    card = _one(_card("N:Rossi;Mario;;;", f"NOTE;{QP}:{android_qp(value)}"))
    assert card.note.value == value


def test_unicode_line_separators_inside_a_value_do_not_split_the_line():
    value = "a\u2028b\u0085c\x0bd\x0ce"
    card = _one(_card("N:Rossi;Mario;;;", f"NOTE:{value}"))
    assert card.note.value == value


@pytest.mark.parametrize("qp", [False, True], ids=["plain", "qp"])
def test_org_with_comma_survives_and_exports(qp):
    line = f"ORG;{QP}:{android_qp('Acme, Inc.')}" if qp else "ORG:Acme, Inc."
    out = _exported(_card("N:Rossi;Mario;;;", line))
    assert "ORG:Acme\\, Inc." in out
    assert vobject.readOne(out).org.value == ["Acme, Inc."]


def test_escaped_semicolon_stays_inside_one_org_component():
    card = _one(_card("N:Rossi;Mario;;;", r"ORG:Uno\;Due;Reparto"))
    assert card.org.value == ["Uno;Due", "Reparto"]


@pytest.mark.parametrize("qp", [False, True], ids=["plain", "qp"])
def test_group_member_with_comma_is_one_category(qp):
    line = f"GROUP_MEMBER;{QP}:{android_qp('Friends, Family')}" if qp else "GROUP_MEMBER:Friends, Family"
    out = _exported(_card("N:Rossi;Mario;;;", line, "GROUP_MEMBER:Work"))
    assert "CATEGORIES:Friends\\, Family,Work" in out
    assert vobject.readOne(out).categories.value == ["Friends, Family", "Work"]


@pytest.mark.parametrize("qp", [False, True], ids=["plain", "qp"])
def test_name_components_with_commas_survive(qp):
    if qp:
        line = f"N;{QP}:{android_qp('Rossi, Jr.')};{android_qp('Mario, Luigi')};;;"
    else:
        line = "N:Rossi, Jr.;Mario, Luigi;;;"
    card = _one(_card(line))
    assert card.n.value.family == "Rossi, Jr."
    assert card.n.value.given == "Mario, Luigi"
    assert card.fn.value == "Mario, Luigi Rossi, Jr."


@pytest.mark.parametrize("qp", [False, True], ids=["plain", "qp"])
def test_android_custom_keeps_its_columns_and_every_value(qp):
    columns = ["vnd.android.cursor.item/nickname", "Nick, the Great; really", "1", "", ""]
    if qp:
        line = f"X-ANDROID-CUSTOM;{QP}:" + ";".join(android_qp(c) for c in columns)
    else:
        line = "X-ANDROID-CUSTOM:" + ";".join(c.replace(";", "\\;") for c in columns)
    out = _exported(_card("N:Rossi;Mario;;;", line))
    unfolded = out.replace("\r\n ", "")
    # Columns stay ';'-separated (Android re-imports them); text inside is escaped.
    assert "X-ANDROID-CUSTOM:vnd.android.cursor.item/nickname;Nick\\, the Great\\; really;1;;" in unfolded
    assert vobject.readOne(out).x_android_custom.value == ";".join(columns)


def test_name_with_extra_non_empty_components_is_not_truncated_silently():
    cards, unparsed = parse_cards(_card("N:Uno;Due;Tre;Quattro;Cinque;Sei"))
    assert cards == []
    assert len(unparsed) == 1


def test_name_with_extra_empty_components_exports():
    card = _one(_card("N:Rossi;Mario;;;;;"))
    assert card.fn.value == "Mario Rossi"


def test_tricky_fixture_values_survive_exactly():
    cards, unparsed = parse_cards(TRICKY_VCF)
    assert unparsed == []
    first, second = (vobject.readOne(c) for c in cards)
    assert first.n.value.family == "Neri, Jr."
    assert first.org.value == ["Acme, Inc.", "Sales, North"]
    assert first.title.value == "CEO, founder"
    assert first.note.value == "hello, world"
    assert first.categories.value == ["Friends, Family"]
    assert first.x_android_custom.value == (
        "vnd.android.cursor.item/nickname;Carletto, the Great;1;;;;;;;;;;;;;"
    )
    assert second.n.value.family == "Gialli, Sr."
    assert second.n.value.given == "Élodie 💋"
    assert second.org.value == ["Società, Uno; Due"]
    assert second.title.value == "Direttrice, capo; reparto"
    assert second.note.value == (
        "Prima riga, con virgola; e punto e virgola\nseconda riga 😀 fine, davvero"
    )
    assert second.categories.value == ["Colleghi, ufficio"]
    assert second.x_android_custom.value == (
        "vnd.sec.cursor.item/emergency_info;;via Roma 1, 00100 Roma, piano 3;;;;;;;;;;;;;"
    )
