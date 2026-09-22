from __future__ import annotations

import base64

import vobject

from ssba.core.parsers.contact import parse_cards
from tests.contact_fixtures import FAKE_JPEG, PROFILE_VCF


def _one(text: str):
    cards, unparsed = parse_cards(text)
    assert unparsed == []
    assert len(cards) == 1
    return cards[0]


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
    card = _one(_card("N:Rossi;Mario;;;", "TEL;CELL;PREF:+39 333 000 0001"))
    assert card.tel.params.get("TYPE") == ["CELL", "PREF"]
    assert card.tel.singletonparams == []
    out = card.serialize()
    assert "VERSION:3.0" in out
    assert "TEL;TYPE=CELL,PREF:+39 333 000 0001" in out


def test_unparseable_card_is_kept_raw_and_neighbours_still_parse():
    bad = _card("THIS LINE HAS NO COLON")
    text = _card("N:Uno;Primo;;;") + bad + _card("N:Due;Secondo;;;")
    cards, unparsed = parse_cards(text)
    assert [c.fn.value for c in cards] == ["Primo Uno", "Secondo Due"]
    assert unparsed == [bad.rstrip("\r\n")]


def test_profile_fixture_round_trips_as_vcard3():
    card = _one(PROFILE_VCF)
    again = vobject.readOne(card.serialize())
    assert again.version.value == "3.0"
    assert again.fn.value == "Paolo Verdi"
    assert again.photo.value == FAKE_JPEG
    assert again.org.value == ["Example Srl", "Ufficio Test"]
    assert again.bday.value == "--12-25"
