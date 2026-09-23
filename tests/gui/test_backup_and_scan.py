from __future__ import annotations

import logging
import time

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
    w.asked, w.warned, w.infos, w.errors = [], [], [], []
    monkeypatch.setattr(w, "ask", lambda text: w.asked.append(text) or True)
    monkeypatch.setattr(w, "warn", lambda text: w.warned.append(text))
    monkeypatch.setattr(w, "info", lambda text: w.infos.append(text))
    monkeypatch.setattr(w, "show_error", lambda details: w.errors.append(details))
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
    asked = []
    monkeypatch.setattr(wizard, "ask", lambda text: asked.append(text) or False)
    wizard.next()
    assert wizard.currentId() == PAGE_BACKUP
    assert asked


def test_a_relative_destination_is_refused(wizard):
    page = wizard.page(PAGE_BACKUP)
    page.dest.setText("relative/path")
    wizard.next()
    assert wizard.currentId() == PAGE_BACKUP
    assert wizard.warned


def test_an_unusable_destination_is_refused(wizard, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a folder", encoding="utf-8")
    page = wizard.page(PAGE_BACKUP)
    page.dest.setText(str(blocker / "out"))
    wizard.next()
    assert wizard.currentId() == PAGE_BACKUP
    assert wizard.warned


def test_decryption_runs_and_can_continue(wizard, qtbot, tmp_path):
    wizard.page(PAGE_BACKUP).dest.setText(str(tmp_path / "out"))
    wizard.next()
    assert wizard.currentId() == PAGE_SCAN
    scan = wizard.page(PAGE_SCAN)
    qtbot.waitUntil(scan.isComplete, timeout=20000)
    assert (tmp_path / "out" / "scan" / "report.json").is_file()
    assert (tmp_path / "out" / "ssba-gui.log").is_file()


def test_closing_the_wizard_while_scanning_asks_first(wizard, qtbot, tmp_path, monkeypatch):
    from ssba.gui.pages import scan_page

    def blocking_scan(backup_path, scan_dir, progress, cancel):
        while True:
            cancel.check()
            time.sleep(0.01)

    monkeypatch.setattr(scan_page, "scan_backup", blocking_scan)
    wizard.page(PAGE_BACKUP).dest.setText(str(tmp_path / "out"))
    wizard.next()
    assert wizard.currentId() == PAGE_SCAN
    scan = wizard.page(PAGE_SCAN)
    assert scan.worker.isRunning()

    monkeypatch.setattr(wizard, "ask", lambda text: False)
    wizard.reject()
    assert wizard.isVisible()
    assert scan.worker.isRunning()

    monkeypatch.setattr(wizard, "ask", lambda text: True)
    wizard.reject()
    assert not scan.worker.isRunning()
    assert not wizard.isVisible()


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


def test_picking_the_same_backup_again_selects_it_instead_of_duplicating(wizard, monkeypatch):
    page = wizard.page(PAGE_BACKUP)
    backup_path = wizard.state.backup.path
    monkeypatch.setattr(wizard, "choose_folder", lambda title: backup_path)
    page._pick_backup()
    assert page.backups.count() == 1
    assert page.backups.currentRow() == 0


def test_default_destination_uses_the_given_documents_folder(tmp_path):
    from ssba.core.discovery import BackupInfo
    from ssba.gui.pages.backup_page import default_destination

    info = BackupInfo(path=tmp_path / "backup", device_name="Telefono", model="SM-X", saved_at=None, size=1)
    documents = tmp_path / "Documents"
    dest = default_destination(info, documents=documents)
    assert dest.parent.parent == documents


def test_default_destination_falls_back_to_home_documents_when_qt_reports_none(monkeypatch, tmp_path):
    from PySide6.QtCore import QStandardPaths

    from ssba.core.discovery import BackupInfo
    from ssba.gui.pages import backup_page

    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda kind: "")
    monkeypatch.setattr(backup_page.Path, "home", lambda: tmp_path)
    info = BackupInfo(path=tmp_path / "backup", device_name="Telefono", model="SM-X", saved_at=None, size=1)
    dest = backup_page.default_destination(info)
    assert dest.parent.parent == tmp_path / "Documents"


def test_worker_uses_the_backup_path_captured_when_the_page_starts(wizard, qtbot, tmp_path):
    page = wizard.page(PAGE_BACKUP)
    page.dest.setText(str(tmp_path / "out"))
    wizard.next()
    assert wizard.currentId() == PAGE_SCAN
    # Simulate the wizard state changing before the background thread runs its job.
    wizard.state.backup = None
    wizard.state.scan_dir = None
    scan = wizard.page(PAGE_SCAN)
    qtbot.waitUntil(scan.isComplete, timeout=20000)
    assert (tmp_path / "out" / "scan" / "report.json").is_file()


def test_finishing_the_wizard_closes_the_log_handler(wizard, tmp_path):
    page = wizard.page(PAGE_BACKUP)
    page.dest.setText(str(tmp_path / "out"))
    assert page.validatePage()
    logger = logging.getLogger("ssba.gui")
    assert any(getattr(h, "_ssba", False) for h in logger.handlers)
    wizard.done(QWizard.Rejected)
    assert not any(getattr(h, "_ssba", False) for h in logger.handlers)
