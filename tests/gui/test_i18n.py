from __future__ import annotations

import pytest

from ssba.gui import i18n


@pytest.fixture(autouse=True)
def _english():
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def test_both_languages_have_the_same_keys():
    assert set(i18n.STRINGS["en"]) == set(i18n.STRINGS["it"])


def test_tr_formats_and_switches_language():
    assert i18n.tr("sum_contacts", n=3) == "3 contacts"
    i18n.set_language("it")
    assert i18n.language() == "it"
    assert i18n.tr("sum_contacts", n=3) == "3 contatti"


def test_unknown_language_falls_back_to_english():
    i18n.set_language("de")
    assert i18n.language() == "en"


@pytest.mark.parametrize("name, lang", [("it_IT", "it"), ("it-CH", "it"), ("en_US", "en"), ("de_DE", "en")])
def test_system_language(name, lang):
    assert i18n.system_language(name) == lang
