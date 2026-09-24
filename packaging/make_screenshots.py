"""Screenshots of the wizard for the README, on a fabricated demo backup (no real data).

Run from the repo root with the GUI extra installed:
    python packaging/make_screenshots.py [en|it]
The window must be able to open (not a headless session). Counts are invented.
"""
import io
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication
from tests.crypto_helpers import encrypt_dummy_ecb
from tests.discovery_fixtures import write_history
from tests.gui.gui_fixtures import ALARM_XML, FAKE_DUMMY, JPEG
from ssba.core.progress import Progress
from ssba.core.recovery import EXPORTS, ExportOutcome
from ssba.gui import i18n
from ssba.gui.pages import choose_page, run_page
from ssba.gui.wizard import PAGE_CHOOSE, PAGE_RUN, PAGE_SUMMARY, RecoveryWizard

OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp())
root = tmp / "backup"
folder = write_history(root / "SM-A137F" / "SM-A137F_" / "SM-A137F_20260922111112",
                       model="SM-A137F", name="Galaxy A13", saved="2026-09-22T11:58:15",
                       size=58392323062, dummy=encrypt_dummy_ecb(FAKE_DUMMY),
                       items=((r"ALARM\ALARM.zip", 1), (r"Photo\Photo.zip", 1)))
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("alarm.exml", ALARM_XML)
(folder / "ALARM").mkdir()
(folder / "ALARM" / "ALARM.zip").write_bytes(buf.getvalue())
(folder / "Photo" / "DCIM" / "Camera").mkdir(parents=True)
(folder / "Photo" / "DCIM" / "Camera" / "a.jpg").write_bytes(JPEG)

RESULTS = {
    "contacts": NS(exported=412, unparsed=0), "messages": NS(exported=1350, unsupported=0),
    "calls": NS(exported=980, unsupported=0), "wifi": NS(networks=12, with_password=9),
    "blocked-numbers": NS(exported=3), "browser": NS(bookmarks=24, history=530),
    "clipboard": NS(texts=36, images=58, missing_images=0), "clock": NS(alarms=4, timers=2, cities=3),
    "notes": NS(notes=210, attachments=95, handwriting_only=0, with_drawings=3),
    "apps": NS(apps=87), "files": NS(placed=5230, merged=120, conflicts=0, missing=0),
}
gate = threading.Event()

def fake_run(export, scan_dir, dest, *, files_mode, progress, cancel):
    time.sleep(0.15)
    if export.key == "notes":
        progress(Progress("notes", 120, 210, "note"))
        gate.wait()
    path = dest / export.target
    path.mkdir(parents=True, exist_ok=True)
    return ExportOutcome(export.key, True, RESULTS[export.key], None, path)

choose_page.available_exports = lambda scan_dir: list(EXPORTS)
run_page.run_export = fake_run

app = QApplication(sys.argv)
i18n.set_language(sys.argv[1] if len(sys.argv) > 1 else "en")
suffix = "" if i18n.language() == "en" else "-" + i18n.language()
w = RecoveryWizard(roots=[root])
for name in ("ask", "warn", "info", "show_error"):
    setattr(w, name, (lambda *a: True))
w.open_path = lambda p: None
w.resize(860, 640)
w.show()

def wait(cond):
    while not cond():
        app.processEvents(); time.sleep(0.02)
    for _ in range(20):
        app.processEvents(); time.sleep(0.01)

def shot(name):
    wait(lambda: True)
    w.grab().save(str(OUT / f"{name}{suffix}.png"))

page = w.currentPage()
page.backups.setCurrentRow(0)
page.dest.setText(r"C:\Users\You\Downloads\SmartSwitch-Backup-Analyzer\SM-A137F_2026-09-22")
shot("1-backup")
page.dest.setText(str(tmp / "out"))
w.next()
wait(lambda: w.currentPage().isComplete())
shot("2-decrypt")
w.next()
wait(lambda: w.currentId() == PAGE_CHOOSE)
shot("3-choose")
w.next()
run = w.page(PAGE_RUN)
wait(lambda: run._running == "notes" and run.bar.maximum() == 210)
shot("4-recover")
gate.set()
wait(run.isComplete)
w.next()
wait(lambda: w.currentId() == PAGE_SUMMARY)
shot("5-summary")
w.done(0)
print("ok", sorted(p.name for p in OUT.iterdir()))
