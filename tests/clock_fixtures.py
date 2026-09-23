"""Fabricated Samsung Clock backup for tests - no real data."""

from __future__ import annotations

from pathlib import Path

from tests.scan_fixtures import add_category, entry

ALARM_XML = (
    "<Alarms><BackupVersion>8</BackupVersion>"
    "<alarm><active>1</active><alarmtime>530</alarmtime><name>Sveglia &lt;presto&gt;</name>"
    "<repeattype>65537</repeattype></alarm>"
    "<alarm><active>0</active><alarmtime>2359</alarmtime><name></name><repeattype>0</repeattype></alarm>"
    "<alarm><active>0</active><alarmtime>abc</alarmtime><name/><repeattype/></alarm>"
    "</Alarms>"
)
TIMER_XML = (
    "<Timer><BackupVersion>8</BackupVersion><timerlife>"
    "<item><id>1</id><timername></timername><time>00:30:00</time></item>"
    "<item><id>2</id><timername>Pasta</timername><time>00:10:00</time></item>"
    "</timerlife></Timer>"
)
WORLD_XML = (
    "<Worldclocks><worldclock>"
    "<item><city>Roma</city><gmt>GMT+1:00</gmt></item>"
    "<item><city>Tokyo</city><gmt>GMT+9:00</gmt></item>"
    "</worldclock></Worldclocks>"
)


def build_clock_scan_dir(scan_dir: Path, *, alarm: str | None = ALARM_XML,
                         timer: str | None = TIMER_XML, world: str | None = WORLD_XML) -> Path:
    if alarm is not None:
        folder = scan_dir / "ALARM" / "ALARM.zip"
        folder.mkdir(parents=True)
        (folder / "alarm.exml").write_text(alarm, encoding="utf-8")
        add_category(scan_dir, "ALARM", [entry("ALARM.zip/alarm.exml", kind="xml")])
    files = []
    folder = scan_dir / "WORLDCLOCK" / "WORLDCLOCK.zip"
    for name, text in (("timer.exml", timer), ("worldclock.exml", world)):
        if text is not None:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / name).write_text(text, encoding="utf-8")
            files.append(entry(f"WORLDCLOCK.zip/{name}", kind="xml"))
    if files:
        add_category(scan_dir, "WORLDCLOCK", files)
    return scan_dir
