from __future__ import annotations

import pytest

from ssba.core.parsers.files import export_files
from ssba.core.parsers.notes import export_notes
from ssba.core.progress import CancelToken, OperationCancelled
from tests.files_fixtures import build_files_scan_dir
from tests.notes_fixtures import build_notes_scan_dir


def _tree(out):
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())


def test_files_report_one_event_per_planned_file(tmp_path):
    events = []
    export_files(build_files_scan_dir(tmp_path / "scan"), tmp_path / "out", "copy", progress=events.append)
    assert {e.stage for e in events} == {"files"}
    assert [e.done for e in events] == list(range(10))
    assert all(e.total == 9 for e in events)
    assert events[0].item == "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/w.jpg"
    assert events[-1].item == ""


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_files_cancel_stops_between_files_and_a_rerun_finishes(tmp_path, mode):
    scan_dir = build_files_scan_dir(tmp_path / "scan")
    out = tmp_path / "out"
    token = CancelToken()

    def progress(event):
        if event.done == 0:  # cancel while the first file is being placed
            token.cancel()

    with pytest.raises(OperationCancelled):
        export_files(scan_dir, out, mode, progress=progress, cancel=token)
    assert _tree(out) == ["Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/w.jpg"]
    assert not list(out.rglob("*.partial"))

    export_files(scan_dir, out, mode)
    assert len(_tree(out)) == 8


def test_notes_report_one_event_per_note(tmp_path):
    events = []
    export_notes(build_notes_scan_dir(tmp_path / "scan"), tmp_path / "out", progress=events.append)
    assert {e.stage for e in events} == {"notes"}
    assert [e.done for e in events] == list(range(8))
    assert events[0].item == "Lista spesa"


def test_notes_cancel_stops_between_notes(tmp_path):
    token = CancelToken()

    def progress(event):
        if event.done == 0:  # cancel while the first note is being written
            token.cancel()

    out = tmp_path / "out"
    with pytest.raises(OperationCancelled):
        export_notes(build_notes_scan_dir(tmp_path / "scan"), out, progress=progress, cancel=token)
    assert _tree(out) == ["Uncategorized/Lista spesa.txt"]
