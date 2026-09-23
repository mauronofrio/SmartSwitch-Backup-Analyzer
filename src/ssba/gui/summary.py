"""One localized line per export for the summary page."""

from __future__ import annotations

from ssba.core.recovery import ExportOutcome
from ssba.gui.i18n import tr


def describe(outcome: ExportOutcome) -> tuple[str, str]:
    """(level, text): level is "ok", "warn" (something to check) or "error"."""
    if not outcome.ok:
        return "error", tr("sum_error", error=outcome.error)
    r = outcome.result
    key = outcome.key
    if key == "files" and r is None:
        return "ok", tr("sum_files_kept")
    warn = 0
    if key == "contacts":
        text, warn = tr("sum_contacts", n=r.exported), r.unparsed
    elif key == "messages":
        text, warn = tr("sum_messages", n=r.exported), r.unsupported
    elif key == "calls":
        text, warn = tr("sum_calls", n=r.exported), r.unsupported
    elif key == "wifi":
        text = tr("sum_wifi", n=r.networks, p=r.with_password)
    elif key == "blocked-numbers":
        text = tr("sum_blocked", n=r.exported)
    elif key == "browser":
        text = tr("sum_browser", b=r.bookmarks, h=r.history)
    elif key == "clipboard":
        text, warn = tr("sum_clipboard", t=r.texts, i=r.images), r.missing_images
    elif key == "clock":
        text = tr("sum_clock", a=r.alarms, t=r.timers, c=r.cities)
    elif key == "notes":
        text, warn = tr("sum_notes", n=r.notes, a=r.attachments), r.handwriting_only + r.with_drawings
    elif key == "apps":
        text = tr("sum_apps", n=r.apps)
    else:  # files
        text, warn = tr("sum_files", n=r.placed, m=r.merged), r.conflicts + r.missing
    if warn:
        return "warn", f"{text} \u2014 {tr('sum_check', n=warn)}"
    return "ok", text
