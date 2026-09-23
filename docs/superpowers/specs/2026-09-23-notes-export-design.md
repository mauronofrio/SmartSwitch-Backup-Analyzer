# Samsung Notes Export

Status: implemented.
Date: 2026-09-23

## Purpose

Turn the Samsung Notes recovered by Phase 1 into plain files the owner can
keep, copy and open anywhere: the text of a note as a `.txt`, its attachments
(PDFs, images) as the files themselves, and Samsung Notes folders as real
folders. The project owner chose:

- deleted notes (Samsung Notes trash) exported too, in a separate `Trash/`
  folder;
- a note with text **and** attachments → files side by side in its folder
  (`Title.txt`, `Title.pdf`, `Title_2.jpg`), not a sub-folder per note.

Whether other apps can import the result is a later, separate research step.

## What Phase 1 gives us (verified against the real backup)

`SAMSUNGNOTE/sdoc.snmm/sdoc.bk/` holds:

- `SmartSwitchRestoreDB/sdoc.db` — Samsung Notes' SQLite database
  (report status `plaintext_passthrough`, kind `sqlite`), with
  `sdoc.db-wal` next to it: a valid WAL (magic `377f0682`) holding recent
  changes, which Phase 1 reports as `undecoded` because it does not
  recognize the format. It must be read together with the database.
- `b_<stem>.sdocx/` — one **folder** per note (Phase 1 already unpacks the
  `.sdocx` ZIPs): `note.note`, `*.page`, `end_tag.bin`, `pageIdInfo.dat`
  and `media/`:
  - `N@pdf_<ms>.pdf`, `N@paste_…jpg`, `N@files_…png` … — the attachments,
    ordered by the `N@` index. 9 of the PDFs are reported `undecoded` by
    Phase 1 (not `%PDF`-headed, e.g. signed PDFs) but are the original
    files and are exported as they are.
  - `N@page_<n>.spi` — Samsung pen-drawing data (proprietary, not exported).
  - `mediaInfo.dat` — hashes (not exported).

Database (tables used):

| Table | Columns used |
|---|---|
| `sdoc` | `_id`, `UUID`, `title` (text), `displayTitle` (blob, UTF-8), `content` (blob, UTF-8), `categoryUUID`, `filePath`, `isDeleted`, `createdAt`, `lastModifiedAt` (ms) |
| `category_tree` | `UUID`, `parentUUID`, `displayName`, `path` |
| `text_search` (optional) | `sdocUUID`, `strippedContent` |

Facts from the real data:

- 2386 notes: 1866 active, 520 deleted. The note's folder is
  `b_<stem>.sdocx`, where `<stem>` is the basename of `filePath` without
  `.sdocx`; all 1866 active notes have one, no deleted note does.
- `content` is only a **preview** (at most ~335 bytes). The full text, with
  line breaks, is `text_search.strippedContent` (237 notes). 4 active notes
  have a preview but no index entry; 74 deleted notes have only a preview.
- Active notes: ~1625 hold one PDF (one holds 109), ~241 are text, a few
  hold images; 81 have `.spi` drawing data (handwriting, often on a PDF).
  Handwriting itself cannot be rendered.
- 29 folders. Roots: `Uncategorized` (`path` `uncategorized:///`, 501 notes,
  the parent of 19 user folders), `Trash` (`trash:///`), `Old notebooks`
  (`old:///`). Maximum depth 2 below a root.

## Scope

In: `ssba export notes`, and `notes` added to `ssba export all`.

Out (non-goals): rendering handwriting or pen annotations; rich-text
formatting (bold, checklists — `strippedContent` is plain text); original
attachment file names (Samsung Notes does not keep them); importing into
other apps (later research).

## Architecture

```
src/ssba/core/parsers/notes.py   # read the database + note folders, write files
src/ssba/cli/main.py             # export notes; export all runs 9 kinds
```

`core/` never prints and only writes under the output directory.

### Reading — `read_notes(scan_dir) -> list[Note]`

- `Note` dataclass: `title: str`, `folder: tuple[str, ...]`,
  `text: str | None`, `text_source: str | None` (`"index"`, `"preview"` or
  `None`), `attachments: list[Path]`, `created: float | None`,
  `modified: float | None` (Unix seconds), `deleted: bool`,
  `file_missing: bool`, `has_drawings: bool`.
- Database: the `category_files(scan_dir, "SAMSUNGNOTE")` entry named
  `sdoc.db` whose parent folder is `SmartSwitchRestoreDB`; none →
  `NotesExportError`. It is copied to a temporary directory together with
  `sdoc.db-wal` when that sibling file exists and starts with a WAL magic
  (`377f0682`/`377f0683`), whatever its report status, and the copy is
  opened (so the original is never modified and the WAL is applied). The
  connection's `text_factory` decodes TEXT columns as UTF-8 with
  `errors="replace"`, so a row with invalid UTF-8 in `title` or
  `strippedContent` becomes U+FFFD in that field instead of aborting the
  whole read with `sqlite3.OperationalError`. The connection is closed
  before the temporary directory is removed. Missing
  `sdoc` or `category_tree` → `NotesExportError`; any `sqlite3.Error` or
  `OSError` while reading → `NotesExportError("cannot read …")`.
- Notes root: the database's grandparent directory (`sdoc.bk`).
- Folders: each `category_tree` row's path is its `displayName` chain from
  the root (a `parentUUID` cycle stops the walk). A chain starting at the
  root whose `path` is `uncategorized:///` drops that root when it has more
  elements (user folders appear at the top level); notes directly in that
  root get `("Uncategorized",)`. Other roots keep their name. Empty
  `displayName` → `Untitled folder`. A note whose `categoryUUID` is unknown
  → `("Uncategorized",)`. A deleted note → `("Trash",)`.
- Title: `title` whitespace-collapsed; else `displayTitle` decoded; else
  `Untitled <YYYY-MM-DD of createdAt>` (or `Untitled note`).
- Text: the note's first non-blank `text_search.strippedContent`, read with
  `ORDER BY rowid` so which one wins is deterministic when a `sdocUUID` has
  more than one row → `"index"`; else a non-blank decoded `content` →
  `"preview"`; else `None`.
- Note folder: `<root>/b_<stem>.sdocx` when `<stem>` matches
  `[0-9A-Za-z_.-]+` and the directory exists; otherwise `file_missing`.
- Attachments: files in its `media/` except `mediaInfo.dat` and `*.spi`,
  ordered by the integer before `@` (names without one last, by name).
  `has_drawings` = any `*.spi` in `media/`.
- Notes in `createdAt`, `_id` order.

### Writing — `export_notes(scan_dir, out_dir) -> NotesExportResult`

- No notes → `NotesExportError`.
- Each note goes in `out_dir/<folder parts…>` (each part made safe).
- Before any note is planned, every folder that will be created is
  reserved in its parent folder's used-names set (one entry per
  `(parent parts, child name)` pair across every note's folder path). This
  stops a category folder from colliding with a note's file — e.g. a
  category `Nota.txt` under `Lavoro` and a note `Nota` in `Lavoro`: the
  note is renamed (`Nota (2).txt`) instead of `mkdir()` crashing on a name
  already taken by a file, or a file write crashing on a name already
  taken by a directory.
- Safe names (`safe_name`): `< > : " / \ | ? *` and characters below
  U+0020 → `_`; strip, drop trailing dots/spaces; at most 100 characters;
  empty → `Untitled`; a Windows reserved device name (`CON`, `PRN`, `AUX`,
  `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`, before the first dot,
  case-insensitive) gets a leading `_` (a trailing one would leave
  `con.txt_` still reserved).
- File names: base = `safe_name(title)`, then `base (2)`, `base (3)`… until
  neither that base (claimed by another note) nor any of the note's file
  names is already used in that output folder (case-insensitive) — so two
  notes never share a base and never look like one note. The note writes:
  - `<base>.txt` when it has text **or** has no attachments;
  - its attachments as `<base><ext>`, `<base>_2<ext>`, `<base>_3<ext>`…
    (`<ext>` = the original suffix, lower-cased); an attachment name equal
    to the `.txt` name becomes `<base>_attachment<ext>`.
- `.txt` content (UTF-8, `\n` line ends; `\r\n`/`\r` in the text become
  `\n`):
  - when `file_missing`: a first line — `Deleted note from the Samsung
    Notes trash; its file is not in the backup.` (deleted) or `This note's
    file is not in the backup.` — then `Created: …` and `Modified: …`
    (local time, `unknown` when absent);
  - when the text is a preview: the line `Only a preview of this note's
    text was kept; it may be cut short.`;
  - a blank line after any such header, then the text; without text:
    `(no text)` when `file_missing`, else `(This note contains only
    handwriting or drawings, which cannot be exported.)`.
- Attachments are copied byte for byte.
- Every written file gets the note's `modified` time as its modification
  time, set only when it is between 0 (exclusive) and 253402300800
  (year 9999, exclusive) — an out-of-range or garbled `lastModifiedAt`
  (e.g. milliseconds stored as microseconds) is silently skipped instead
  of raising `OSError` (`OverflowError`/`ValueError`/`OSError` from
  `os.utime` are all caught).
- Any `OSError` → `NotesExportError("cannot export '<title>': …")`.
- `NotesExportResult`: `notes`, `text_notes` (with text),
  `preview_only`, `attachments` (files copied), `handwriting_only` (folder
  present, no text, no attachment), `missing_files`, `with_drawings`,
  `trashed`.

## CLI

`ssba export notes <scan_dir> --out <dir>` prints
`<n> notes written to <dir> (<t> with text, <a> attachments)`, then when
non-zero: `<n> notes from the trash in <dir/Trash>`, `<n> notes only had a
text preview (it may be cut short)`, `<n> notes contain only handwriting or
drawings, which cannot be exported`, `<n> notes had handwriting or drawings
that are not exported`, `<n> notes had no file in the backup (title and
saved text only)`. Exit 0; `NotesExportError` → `error: …`, exit 1.

`ssba export all` runs `notes` last, into `<dir>/notes`, and its summary
becomes `<n> of 9 exports written to <dir>`.

## Testing

Fabricated data only: a reduced `sdoc.db` (the four tables above), note
folders with fake media bytes, and a WAL-only row (the database written in
WAL mode and copied while the writer is still open).

- Reading: folder chains (uncategorized root dropped, other roots kept,
  unknown category, cycle), deleted → Trash, title fallbacks, text from
  index vs preview vs none, attachment order and exclusions, drawings,
  missing folder, unsafe `filePath` stem, WAL-only row present, database
  unchanged, missing table, no database.
- Writing: safe names (unsafe characters, reserved names, length, empty),
  collisions between notes (`(2)`), text + attachments side by side,
  attachment named like the `.txt`, placeholders and headers, `\r\n`
  normalization, byte-identical attachments, modification times, counts,
  unwritable output.
- CLI: `export notes` success and error; `export all` now 9 kinds.

Manual, local-only validation on the real scan (outputs under the
git-ignored `out/`): 2386 notes (520 in `Trash/`); every attachment in
every `b_*.sdocx/media/` except `mediaInfo.dat`/`*.spi` present
byte-identical; every `text_search` text found whole in its `.txt`; folder
names match `category_tree`.

## Constraints

- Python 3.10+, no new dependency. `core/` never prints.
- No real personal data in the repository, tests or fixtures.
- No attribution lines in commits; nothing pushed; work on `master`.
