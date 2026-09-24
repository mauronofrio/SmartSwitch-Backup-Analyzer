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


def test_the_app_starts_in_english_even_on_an_italian_system(qtbot, monkeypatch):
    from PySide6.QtCore import QLocale
    from PySide6.QtWidgets import QApplication

    from ssba.gui import app
    from ssba.gui.wizard import RecoveryWizard

    monkeypatch.setattr(QLocale, "system", staticmethod(lambda: QLocale("it_IT")))
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    monkeypatch.setattr(RecoveryWizard, "show", lambda self: None)
    i18n.set_language("it")
    assert app.main() == 0
    assert i18n.language() == "en"
