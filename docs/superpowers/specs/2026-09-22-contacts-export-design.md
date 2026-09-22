# Contacts Export (Phase 2, sub-project 1)

Status: approved design, not yet implemented.
Date: 2026-09-22

## Purpose

Turn the contacts already recovered by Phase 1 (`ssba scan`) into a single
`.vcf` file that imports cleanly into any phone or contacts service, without
the project owner having to dig through the scan output tree.

This is the first of three Phase 2 sub-projects agreed with the project owner:

1. **Contacts export** (this spec).
2. SMS, call log and other structured data — research spike first, to find
   out what is actually restorable to a normal Android device and in which
   format, before any design.
3. Consolidating the "file" categories (`Photo`, `Video`, `Music`, `Docs`,
   `EtcFolder`, `EtcFile`, `MYFILES`, `PHOTO_ORIGIN`, `VIDEO_ORIGIN`, ...) into
   one de-duplicated tree mirroring the Android storage layout (`Download/`,
   `DCIM/`, ...), since several categories are overlapping views of the same
   folders (e.g. the same PDF was found under both `Docs/Download/` and
   `EtcFolder/Download/`).

It is also the first module under `core/parsers/`, so it sets the pattern the
later parsers follow: read Phase 1's output, never touch crypto.

## What Phase 1 already gives us (verified against the real backup)

Inside the decrypted `CONTACT` category, `ssba scan` already writes real
vCard 2.1 files:

| File (under `CONTACT/Contact.spbm/Contact.bk/`) | Cards | Meaning |
|---|---|---|
| `@@<google-account>@@com.google.vcf` | 795 | contacts synced to the Google account |
| `@@vnd.sec.contact.phone@@vnd.sec.contact.phone.vcf` | 2 | contacts stored on the phone only — **not** in Google, so lost if the owner only restores from Google |
| `profile.vcf` | 1 | the owner's own card (name, phone, e-mail, job, birthday, photo) |

The account e-mail is part of the file name, so the exact path differs per
backup — the parser must discover files, not hard-code paths.

A throwaway spike (nothing committed) parsed these real files with `vobject`
and found three Samsung quirks that a naive parse gets wrong:

1. **Empty property parameters.** Samsung writes headers like
   `PHOTO;ENCODING=BASE64;PREF;JPEG; :` (whitespace-only parameter before the
   colon) and `BDAY;;:--12-25` (empty parameter). `vobject` rejects both. Parsing
   the whole file at once stopped at the first bad line: 685 of 795 Google
   contacts read, 110 silently lost, profile not read at all. Dropping empty /
   whitespace-only parameters from each property header before parsing, and
   parsing card by card, makes all **798 of 798** cards parse.
2. **No `FN` anywhere.** None of the 798 cards has `FN` (formatted name), which
   vCard 3.0 requires. Three cards also have no `N`.
3. **Non-standard properties.** Property inventory across all files:
   `N` 795, `TEL` 708, `EMAIL` 95, `ORG` 86, `PHOTO` 22, `TITLE` 2, `NOTE` 1,
   `BDAY` 1 (standard); `X-FAVORITE` 3, `X-ANDROID-CUSTOM` 2 (valid `X-`
   extensions); **`GROUP_MEMBER` 901** (Samsung group membership, and not even a
   valid vCard property name — underscores aren't allowed) and **`DEPARTMENT`
   2** (not a vCard property; vCard puts the department in `ORG`'s second
   component).

The spike also confirmed that, after the sanitizing step, quoted-printable
UTF-8 names decode correctly (including emoji), the profile's embedded JPEG
(~308 KB) round-trips, and the year-less birthday `--12-25` is preserved.

## Scope

In:
- Discover every contact `.vcf` Phase 1 recovered, from `report.json`.
- Parse each card independently, fixing the quirks above.
- Write one merged vCard 3.0 file.
- Never drop a card silently: anything that still can't be parsed is written,
  untouched, to a side file and counted.

Out (non-goals):
- Uploading or test-importing the contacts into any real account or service.
  Compatibility is checked offline only (see Testing) — the project owner's
  personal data never leaves the machine.
- De-duplication across sources. Android keeps each account's contacts in a
  separate partition; the real data shows no overlap between the Google file,
  the phone-only file and the profile.
- `GroupBulk.bin` and `SpeedDials.json` (group definitions and speed dials) —
  not needed for an importable contact list.
- Any change to Phase 1 (`ssba scan`) or the crypto layer.

## Architecture

```
src/ssba/core/parsers/
├── __init__.py
└── contact.py      # discover + normalize + merge; no printing
src/ssba/cli/main.py  # new subcommand: ssba export contacts
```

`core/parsers/contact.py` follows the same rules as the rest of `core/`: it
never prints and only writes to paths its caller passes in.

### Public interface (`ssba.core.parsers.contact`)

- `find_contact_sources(scan_dir: Path) -> list[ContactSource]`
  - `ContactSource`: dataclass `path: Path` (absolute path on disk),
    `label: str` (file name), `is_profile: bool` (`True` for `profile.vcf`).
  - Reads `scan_dir / "report.json"`; raises `ContactExportError` if it is
    missing or not valid JSON.
  - Takes the category whose name is exactly `"CONTACT"`; raises
    `ContactExportError` if absent.
  - Keeps every file entry whose `path` ends in `.vcf` (case-insensitive) and
    whose `status` is `"decrypted"` or `"plaintext_passthrough"`; resolves it to
    `scan_dir / "CONTACT" / <path>`; skips (and does not fail on) entries whose
    file is missing on disk.
  - Order: the profile first, then the rest sorted by file name.
- `parse_cards(text: str) -> tuple[list[vobject.base.Component], list[str]]`
  - Splits `text` into cards (`BEGIN:VCARD` ... `END:VCARD`), sanitizes each,
    parses each with `vobject.readOne`, normalizes each (rules below).
  - Returns (normalized cards, raw text of cards that failed to parse).
- `export_contacts(scan_dir: Path, out_path: Path) -> ContactExportResult`
  - `ContactExportResult`: dataclass `exported: int`,
    `per_source: dict[str, int]` (label → exported count),
    `unparsed: int`, `unparsed_path: Path | None`.
  - Writes all normalized cards, in source order, to `out_path` (UTF-8).
  - If any card failed to parse, writes those raw cards, unchanged, to
    `<out_path stem>_unparsed.vcf` next to `out_path`; otherwise creates no
    such file.
  - Raises `ContactExportError` if no sources are found or zero cards export.
- `ContactExportError(Exception)`.

### Normalization rules (applied to every card, in this order)

1. **Sanitize headers** (before parsing). For each line that is not a folded
   continuation (does not start with space/tab) and contains `:`, split at the
   first `:`, split the header part on `;`, drop parameters that are empty or
   whitespace-only, and rejoin. Lines are otherwise untouched.
2. **Parse** the sanitized card with `vobject.readOne`. A failure puts the
   *original* (unsanitized) card text in the unparsed list; move to the next
   card.
3. **`GROUP_MEMBER` → `CATEGORIES`.** Collect every `GROUP_MEMBER` value on the
   card, de-duplicated in first-seen order, into a single `CATEGORIES`
   property; remove all `GROUP_MEMBER` properties.
4. **`DEPARTMENT` → `ORG`.** If the card has `ORG`, set its value to
   `[<existing first ORG component>, <department>]` (any further existing
   components are replaced — the real data never has them); if not, create
   `ORG` with value `[<department>]`. Remove `DEPARTMENT`.
5. **Synthesize `FN` if missing**, using the first non-empty of:
   `N` (prefix, given, additional, family, suffix joined by single spaces) →
   first `ORG` component → first `EMAIL` → first `TEL` → `"Unknown"`.
6. **Set `VERSION` to `3.0`.** Everything else (`TEL`, `EMAIL`, `PHOTO`,
   `BDAY`, `NOTE`, `TITLE`, `X-*`) is kept as `vobject` parsed it and is
   re-serialized by `vobject` as vCard 3.0 (UTF-8, no quoted-printable,
   photo as base64).

## CLI

```
ssba export contacts <scan_dir> --out <file.vcf>
```

- `<scan_dir>` is the directory `ssba scan --out` wrote (it holds
  `report.json`).
- Prints one line per source (`<label>: <n> contacts`), the total, and — if any —
  the number of unparsed cards and the side file's path.
- Exit 0 if at least one contact was exported. Exit 1, with a one-line
  `error: ...` on stderr, on `ContactExportError` (no `report.json`, no
  `CONTACT` category, no `.vcf` sources, nothing exported).

## Testing

All automated tests use fabricated vCards built in the test code — no real
contact data in the repository.

- `find_contact_sources`: a fake scan dir with a `report.json` listing a Google
  file, a phone-only file, `profile.vcf`, a non-`.vcf` file and an `error`
  entry → returns the three `.vcf` files, profile first. Missing `report.json`,
  missing `CONTACT` category, and an entry whose file is absent on disk each
  behave as specified.
- `parse_cards`, one fabricated card per quirk:
  - `PHOTO;ENCODING=BASE64;PREF;JPEG; :<small base64 JPEG>` → parses, photo
    bytes intact;
  - `BDAY;;:--12-25` → parses, value `--12-25`;
  - quoted-printable UTF-8 `N` containing an accented letter and an emoji →
    decoded exactly;
  - two `GROUP_MEMBER` lines (one repeated) → one `CATEGORIES`, de-duplicated,
    no `GROUP_MEMBER` left;
  - `ORG` + `DEPARTMENT`, and `DEPARTMENT` alone → `ORG` as specified;
  - a card with no `N` but a `TEL` → `FN` equals the number;
  - a card containing a line with no `:` that is not a continuation → lands
    in the unparsed list verbatim, and the cards before and after it still
    parse.
- `export_contacts`: end to end on the fake scan dir → output re-parses with
  `vobject` card by card, every card is `VERSION:3.0` with an `FN`, counts
  match `per_source`; `_unparsed.vcf` exists only when there were failures.
- CLI: success (exit 0, summary printed) and missing `report.json` (exit 1,
  error on stderr).

Manual, local-only validation (never committed): run
`ssba export contacts` on the real scan output and check 798 cards exported,
0 unparsed, the phone-only contacts and the profile present, the emoji name
and the profile photo intact — i.e. the output is a strict superset of what
the spike could read.

## Constraints

- Python 3.10+.
- New runtime dependency: `vobject>=0.9.9` (pulls in `python-dateutil`, `pytz`,
  `six`). No other new dependencies.
- `core/` never prints; only `cli/` does.
- No real personal data in the repository, tests or fixtures.
- No attribution lines in commit messages; commits stay local — nothing is
  pushed until the project owner says so.
