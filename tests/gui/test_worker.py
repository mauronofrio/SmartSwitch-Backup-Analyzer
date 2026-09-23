from __future__ import annotations

from ssba.core.progress import Progress
from ssba.gui.worker import Worker


def test_worker_relays_progress_and_result(qtbot):
    def job(progress, cancel):
        progress(Progress("scan", 1, 2, "a"))
        return 42

    worker = Worker(job)
    seen = []
    worker.progressed.connect(seen.append)
    with qtbot.waitSignal(worker.succeeded, timeout=5000) as blocker:
        worker.start()
    assert blocker.args == [42]
    worker.wait()
    assert seen == [Progress("scan", 1, 2, "a")]


def test_worker_reports_failures(qtbot):
    def job(progress, cancel):
        raise ValueError("broken")

    worker = Worker(job)
    with qtbot.waitSignal(worker.failed, timeout=5000) as blocker:
        worker.start()
    worker.wait()
    assert "ValueError: broken" in blocker.args[0]


def test_worker_reports_cancellation(qtbot):
    def job(progress, cancel):
        cancel.check()
        return "not reached"

    worker = Worker(job)
    worker.token.cancel()
    with qtbot.waitSignal(worker.cancelled, timeout=5000):
        worker.start()
    worker.wait()
