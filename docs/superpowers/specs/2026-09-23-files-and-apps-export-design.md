# Files Merge and App List Export (Phase 2, sub-project 3)

Status: approved design, not yet implemented.
Date: 2026-09-23

## Purpose

Phase 1 leaves the phone's files split across Smart Switch "categories"
(`Photo/`, `Video/`, `Music/`, `Docs/`, `EtcFile/`, `EtcFolder/`), each
holding part of the same Android storage tree. This sub-project lets the
owner browse them as the phone had them — one `DCIM/`, one `Download/`,
one `Android/media/…` — and lists the installed apps so they can be
reinstalled.

The project owner chose:

- three ways of handling the files: **merge by moving** them out of the
  category folders into one Android tree (no extra copy), **merge by
  copying** them (category folders kept), or **no merge** (files stay
  extracted in their category folders, as `ssba scan` left them);
- the owner's own copies of a file in two phone folders stay where they
  were (the tree mirrors the phone); only copies the backup itself made
  (same path in two categories) are merged;
- the originals the Gallery keeps for edited photos are included, in their
  own folder;
- apps: a page listing the installed apps with a Play Store link each (the
  backed-up APK files are only split parts; each app's base APK is inside a
  `.penc` file encrypted differently, so they cannot be installed).

## What Phase 1 gives us (verified against the real backup)

- Each storage category is a folder whose paths are the phone's storage
  paths: `Photo/DCIM/Camera/…`, `Docs/Download/…`,
  `Video/Android/media/com.whatsapp/…`, plus files at the storage root
  (`Docs/<name>.docx`). Many files are reported `undecoded` (HEIC, MP4, Opus,
  …) but are the original plain files, so files are found by walking the
  folders, not by report status.
- Each also holds a Smart Switch manifest:
  `<Category>/data/user/0/com.sec.android.easyMover/files/SmartSwitch/tmp/<TYPE>/<name>.json`
  = `{"categoryType", "count", "files": [{"FilePath", "FileName", "Length",
  "DateModified", …}]}`. `FilePath` is the full phone path starting with
  `/mnt/sdcard/` (the storage root); `DateModified` is in milliseconds.
  Real data: 17,171 entries (Photo 13,126, Docs 2,279, EtcFolder 951,
  Video 518, Music 264, EtcFile 33), **every one** matching a scanned file of
  the same size at `<Category>/<path after /mnt/sdcard/>`. The scanned files'
  own modification times are the backup date, not the original one.
- Overlaps: 940 paths exist in two categories (`Docs`+`EtcFolder` 910,
  `EtcFile`+`EtcFolder` 30), all byte-identical. Separately, 164 groups of
  identical files live at different paths (193 extra copies, 315 MB, mostly
  WhatsApp images also saved in `Pictures/` or `Download/`) — the owner's own
  copies, kept.
- `PHOTO_ORIGIN/` (396) and `VIDEO_ORIGIN/` (5):
  `data/sec/photoeditor/0/<name>` (flat) and
  `data/sec/photoeditor/0/storage/emulated/0/<phone path>` — the Gallery's
  originals of edited photos/videos; 42 share a file name with the edited
  version.
- `APKFILE/AppList.json` = `{"Apks": [{"ApkName", "ApkPkgName",
  "InstPkgName", "VersionName", "LastTimeUsed", …}]}` — 129 apps. The 292
  `*.apk` files are all `*_split_*` parts; the base APKs are the 129
  `.penc` files (7.3 GB, not decryptable today).

Sizes: ~29 GB of unique storage files, 0.6 GB of originals.

## Scope

In: `ssba export files` (modes `none`, `copy`, `move`), `ssba export apps`,
and both in `ssba export all`.

Out (non-goals): de-duplicating the owner's own copies; the `.penc` files and
split APKs; `MYFILES` (the My Files app's databases), `SAMSUNGNOTE` (already
exported by `export notes`), other app-data categories.

## Architecture

```
src/ssba/core/parsers/files.py   # plan the Android tree, then copy or move
src/ssba/core/parsers/apps.py    # AppList.json -> apps.html
src/ssba/cli/main.py             # export files --mode, export apps, export all --files
```

### `files` — planning

- `STORAGE_CATEGORIES = ("Photo", "Video", "Music", "Docs", "EtcFile",
  "EtcFolder")` in that order; `ORIGIN_CATEGORIES = ("PHOTO_ORIGIN",
  "VIDEO_ORIGIN")`.
- A category counts when `category_files` does not raise
  `MissingCategoryError` and `<scan_dir>/<Category>` is a directory; any other
  `ScanReportError` → `FilesExportError`. No category at all →
  `FilesExportError("no file categories found in the scan output")`.
- Storage files: every regular file under `<scan_dir>/<Category>` (walk
  without following symlinks), except the manifest folder
  `data/user/0/com.sec.android.easyMover`; target = the path relative to the
  category (the phone storage path).
- Original dates: from every manifest JSON in the storage categories,
  `FilePath` with a leading `/mnt/sdcard/` or `/storage/emulated/0/` removed →
  `DateModified / 1000` when it is a number > 0 (first entry wins). The match
  against the scanned file's path is case-insensitive, because Android's
  shared storage is: Smart Switch's manifest sometimes spells a folder with
  different letter case than the scanned file path (e.g. `Pictures/WhatsApp/`
  in the manifest vs `Pictures/Whatsapp/` on disk); the target path keeps the
  scanned file's own spelling. A manifest that is not readable JSON of that
  shape is ignored (counted in `bad_manifests`). Manifest entries with no
  scanned file at that path (case-insensitively) in any storage category →
  counted in `missing` (never an error). After a `move` the manifests stay in
  the scan, so a later run counts the moved files as missing — expected, and
  the CLI line says "not found in the scan".
- Originals: every regular file under `<scan_dir>/<ORIGIN category>`; its
  path relative to the category, with a leading
  `data/sec/photoeditor/0/storage/emulated/0/` or else
  `data/sec/photoeditor/0/` removed, goes under `_Edited photo originals/`.
- Order: storage categories in the order above (files sorted by path within
  each), then the originals.

### `files` — placing (`export_files(scan_dir, out_dir, mode)`)

- `mode` is `"copy"` or `"move"`; anything else → `ValueError`.
- Before placing anything: `out_dir` must not overlap any scanned category
  folder, checked two ways, since path-string comparison alone (even
  `resolve()`-based) cannot reliably tell a real self-reference apart from a
  same-file alias reached through a different spelling (an 8.3 short name, a
  directory junction, a symlinked ancestor, a UNC loopback path, ...):
  - nominal: `Path.resolve()` on both sides, then `is_relative_to` each way
    (cheap, catches most cases without touching the filesystem);
  - same-file: `os.path.samefile` along whichever side's ancestors actually
    exist — `out_dir` overlaps a category folder if any existing ancestor of
    `out_dir` (including `out_dir` itself, if it exists) is `samefile` with
    the category folder, or any ancestor of the category folder (including
    itself — always exists, since the category folder does) is `samefile`
    with `out_dir` (checked only when `out_dir` exists).
  Either way → `FilesExportError("the output folder must not be inside or
  contain a scanned category folder: …")`.
- For each planned file, target = `out_dir / <target path>`:
  - a candidate name that is a symlink is never followed or trusted — it is
    always treated as occupied (the numbered-copy search moves on);
  - target exists and is the very same file as the source
    (`os.path.samefile`) — two cases, distinguished by `os.stat(source).st_nlink`
    and whether source and candidate are the same directory entry
    (`os.path.samefile(source.parent, candidate.parent)` and
    `source.name.casefold() == candidate.name.casefold()`), never by
    comparing path strings:
    - `st_nlink >= 2` and they are *not* the same directory entry → a second
      hard link an earlier, interrupted `move` left behind (its
      `os.link(source, candidate)` succeeded but removing the source then
      failed — e.g. a read-only source — or the process stopped). The bytes
      are already safe at the target: in `move` mode the source is removed
      (counted in `already_present`, not treated as the overlap error); in
      `copy` mode nothing changes (also `already_present`);
    - anything else — a single-link file (`st_nlink == 1`), or literally the
      same directory entry — means `out_dir` resolves back onto its own
      source (the up-front check above somehow didn't catch it) →
      `FilesExportError`; nothing is deleted;
  - target exists and is identical (same size and same SHA-256) → nothing is
    written; in `move` mode the source is deleted. Counted in `merged` when
    the target was placed earlier in this run (a backup duplicate), else in
    `already_present` (a re-run);
  - target exists and differs → the file goes to the first free
    `<stem> (2)<suffix>`, `<stem> (3)<suffix>`… (an identical one found there
    counts as identical), counted in `conflicts`;
  - target is free → committed without ever writing to that final name
    directly: `move` first tries a direct `os.link(source, candidate)`
    (falling back to the copy path below only across volumes or where hard
    links aren't supported); `copy`, and that fallback, stage the bytes in a
    short, fixed-length, exclusively-created (`"xb"`) partial file in the
    same folder — `.ssba-<8 hex>.partial`, unrelated to the original name (so
    staging can't push a long filename past the filesystem's path-length
    limit), filled with `shutil.copyfileobj`. Only the call that actually
    created the partial (its `open(..., "xb")` succeeded) may ever delete it
    — a name collision with an unrelated, pre-existing file must never
    delete that file; on such a collision the failure propagates as
    `FilesExportError` rather than staging succeeding by chance. Once
    staged, commit with a no-clobber `os.link(partial, candidate)` followed
    by dropping the partial name (or `os.rename` when the filesystem has no
    hard links, with a `FileExistsError` from that `os.rename` — how Windows
    reports a concurrently-claimed name — handled the same way as from
    `os.link`; without hard-link support a narrow race remains on POSIX,
    where `os.rename` replaces a file created at that exact instant instead
    of failing). A name claimed by someone else in between (`FileExistsError`
    from `os.link` or that `os.rename`) is treated like any other occupied
    candidate: the search moves to the next numbered name, and the partial
    is removed.
  Existing files are never overwritten, and an interruption never leaves a
  truncated file under a final name — at most a hidden, short-named
  `.ssba-<hex>.partial` file, removed on a handled failure and otherwise
  inert (never reused, since the next run picks a fresh name).
- A source removal (after a hard link, after an identity match, after a
  copy-fallback commit) uses a helper that clears a Windows read-only bit
  and retries once if the plain delete raises `PermissionError`, so a
  read-only source is still moved instead of failing.
- After a file is placed, its modification time is set to its original date
  when known (`0 < t < 253402300800`; `OSError` ignored); counted in
  `dated`.
- `move` mode, at the end: empty folders left inside each category folder
  are removed (bottom-up), the category folder itself included when empty.
- A failure to read, copy or move → `FilesExportError("cannot <copy|move>
  <source>: …")`; a re-run resumes (placed files are identical or gone, or
  are recognized as the same file under a different name — see the
  `samefile` cases above).
- `FilesExportResult`: `placed`, `merged`, `already_present`, `conflicts`,
  `originals` (placed originals), `dated`, `missing`, `bad_manifests`.

### `apps` — `export_apps(scan_dir, out_path) -> AppsExportResult`

- Source: `category_files(scan_dir, "APKFILE")` entry named `AppList.json`
  (none → `AppsExportError`); JSON object with an `Apks` list (else
  `AppsExportError`).
- Each item that is an object with a non-empty `ApkPkgName`: name
  (`ApkName`, else the package), package, version (`VersionName`), installer
  (`InstPkgName`), last used (`LastTimeUsed` ms → `format_time`), and a link
  `https://play.google.com/store/apps/details?id=<package>` (URL-encoded)
  shown with `safe_link`. Items without a package → skipped (counted).
- Page `Apps` (via `page`), sorted by name (case-insensitive), with a note:
  the apps must be reinstalled from their store; their data is not in a
  restorable form. `AppsExportResult`: `apps`, `skipped`. Write failure →
  `AppsExportError("cannot write …")`.

## CLI

- `ssba export files <scan_dir> --out <dir> --mode none|copy|move`
  (`--mode` required):
  - `none`: nothing is changed; prints
    `files left in their category folders in <scan_dir>: <Category, …>`
    (the categories found); exit 0; no category → `error: …`, exit 1.
  - `copy`/`move`: prints `<placed> files copied|moved into <out>`, then when
    non-zero: `<merged> duplicate files of the backup merged`,
    `<already_present> files were already there`,
    `<conflicts> files had the same path but different content; kept as
    '<name> (2)'`, `<originals> originals of edited photos in <out/_Edited
    photo originals>`, `<dated> files got their original date back`,
    `<missing> files listed by Smart Switch were not found in the scan`,
    `<bad_manifests> Smart Switch file lists could not be read`.
- `ssba export apps <scan_dir> --out <apps.html>` prints
  `<n> apps listed in <out>` (+ skipped when non-zero).
- `ssba export all <scan_dir> --out <dir> [--files none|copy|move]`
  (default `none`): runs `apps` into `apps.html` and `files` with that mode
  into `<dir>/files`, after the existing kinds; summary
  `<n> of 11 exports written to <dir>`.

## Testing

Fabricated category folders, manifests and files only.

- Planning: phone paths kept; manifest folder excluded; dates from both
  prefixes; bad manifest ignored and counted; missing manifest entries
  counted; originals mapping (nested and flat); absent categories skipped;
  no category → error.
- Placing, both modes: tree layout; byte-identical content; backup
  duplicates merged once (move deletes the duplicate source only after the
  identity check, including a same-size-but-different-bytes case that a
  size-only check would miss); conflict → `(2)`; never overwrite; original
  dates set; re-run in copy mode → `already_present`, nothing rewritten;
  move empties and removes category folders but keeps what was not moved;
  invalid mode; `out_dir` equal to, inside, or containing a category folder
  → rejected before anything is touched, sources left untouched; an
  interrupted write leaves no file at the final name and a re-run then
  places it at the plain name; a name claimed by someone else between the
  existence check and the commit is not overwritten; a symlinked target is
  treated as occupied (skipped on platforms that cannot create symlinks
  without privilege); a read-only source is still moved; a hard link left
  by an interrupted move (`samefile` true, `st_nlink >= 2`, not the same
  directory entry) resumes as `already_present` in both modes rather than
  raising the overlap error; an existing file that happens to be named like
  a partial is left untouched; a `FileExistsError` from the no-hard-link
  `os.rename` fallback is treated as a taken name, with no partial left
  behind; `out_dir` reached through a directory junction pointing at a
  category folder is rejected (skipped if junctions can't be created without
  elevation); the up-front overlap check's `samefile`-based branch is
  reachable and raises (a portable stand-in, forcing `os.path.samefile`
  true, for an alias `resolve()` cannot normalize away, e.g. a UNC loopback
  path); a differently-spelled alias of the source (a parent `..`
  round-trip that `os.path.abspath` normalizes) is recognized as a real
  self-reference and raises without deleting the single-link source; a
  forced `samefile` match on a genuinely single-link file also raises,
  isolating the `st_nlink == 1` branch specifically; the partial name is
  short and fixed-length; a name collision with an unrelated pre-existing
  partial-like file never deletes that file.
- Apps: sorting, fallbacks, skipped items, link escaping, page escaping,
  errors.
- CLI: `files` each mode, `apps`, `export all` with default `none` and with
  `copy`, summary `of 11`.

Manual, local-only validation on the real scan, on a **copy** of the scan
folder for `move`: 17,171 storage files → 16,231 unique paths placed, 940
merged, 0 conflicts, 401 originals, every placed file's hash equal to its
source, 16,231 dated; 129 apps.

## Constraints

- Python 3.10+, no new dependency. `core/` never prints.
- `move` only ever deletes a source after it has been moved or proven
  identical to the file already at the target. Existing output files are never
  overwritten, and no write ever lands under a final name until it is
  complete (staged in a short, fixed-length, exclusively-created
  `.ssba-<hex>.partial` file — not derived from the target's name, so long
  filenames stay stageable — committed with a no-clobber hard link; only the
  call that actually created the partial may delete it, so a name collision
  with an unrelated file never deletes that file). `out_dir` is checked up
  front against every scanned category folder, both nominally
  (`resolve()`/`is_relative_to`) and via `os.path.samefile` along each
  side's ancestors, so a target can never resolve to its own source even
  through an alias `resolve()` doesn't normalize away (an 8.3 short name, a
  directory junction, a symlinked ancestor, a UNC loopback path). `_place`
  tells that same kind of real self-reference apart from a hard link an
  interrupted move left behind by `os.stat(source).st_nlink` (>= 2 only for
  a genuine second link) together with whether source and candidate are the
  same directory entry — never by comparing path strings, which cannot be
  trusted to catch every alias. A source removal survives a Windows
  read-only source.
- No real personal data in the repository, tests or fixtures.
- No attribution lines in commits; nothing pushed; work on `master`.
