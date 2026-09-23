from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWizard

from ssba.gui import i18n
from ssba.gui.wizard import PAGE_BACKUP, PAGE_CHOOSE, PAGE_SCAN, RecoveryWizard
from tests.gui.gui_fixtures import build_backup


@pytest.fixture(autouse=True)
def _english():
    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture
def wizard(qtbot, tmp_path, monkeypatch):
    build_backup(tmp_path / "root")
    w = RecoveryWizard(roots=[tmp_path / "root"])
    qtbot.addWidget(w)
    w.asked, w.warned = [], []
    monkeypatch.setattr(w, "ask", lambda text: w.asked.append(text) or True)
    monkeypatch.setattr(w, "warn", lambda text: w.warned.append(text))
    w.show()
    return w


def test_found_backups_are_listed_and_a_destination_is_proposed(wizard):
    page = wizard.page(PAGE_BACKUP)
    assert page.backups.count() == 1
    assert "Telefono (SM-X)" in page.backups.item(0).text()
    assert "SmartSwitch Recovery" in page.dest.text()
    assert wizard.button(QWizard.NextButton).isEnabled()


def test_a_destination_inside_the_backup_is_refused(wizard):
    page = wizard.page(PAGE_BACKUP)
    page.dest.setText(str(wizard.state.backup.path / "out"))
    wizard.next()
    assert wizard.currentId() == PAGE_BACKUP
    assert wizard.warned


def test_low_disk_space_asks_first(wizard, tmp_path, monkeypatch):
    from ssba.gui.pages import backup_page

    page = wizard.page(PAGE_BACKUP)
    page.dest.setText(str(tmp_path / "out"))
    monkeypatch.setattr(backup_page, "free_space", lambda path: 10)
    monkeypatch.setattr(wizard, "ask", lambda text: False)
    wizard.next()
    assert wizard.currentId() == PAGE_BACKUP


def test_decryption_runs_and_can_continue(wizard, qtbot, tmp_path):
    wizard.page(PAGE_BACKUP).dest.setText(str(tmp_path / "out"))
    wizard.next()
    assert wizard.currentId() == PAGE_SCAN
    scan = wizard.page(PAGE_SCAN)
    qtbot.waitUntil(scan.isComplete, timeout=20000)
    assert (tmp_path / "out" / "scan" / "report.json").is_file()
    assert (tmp_path / "out" / "ssba-gui.log").is_file()


def test_an_existing_scan_is_reused_and_decryption_skipped(wizard, qtbot, tmp_path):
    (tmp_path / "out" / "scan").mkdir(parents=True)
    (tmp_path / "out" / "scan" / "report.json").write_text('{"categories": []}', encoding="utf-8")
    page = wizard.page(PAGE_BACKUP)
    page.dest.setText(str(tmp_path / "out"))
    assert page.validatePage()
    assert wizard.state.reuse_scan
    assert page.nextId() == PAGE_CHOOSE  # the choose page itself arrives in Task 8


def test_picking_an_already_decrypted_folder_skips_decryption(wizard, tmp_path, monkeypatch):
    scan = tmp_path / "old" / "scan"
    scan.mkdir(parents=True)
    (scan / "report.json").write_text('{"categories": []}', encoding="utf-8")
    monkeypatch.setattr(wizard, "choose_folder", lambda title: scan)
    page = wizard.page(PAGE_BACKUP)
    page.browse_backup.click()
    assert wizard.state.existing_scan == scan
    assert page.validatePage()
    assert page.nextId() == PAGE_CHOOSE
    assert wizard.state.scan_dir == scan


def test_a_folder_that_is_not_a_backup_is_refused(wizard, tmp_path, monkeypatch):
    monkeypatch.setattr(wizard, "choose_folder", lambda title: tmp_path)
    wizard.page(PAGE_BACKUP).browse_backup.click()
    assert wizard.warned


def test_language_button_switches_every_text(wizard):
    wizard.button(QWizard.CustomButton1).click()
    assert wizard.page(PAGE_BACKUP).title() == "Scegli il backup"
    assert wizard.button(QWizard.CustomButton1).text() == "English"
