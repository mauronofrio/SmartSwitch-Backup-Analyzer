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
- Support for password/PIN-protected backups.
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

- `core/` has no side effects beyond what's explicitly passed in: functions
  take bytes/paths in, return bytes/data structures out. No printing, no
  implicit file writes. This is what lets a future GUI call `core/` directly.
- `cli/` is the only layer that talks to stdout/stderr and decides where to
  write output files.
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
  - For each file directly under the category folder:
    - If it's a valid ZIP already (unencrypted outer wrapper, e.g.
      `Contact.spbm`, `CALLLOG.zip`): open it, recurse into its entries
      (files that themselves decrypt successfully, or are already
      plaintext/media, are kept; nothing here should be assumed encrypted
      just because it's inside a wrapper zip).
    - Else: attempt `container.decrypt_file`. If the sniffed kind is
      `binary` *and* decryption didn't produce a recognizable structure,
      record it as `undecoded` rather than guessing.
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
