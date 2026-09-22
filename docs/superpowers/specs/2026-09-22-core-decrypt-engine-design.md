# SmartSwitch Backup Analyzer — Core Decrypt Engine (Phase 1)

Status: approved design, not yet implemented.
Date: 2026-09-22

## Purpose

Samsung Smart Switch PC backups ("basic", no user-set backup password) store
most categories (Notes, Contacts, Call log, and others) encrypted with a
per-session key that is not published anywhere, but is fully recoverable from
data already present in the backup itself. This project provides an open
source tool to decrypt and recover data from a user's own Smart Switch
backup, starting with a generic decryption engine that works across
categories, followed by category-specific parsers that turn the decrypted
data into human-usable output (initially: a browsable HTML export, one
category at a time, starting with the one already validated: Notes).

This spec covers **Phase 1 only**: the generic decrypt engine. Category
parsers (Contacts, Call log, etc.) are out of scope here and will get their
own design pass once Phase 1 is implemented and validated against a real
backup.

## Background / what we already verified manually

Working through this by hand against a real SM-A137F Smart Switch backup
(category: Samsung Notes) established the following, which this project
turns into reusable code:

1. The backup root folder (e.g. `SM-A137F_<timestamp>/`) contains
   `backupHistoryInfo.xml` with a `<Dummy>` element: a hex string, itself
   encrypted.
2. `<Dummy>` is decrypted with **AES-128-ECB**, fixed key (ASCII bytes)
   `0b1e96db05d64ea4`, no IV, PKCS-style zero padding stripped from the
   plaintext. The result is a hex string (32-128 chars, even length) — the
   **session dummy**.
3. The AES key used for the rest of the backup's encrypted files is
   `SHA-256(session_dummy_ascii_string)`, truncated to the first 16 bytes
   (AES-128).
4. Individual encrypted files/blobs across *different categories* all follow
   the same envelope: first 16 bytes = IV, remainder = AES-128-CBC
   ciphertext (no separate authentication tag). Decrypting produces either:
   - a valid ZIP (`PK\x03\x04` signature) — e.g. Notes' `sdoc.bk`, Contacts'
     `Contact.bk` (itself found inside a plain outer ZIP, `Contact.spbm`)
   - plain XML/JSON/text directly — e.g. Call log's `call_log.exml` inside
     `CALLLOG/CALLLOG.zip` decrypts straight to `<?xml ...><CallLogs>...`
5. Confirmed today against the real backup for **three different
   categories** (Notes, Contacts, Call log) with the *same* key/algorithm —
   no per-category crypto variant needed for "basic" (no password) backups.
6. Categories may wrap their encrypted payload in a plain (unencrypted) ZIP
   first (`Contact.spbm`, `CALLLOG.zip`), or have the encrypted blob directly
   as the category's file (`sdoc.bk` via `sdoc.snmm`). The engine must handle
   both: try to unzip a category's file first, and treat anything that isn't
   a valid zip as a directly-encrypted blob.
7. Password/PIN-protected backups use a different, more complex key
   derivation (PBKDF2-based, per published forensic research) and are
   explicitly **out of scope** for Phase 1 — the engine should detect and
   report "unsupported (password-protected backup)" rather than silently
   failing or producing garbage.

## Non-goals (Phase 1)

- Understanding/parsing what any category's decrypted data *means* (that's
  category parsers, later phases).
- Support for password/PIN-protected backups. **Known gap, recorded after
  the final review (not silently dropped):** the "detect and report
  'unsupported (password-protected backup)'" behavior described above under
  Background item 7 is *not implemented* in this phase. Today, scanning a
  password-protected backup with this tool produces a report full of
  `"undecoded"` entries (the encrypted files just don't decrypt with the
  no-password key derivation) but likely still exits 0, because unencrypted
  wrapper zips and other already-plaintext files still count as
  `plaintext_passthrough` "success" — there is currently no positive
  detection of "this whole backup uses a scheme we don't support" as
  distinct from "some individual files didn't decrypt." Implementing real
  detection needs its own design pass (how to distinguish a systematically
  wrong key from a few odd/corrupt files without false-positiving on normal
  `undecoded` categories) and is deferred to Phase 2, not attempted as a
  quick heuristic here.
- A GUI (explicitly deferred by the project owner to a later phase, after
  the CLI and at least a few category parsers exist).
- Modifying or writing anything back into a Smart Switch backup — this is
  read-only recovery tooling.

## Architecture

Two layers, so the same logic can be reused later by a GUI without
rewriting it:

```
src/ssba/
├── core/
│   ├── session.py      # locate + decrypt the per-backup session Dummy
│   ├── crypto.py        # derive_key(dummy) -> bytes; decrypt(raw, key) -> bytes
│   ├── container.py     # decrypt one file, sniff the resulting content type
│   └── scanner.py       # walk a backup root, find + decrypt every category's files
└── cli/
    └── main.py          # thin CLI wrapping core/
```

- `core/` never prints or writes to stdout/stderr — only `cli/` does that.
  **Correction (post-implementation, recorded after the final review found
  the original wording below didn't match what got built):** `core/scanner.py`
  *does* write decrypted/passthrough file content to disk, under the
  `out_dir` its caller passes in — decrypted category data can run into the
  tens of GB for a real backup, so buffering it all in memory to return as
  data structures and let `cli/` write it isn't viable. What `core/` still
  never does is *decide* where output goes beyond the `out_dir` it's given,
  or talk to stdout/stderr. A pure, no-I/O `core/` (e.g. via an injectable
  write-sink callback) is deferred to whenever Phase 2 actually needs to
  call `scan_backup` from a GUI or in-memory context without materializing
  files — not needed yet, since nothing does that today.
- `cli/` is the only layer that talks to stdout/stderr and decides *which*
  output directory is used (it still owns that decision — it's just that
  `core/scanner.py` is who does the actual writing into it).
- Category-specific interpretation (Phase 2+) will live under
  `core/parsers/<category>.py`, each consuming the *already-decrypted* bytes
  `core/scanner.py` produces — parsers never touch crypto directly.

### `core/session.py`

- `get_session_dummy(backup_root: Path) -> str`
  - Reads `backupHistoryInfo.xml` from `backup_root`.
  - Extracts the `<Dummy>` element (there must be exactly one; error if zero
    or more than one — a backup format we don't recognize).
  - Decrypts it with the fixed AES-128-ECB key, strips trailing zero
    padding, validates the result is even-length hex, 32-128 chars.
  - Raises a typed `UnsupportedBackupError` with a clear message if any step
    fails (e.g., different Smart Switch version, or the file is missing).

### `core/crypto.py`

- `derive_key(session_dummy: str) -> bytes` — `SHA-256(session_dummy)[:16]`.
- `decrypt_iv_prefixed(raw: bytes, key: bytes) -> bytes` — split IV (first 16
  bytes) / ciphertext (rest, truncated to a multiple of 16), AES-128-CBC
  decrypt, no padding validation (Smart Switch payloads don't reliably use
  PKCS7 — we return the raw decrypted bytes and let `container.py` sniff/trim
  based on content, same approach validated manually for Notes).

### `core/container.py`

- `sniff_kind(data: bytes) -> Literal["zip","xml","json","sqlite","text","binary"]`
- `decrypt_file(raw: bytes, key: bytes) -> DecodedBlob` (dataclass: `data:
  bytes`, `kind: str`) — decrypts + sniffs in one call, used by the scanner
  for every candidate encrypted file.

### `core/scanner.py`

- `list_categories(backup_root: Path) -> list[str]` — one entry per
  top-level subfolder of the backup root (Phase 1 doesn't need to know what
  they mean).
- `scan_category(backup_root: Path, category: str, key: bytes) -> CategoryResult`
  - For each file under the category folder, **recursively** (some real
    categories — e.g. `Photo`, `Video`, `Docs` — store their content in
    subdirectories, not directly in the category folder; a "top-level files
    only" reading of this spec was implemented first and found, by the
    final review against a real 49GB backup, to silently skip 17,641 real
    files including 13,127 photos — corrected to recursive before Phase 1
    was considered done):
    - If it's a valid ZIP already (unencrypted outer wrapper) or decrypts to
      one, whether to open it and recurse into its entries is **not** a
      blanket default — an earlier version of this spec described "any
      valid ZIP gets opened," but inspection against the real 49GB backup
      found this exploded the user's own Office documents and plain `.zip`
      files into directories of raw parts. The actual rule, in precedence
      order (see `scanner.py`'s `_should_recurse_into_zip` /
      `_is_known_smart_switch_container`):
      1. `.apk`/`.jar` (by extension, case-insensitive) → never recurse,
         always preserved as a single file, regardless of anything else.
      2. Content-based document detection: a root-level
         `[Content_Types].xml` entry (Office Open XML — docx/xlsx/pptx/…,
         regardless of the file's own name/extension) or a root-level
         `mimetype` entry starting with `application/vnd.oasis.opendocument.`
         (ODF) or equal to `application/epub+zip` (EPUB) → never recurse,
         preserved as a single file.
      3. Known Smart Switch container recognition — recurse only if the
         file is recognized as Smart Switch's own internal packaging, by
         any of:
         - Exact filename match against a small, hand-verified catalog
           (`sdoc.snmm`, `sdoc.bk`, `Contact.spbm`, `Contact.bk`,
           `CALLLOG.zip`);
         - A known proprietary extension (currently `.sdocx`, Samsung
           Notes' per-note package format — the id varies per note, so
           these can't be exact-name catalogued);
         - The file's name, minus extension, exactly matches the category
           folder it's being scanned under (e.g. `WIFICONFIG/WIFICONFIG.zip`,
           `SBROWSER/SBROWSER.zip`) — roughly 90 real categories store
           their payload in a wrapper named identically to the category
           itself; this general pattern subsumes `CALLLOG.zip` as one
           instance of it.
      4. Otherwise → **do not recurse**; preserve as a single file. This is
         the default for anything not specifically recognized above,
         including the user's own arbitrary `.zip` files and any Smart
         Switch container not yet identified by one of the three
         mechanisms above.

      Whether or not a zip is recursed into, decryption of its own bytes
      (if it arrived encrypted) still always happens first and
      independently — the recursion decision above only controls whether
      the (already decrypted, if necessary) zip's *entries* are unpacked
      further, not whether the file itself gets decrypted.
    - Whatever the outcome above, attempt `container.decrypt_file` on any
      file that doesn't already sniff as zip/media/plaintext. If the
      sniffed kind is `binary` *and* decryption didn't produce a
      recognizable structure, record it as `undecoded` rather than
      guessing.
  - Returns a `CategoryResult` with per-file status (`decrypted`,
    `plaintext_passthrough`, `undecoded`, `error`) — never raises for a
    single file's failure; the category-level scan always completes.
- `scan_backup(backup_root: Path, out_dir: Path) -> BackupReport` — orchestrates
  `get_session_dummy` + `derive_key` once, then `scan_category` for every
  category, writing decrypted output under `out_dir/<category>/...` mirroring
  the original relative paths, and returns/writes a JSON summary report
  (counts of decrypted/undecoded/error per category).

### `cli/main.py`

- `ssba scan <backup_root> --out <out_dir> [--category NAME ...]`
- Prints a human-readable summary of `BackupReport` at the end (per category:
  N decrypted, N undecoded, N errors); exits non-zero if every category
  failed, zero otherwise (partial success is still success for this tool's
  purpose — recovery, not validation).
- `ssba scan --out <out_dir> --auto` (later, optional): try to auto-locate a
  Smart Switch backup under `%USERPROFILE%\Samsung\SmartSwitch\backup` on
  Windows. Not required for Phase 1 — explicit path is enough to ship.

## Error handling

- A category that doesn't decrypt with the standard (no-password) scheme is
  recorded as `unsupported` in the report with a human-readable reason
  (e.g. "looks password-protected — not supported yet") and the scan
  continues with the next category. The tool never aborts the whole run
  because of one bad category.
- `backupHistoryInfo.xml` missing or unparsable → the whole scan aborts
  early with a clear error (there is no key to derive without it).

## Testing strategy

- All automated tests run against **synthetic fixtures generated by the test
  suite itself** — a fake `backupHistoryInfo.xml` with a `<Dummy>` value
  encrypted the same way real Smart Switch does it (test code encrypts a
  known plaintext dummy with the fixed ECB key), plus a couple of fake
  category files encrypted the same way with fabricated content (e.g. a
  tiny made-up "call log" XML). No real backup data, no data derived from
  the project owner's personal backup, ever committed to the repository.
- Unit tests: `crypto.py` round-trip (encrypt-with-known-key /
  decrypt-with-derive_key), `session.py` against the synthetic
  `backupHistoryInfo.xml`, `container.py` sniffing for each supported kind.
- Integration test: `scanner.scan_backup` against a small synthetic backup
  tree fixture (2-3 fake categories) end to end.
- A manual/local-only test path (documented, not run in CI, never touches
  git) lets the project owner point the CLI at their real backup to
  smoke-test against real-world data shapes; this is explicitly not part of
  the committed test suite.

## Licensing / repo hygiene (carried over from earlier discussion, recorded here for completeness)

- License: AGPL-3.0, plus a README note that commercial use requires a
  separate license — contact the project owner. (Not implemented as part of
  this spec; tracked for the implementation plan.)
- `.gitignore` must exclude any local backup/output directories by default
  (e.g. a conventional `backups/`, `output/` at the repo root) so a
  contributor running the tool against their own backup doesn't accidentally
  commit personal data.
- Repo name: `SmartSwitch-Backup-Analyzer`, local path
  `D:\SmartSwitch-Backup-Analyzer` (separate from the project owner's
  personal recovered-data folder). GitHub push happens only when the
  project owner explicitly asks for it.

## Open questions for Phase 2 (not blocking Phase 1, recorded so they aren't lost)

- Which categories to build parsers for first, once Phase 1 is validated
  against the real backup (candidates already confirmed decryptable today:
  Notes — done separately already — Contacts, Call log).
- Whether `scan_category`'s "wrapper zip vs. direct blob" heuristic holds for
  every category, or some categories need a small per-category hint (to be
  determined empirically once we scan the full real backup with Phase 1).
