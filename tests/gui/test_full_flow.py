from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QWizard

from ssba.gui import i18n
from ssba.gui.wizard import PAGE_BACKUP, PAGE_CHOOSE, PAGE_RUN, PAGE_SUMMARY, RecoveryWizard
from tests.gui.gui_fixtures import JPEG, build_backup


def _blocking_run_export(export, scan_dir, dest, *, files_mode, progress, cancel):
    while True:
        cancel.check()
        time.sleep(0.01)


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
    w.opened, w.infos, w.errors = [], [], []
    monkeypatch.setattr(w, "ask", lambda text: True)
    monkeypatch.setattr(w, "warn", lambda text: None)
    monkeypatch.setattr(w, "open_path", lambda path: w.opened.append(path))
    monkeypatch.setattr(w, "info", lambda text: w.infos.append(text))
    monkeypatch.setattr(w, "show_error", lambda details: w.errors.append(details))
    w.show()
    w.page(PAGE_BACKUP).dest.setText(str(tmp_path / "out"))
    w.next()
    qtbot.waitUntil(w.currentPage().isComplete, timeout=20000)
    w.next()
    assert w.currentId() == PAGE_CHOOSE
    return w


def test_only_available_exports_are_offered(wizard):
    page = wizard.page(PAGE_CHOOSE)
    assert list(page.checks) == ["clock"]
    assert page.checks["clock"].isChecked()
    # Smart Switch's own item counts count backup files, not records (SMS showed "(1)").
    assert page.checks["clock"].text() == "Alarms, timers and world clock"
    assert page.files_copy.isChecked()
    assert page.files_box.isVisible()


@pytest.mark.parametrize("mode", ["copy", "move", "keep"])
def test_recovery_runs_and_the_summary_opens_results(wizard, qtbot, tmp_path, mode):
    page = wizard.page(PAGE_CHOOSE)
    {"copy": page.files_copy, "move": page.files_move, "keep": page.files_keep}[mode].setChecked(True)
    wizard.next()
    assert wizard.currentId() == PAGE_RUN
    qtbot.waitUntil(wizard.page(PAGE_RUN).isComplete, timeout=20000)
    out = tmp_path / "out"
    assert (out / "clock.html").is_file()
    photo = out / "files" / "DCIM" / "Camera" / "a.jpg"
    if mode == "keep":
        assert not photo.exists()
    else:
        assert photo.read_bytes() == JPEG
    assert [o.key for o in wizard.state.outcomes] == ["clock", "files"]
    assert all(o.ok for o in wizard.state.outcomes)

    wizard.next()
    assert wizard.currentId() == PAGE_SUMMARY
    summary = wizard.page(PAGE_SUMMARY)
    assert len(summary.rows) == 2
    summary.rows[0].open_button.click()
    summary.open_results.click()
    assert wizard.opened == [out / "clock.html", out]


def test_unticked_exports_are_not_run(wizard, qtbot, tmp_path):
    page = wizard.page(PAGE_CHOOSE)
    page.checks["clock"].setChecked(False)
    page.files_keep.setChecked(True)
    wizard.next()
    qtbot.waitUntil(wizard.page(PAGE_RUN).isComplete, timeout=20000)
    assert not (tmp_path / "out" / "clock.html").exists()
    assert [o.key for o in wizard.state.outcomes] == ["files"]


def test_recovery_can_be_stopped(wizard, qtbot, monkeypatch):
    from ssba.gui.pages import run_page

    monkeypatch.setattr(run_page, "run_export", _blocking_run_export)

    wizard.next()
    run = wizard.page(PAGE_RUN)
    run.worker.token.cancel()
    qtbot.waitUntil(run.isComplete, timeout=20000)
    assert run.status.text() == i18n.tr("p4_cancelled")
    assert wizard.state.outcomes == []


def test_back_is_disabled_once_the_run_page_is_entered(wizard, qtbot):
    wizard.next()
    assert wizard.currentId() == PAGE_RUN
    assert not wizard.button(QWizard.BackButton).isEnabled()
    qtbot.waitUntil(wizard.page(PAGE_RUN).isComplete, timeout=20000)


def test_closing_the_wizard_while_running_asks_first(wizard, qtbot, monkeypatch):
    from ssba.gui.pages import run_page

    monkeypatch.setattr(run_page, "run_export", _blocking_run_export)

    wizard.next()
    run = wizard.page(PAGE_RUN)
    assert run.worker.isRunning()

    monkeypatch.setattr(wizard, "ask", lambda text: False)
    wizard.reject()
    assert wizard.isVisible()
    assert run.worker.isRunning()

    monkeypatch.setattr(wizard, "ask", lambda text: True)
    wizard.reject()
    assert not run.worker.isRunning()
    assert not wizard.isVisible()


def test_choose_page_blocks_next_when_nothing_will_run(wizard):
    page = wizard.page(PAGE_CHOOSE)
    page.checks["clock"].setChecked(False)
    page.files_keep.setChecked(True)
    assert not page.isComplete()
    assert not wizard.button(QWizard.NextButton).isEnabled()
    page.checks["clock"].setChecked(True)
    assert page.isComplete()
    assert wizard.button(QWizard.NextButton).isEnabled()


def test_nothing_available_shows_message_and_blocks_next(qtbot, tmp_path, monkeypatch):
    w = RecoveryWizard(roots=[tmp_path / "root"])
    qtbot.addWidget(w)
    monkeypatch.setattr(w, "ask", lambda text: True)
    monkeypatch.setattr(w, "warn", lambda text: None)
    monkeypatch.setattr(w, "info", lambda text: None)
    monkeypatch.setattr(w, "show_error", lambda details: None)
    scan_dir = tmp_path / "empty_scan"
    scan_dir.mkdir()
    (scan_dir / "report.json").write_text('{"categories": []}', encoding="utf-8")
    w.state.scan_dir = scan_dir
    page = w.page(PAGE_CHOOSE)
    page.initializePage()
    assert page.nothing.text() == i18n.tr("p3_nothing")
    assert not page.isComplete()


def test_a_failed_export_shows_the_failed_status_and_reports_the_error(wizard, qtbot, monkeypatch):
    from ssba.gui.pages import run_page

    def boom(export, scan_dir, dest, *, files_mode, progress, cancel):
        raise RuntimeError("boom")

    monkeypatch.setattr(run_page, "run_export", boom)
    wizard.next()
    run = wizard.page(PAGE_RUN)
    qtbot.waitUntil(run.isComplete, timeout=20000)
    assert run.status.text() == i18n.tr("p4_failed")
    assert wizard.errors

    wizard.button(QWizard.CustomButton1).click()  # switch to Italian
    assert run.status.text() == i18n.tr("p4_failed")


def test_a_cancelled_row_is_marked_stopped(wizard, qtbot, monkeypatch):
    from ssba.gui.pages import run_page

    monkeypatch.setattr(run_page, "run_export", _blocking_run_export)
    wizard.next()
    run = wizard.page(PAGE_RUN)
    qtbot.waitUntil(lambda: run._running == "clock", timeout=20000)
    run.worker.token.cancel()
    qtbot.waitUntil(run.isComplete, timeout=20000)
    assert run.labels["clock"].text() == i18n.tr("p4_row_cancelled", name=i18n.tr("export_clock"))


def test_re_entering_run_page_replaces_the_finished_worker(wizard, qtbot):
    wizard.next()
    assert wizard.currentId() == PAGE_RUN
    run = wizard.page(PAGE_RUN)
    qtbot.waitUntil(run.isComplete, timeout=20000)
    first_worker = run.worker

    wizard.back()  # the Back button is disabled, but the API call still works
    assert wizard.currentId() == PAGE_CHOOSE
    wizard.next()
    assert wizard.currentId() == PAGE_RUN
    qtbot.waitUntil(run.isComplete, timeout=20000)
    assert run.worker is not first_worker
    assert [o.key for o in wizard.state.outcomes] == ["clock", "files"]
