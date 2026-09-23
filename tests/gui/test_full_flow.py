from __future__ import annotations

import time

import pytest

from ssba.gui import i18n
from ssba.gui.wizard import PAGE_BACKUP, PAGE_CHOOSE, PAGE_RUN, PAGE_SUMMARY, RecoveryWizard
from tests.gui.gui_fixtures import JPEG, build_backup


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
    assert "(1)" in page.checks["clock"].text()
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

    def fake_run_export(export, scan_dir, dest, *, files_mode, progress, cancel):
        while True:
            cancel.check()
            time.sleep(0.01)

    monkeypatch.setattr(run_page, "run_export", fake_run_export)

    wizard.next()
    run = wizard.page(PAGE_RUN)
    run.worker.token.cancel()
    qtbot.waitUntil(run.isComplete, timeout=20000)
    assert run.status.text() == i18n.tr("p4_cancelled")
    assert wizard.state.outcomes == []
