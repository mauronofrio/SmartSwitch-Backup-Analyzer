# Graphical Interface (Phase 3)

Status: approved design, not yet implemented.
Date: 2026-09-24

## Purpose

Let anyone with a Samsung Smart Switch PC backup on Windows recover their
data without a terminal: pick the backup, pick a folder, tick what to
recover, and get the files — with progress, cancel, and a clear summary.

Decisions taken with the project owner:

- Audience: anyone, on **Windows**, as a downloadable `.exe` (no Python
  needed). Not published on PyPI.
- Interface in **Italian and English** (system language by default,
  switchable with a button).
- A **guided wizard** only; results are opened with the programs the user
  already has (File Explorer, browser). No in-app viewers.
- Toolkit: **PySide6 (Qt)**.
- Everything stays usable **without the GUI**: the `ssba` command line keeps
  working unchanged, and the engine (`ssba.core`) is importable from Python
  scripts. The GUI contains no recovery logic of its own.
- The Wi-Fi page shows each network's QR code and password only on request
  ("Show QR code", "Show password").
- The user chooses the destination folder; the GUI proposes one.

## Architecture

```
src/ssba/core/          engine, importable; never prints
  progress.py           NEW  Progress, ProgressFn, CancelToken, OperationCancelled
  discovery.py          NEW  find Smart Switch backups and read their summary
  recovery.py           NEW  registry of the exports (shared by CLI `export all` and GUI)
  scanner.py            + progress/cancel, + write_report()
  parsers/files.py      + progress/cancel
  parsers/notes.py      + progress/cancel
  parsers/wifi.py       QR code and password behind <details>
src/ssba/cli/main.py    + `ssba backups`; `scan` and `export all` use the shared pieces
src/ssba/gui/           NEW  PySide6 wizard (only calls ssba.core)
packaging/              NEW  PyInstaller spec + build script
```

Three ways to use the same engine, same results:

1. **GUI** — `SmartSwitch Backup Analyzer.exe` (or `ssba-gui` from a source
   install).
2. **Command line** — `ssba …` (also shipped as `ssba.exe` next to the GUI).
3. **Python scripts** — `from ssba.core.scanner import scan_backup`,
   `from ssba.core.parsers.notes import export_notes`, … — unchanged
   signatures; the new parameters are optional keyword arguments.

Installing from source: `pip install .` (engine + CLI) or `pip install
".[gui]"` (adds PySide6). `pyproject.toml` gains the `gui` extra
(`PySide6>=6.6`), `pytest-qt` in `dev`, a `build` extra (`pyinstaller>=6`),
and a `gui-scripts` entry `ssba-gui = "ssba.gui.app:main"`.

### `core/progress.py`

- `Progress` frozen dataclass: `stage: str` (e.g. `"scan"`, `"files"`,
  `"notes"`), `done: int`, `total: int | None`, `item: str` (category or file
  name, may be empty).
- `ProgressFn = Callable[[Progress], None]`.
- `CancelToken`: `cancel()`, `cancelled: bool`, `check()` → raises
  `OperationCancelled` when cancelled. Thread-safe (`threading.Event`).
- `OperationCancelled(Exception)`.
- Rule for every function that accepts them: `progress=None, cancel=None`
  keyword arguments; `check()` is called only **between** items (never while a
  file is being written), so everything already written stays valid.
  Without them, behaviour is exactly as today.

### Engine functions that gain `progress` / `cancel`

- `scan_backup(backup_root, out_dir, categories=None, *, progress=None,
  cancel=None)`: one progress event per source file (`stage="scan"`, `done` =
  categories finished, `total` = categories selected, `item` =
  `<category>/<file>`), then a final `(total, total, "")`; `check()` before
  each category and each file.
- `write_report(report, out_dir) -> Path` (new, in `scanner.py`): writes
  `report.json` exactly as `ssba scan` does today; the CLI now calls it.
- `export_files(…, *, progress=None, cancel=None)`: one event per planned
  file (`stage="files"`, `total` = planned files).
- `export_notes(…, *, progress=None, cancel=None)`: one event per note.
- The other exporters run in seconds on real data and get no progress
  parameters (the GUI shows them as one step each).

### `core/discovery.py`

- `BackupInfo` frozen dataclass: `path` (folder holding
  `backupHistoryInfo.xml`), `device_name` (`UserInputName`, may be empty),
  `model` (`ModelName`), `saved_at` (`datetime | None` from `SavedTime`),
  `size` (`FileSize` of the backup, bytes, `int | None`), `items`
  (`dict[str, int]`: category folder → `ItemsCount`, from each entry's
  `FileName` top folder, e.g. `CONTACT\Contact.spbm` → `CONTACT`).
- `default_roots() -> list[Path]`: `%USERPROFILE%\Samsung\SmartSwitch\backup`
  and `%USERPROFILE%\Documents\Samsung\SmartSwitch\backup` (existing ones
  only).
- `find_backups(roots=None) -> list[BackupInfo]`: every folder at most three
  levels below a root that contains `backupHistoryInfo.xml` (real layout:
  `<root>\SM-A137F\SM-A137F_\SM-A137F_20260922111112\`; a second identical
  phone gets another `<model>_…` folder), newest first. An unreadable or
  malformed XML still yields an entry with the folder name as model and
  empty fields (never an exception); a root that does not exist is skipped.
- `read_backup(path) -> BackupInfo` for a folder the user picks by hand;
  a folder without `backupHistoryInfo.xml` → `UnsupportedBackupError`.
- Real data (verified): `UserInputName`, `ModelName=SM-A137F`,
  `SavedTime=2026-09-22T11:58:15`, `FileSize=58392323062`, per-entry
  `FileName` + `ItemsCount` (e.g. `CONTACT\Contact.spbm` 797,
  `SAMSUNGNOTE\sdoc.snmm` 1866).

### `core/recovery.py`

The single list of exports, used by the CLI's `export all` and by the GUI:

- `Export` frozen dataclass: `key` (`"contacts"`, `"messages"`, `"calls"`,
  `"wifi"`, `"blocked-numbers"`, `"browser"`, `"clipboard"`, `"clock"`,
  `"notes"`, `"apps"`, `"files"`), `target` (the name inside the output
  folder, as `export all` uses today), `categories` (scan categories that
  make it available, e.g. `("CONTACT",)`, `("ALARM", "WORLDCLOCK")`, the
  storage + origin categories for `"files"`).
- `EXPORTS: tuple[Export, ...]` in `export all` order.
- `available_exports(scan_dir) -> list[Export]`: those with at least one of
  their categories in `report.json`.
- `run_export(export, scan_dir, out_dir, *, files_mode="copy",
  progress=None, cancel=None) -> ExportOutcome` — calls the matching
  `export_*` function; `ExportOutcome` dataclass: `key`, `ok: bool`,
  `result` (the exporter's result dataclass or `None`), `error: str | None`,
  `path: Path` (what to open). The module's export error →
  `ok=False, error=str(exc)`; `OperationCancelled` propagates; any other
  exception → `ok=False, error="unexpected: …"` (never stops the others).
- The CLI keeps its printed output; `_run_export_all` iterates `EXPORTS`
  (behaviour and messages unchanged).

### `parsers/wifi.py` page change

Each network row: name, security, hidden; then
`<details><summary>Show QR code</summary>` large QR (`scale=8`) `</details>`
and `<details><summary>Show password</summary>` password `</details>`
(no password → `—`, no QR for EAP/WEP or protected-without-password). No
scripts; the note about passwords stays. Tests updated: passwords and QR
codes are only inside `<details>` elements.

### `ssba backups` (new CLI command)

`ssba backups [--root <folder> …]` prints one line per backup found:
`<path>  <device name> (<model>)  <date>  <size>`; exit 0 even when none
(prints `no Smart Switch backups found in <roots>`).

## GUI (`src/ssba/gui/`)

- `app.py` — `main()`: `QApplication`, language, main window.
- `i18n.py` — `tr(key, **fmt)` over two dictionaries (`it`, `en`) of every
  visible string; language from `QLocale` (Italian if the system language is
  Italian, else English), switchable with a language button in the wizard's
  button row ("Italiano" / "English"); switching re-applies texts to every
  page. A test checks both dictionaries have
  the same keys.
- `worker.py` — `Worker(QThread)` running a callable with a `CancelToken`,
  relaying `Progress` through a Qt signal; signals `progressed(event)`,
  `succeeded(result)`, `failed(message)`, `cancelled()`.
- `wizard.py` — `QWizard` with the pages below; `pages/*.py` one module per
  page.

Pages:

1. **Backup** — list from `find_backups()` (device name, model, date, size);
   **Browse…** for another backup folder (validated with `read_backup`) or
   an existing scan folder (one with `report.json`: the decryption page is
   skipped). **Save to:** folder field + **Browse…**, default
   `Documents\SmartSwitch Recovery\<model>_<YYYY-MM-DD>`. Checks before
   **Next**:
   - the destination is not inside the backup folder;
   - free space (`shutil.disk_usage`) ≥ 2 × backup size (low-space dialog:
     Yes/No with a question text giving the free and needed amounts);
   - a destination that already holds unrelated files (not a previous SSBA
     run) is used only after a Yes/No confirmation;
   - a non-empty destination that already holds a scan is reused (the user
     is asked: reuse or start over).
2. **Decryption** — runs `scan_backup` + `write_report` into
   `<dest>\scan` in the worker; progress bar per category, current file,
   **Cancel** (asks for confirmation; a cancelled scan can be restarted).
3. **What to recover** — one checkbox per `available_exports()` entry,
   labelled with its item count from `BackupInfo.items` when known, all
   ticked; Wi-Fi shows "contains passwords"; for photos and files three
   choices: **Keep separate** / **Merge by copying** (default) / **Merge by
   moving** (explains: instant on the same disk, no extra space, the
   category folders are emptied).
4. **Recovery** — runs `run_export` for each ticked export into `<dest>`
   (targets from `EXPORTS`; files mode from page 3; "Keep separate" skips
   the files export and reports where the category folders are), one row per
   export with a status icon and, for files and notes, a progress bar;
   **Cancel** stops after the current file (what is done stays).
5. **Summary** — per export: ✔/⚠/✖, the key counts from its result, the
   error text when it failed, and **Open** (file → default program, folder →
   Explorer via `QDesktopServices`); **Open results folder**; **How to put
   this on a new phone** (short localized guide: contacts `.vcf`, SMS/calls
   with SMS Backup & Restore, Wi-Fi QR codes, bookmarks import, photos/files
   copy). Unexpected errors: a dialog with the full text (copyable) and the
   log file path.
- Log: `<dest>\ssba-gui.log` (Python `logging`: steps, counts, errors — no
  file contents).
- The window never blocks: all engine work runs in the worker.

## Packaging (`packaging/`)

- `ssba.spec` (PyInstaller, one-folder): two executables sharing one
  folder — `SmartSwitch Backup Analyzer.exe` (windowed, `ssba.gui.app`) and
  `ssba.exe` (console, `ssba.cli.main`). No custom icon yet (added when the
  project has artwork).
- `build.ps1`: creates a clean virtual environment, `pip install
  ".[gui,build]"`, runs PyInstaller, zips the folder as
  `SmartSwitch-Backup-Analyzer-<version>-windows.zip`.
- Publishing to GitHub Releases is manual and waits for the owner.

## Testing

- Engine (fabricated data): `progress` events (counts, order) and `cancel`
  (stops between items, what was written stays valid, a re-run resumes) for
  `scan_backup`, `export_files`, `export_notes`; `write_report` identical to
  the CLI's; `discovery` with fabricated `backupHistoryInfo.xml` trees
  (layout, second phone `_2`, malformed XML, missing roots, newest first,
  items per category); `recovery` (availability, outcomes, errors not
  stopping others, cancel propagating); Wi-Fi page (`<details>`).
- CLI: `ssba backups`; `scan`/`export all` output unchanged (existing tests).
- GUI with `pytest-qt` (offscreen): page flow, validation (destination
  inside the backup, low space warning), checkboxes only for available
  exports, worker progress and cancel, summary rows and open buttons,
  language switch, `it`/`en` key parity.
- Manual: build the `.exe`, run it on the owner's real backup (copy and
  move modes), check the summary numbers against the CLI validations.

## Constraints

- Python 3.10+. New dependencies only in extras: `PySide6>=6.6` (`gui`),
  `pytest-qt` (`dev`), `pyinstaller>=6` (`build`).
- `core/` never prints and never imports Qt; the GUI never re-implements
  engine logic.
- The CLI's commands, options and output stay compatible (additions only).
- No real personal data in the repository, tests or fixtures.
- No attribution lines in commits; nothing pushed; work on `master`.
