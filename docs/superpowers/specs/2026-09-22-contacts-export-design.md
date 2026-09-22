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
- `parse_cards(text: str) -> tuple[list[str], list[str]]`
  - Splits `text` into cards (`BEGIN:VCARD` ... the first `END:VCARD`, with no
    other `BEGIN:VCARD` in between), and converts each one (rules below) to a
    serialized vCard 3.0 string.
  - Returns (serialized vCard 3.0 cards, raw text of cards that could not be
    converted). Everything that can fail for one card — preparing, parsing,
    normalizing, serializing — runs inside a per-card guard, so a failure
    puts that card's *original* text in the unparsed list and never stops the
    other cards.
  - Text outside the complete cards that contains `BEGIN:VCARD` (a card cut
    off before its `END:VCARD`, at the end of the file or before the next
    card) goes to the unparsed list verbatim, from its `BEGIN:VCARD` on.
- `export_contacts(scan_dir: Path, out_path: Path) -> ContactExportResult`
  - `ContactExportResult`: dataclass `exported: int`,
    `per_source: dict[str, int]` (label → exported count),
    `unparsed: int`, `unparsed_path: Path | None`.
  - Reads each source as raw bytes decoded as UTF-8 (no newline translation,
    so unparsed cards stay byte-for-byte as in the source).
  - Writes all converted cards, in source order, to `out_path` (UTF-8).
  - If any card could not be converted, writes those raw cards, unchanged, to
    `<out_path stem>_unparsed.vcf` next to `out_path`; otherwise deletes such
    a file if an earlier run left one (it would claim cards are missing).
  - Raises `ContactExportError` if no sources are found, zero cards export, a
    source cannot be read, or the output / side file cannot be written
    (e.g. `--out` is a directory, permission denied).
- `ContactExportError(Exception)`.

### Normalization rules (applied to every card, in this order)

(Amended after the final review. The original rule 7 said every other value
was "kept as `vobject` parsed it" — wrong for vCard 2.1 text: `vobject` reads
values with vCard 3.0 rules, where an unescaped `,` separates list items, and
keeps only the first item, so 2.1 text such as `NOTE:hello, world` became
`hello`. That already truncated one NOTE and one X-ANDROID-CUSTOM in the real
export while reporting 0 unparsed. Rule 1 now fixes every 2.1 value *before*
`vobject` sees it.)

1. **Prepare the card for `vobject`** (before parsing).
   - Split the card into lines on CR/LF only (`\r\n`, `\r`, `\n`) —
     not `str.splitlines()`, which also splits on U+2028, U+0085, `\x0b` and
     `\x0c` inside UTF-8 values.
   - **Unfold** each property: a line starting with space/tab continues the
     previous property (the line break and that one space/tab vanish); and a
     quoted-printable property whose line ends in `=` continues on the next
     raw line, which has no leading space (Android's soft line break every
     ~67 characters; the `=` and line break vanish).
   - **Sanitize the header**: drop parameters that are empty or
     whitespace-only (`PHOTO;ENCODING=BASE64;PREF;JPEG; :`, `BDAY;;:`).
   - Leave the value and continuation lines untouched for binary properties
     (`ENCODING=BASE64`/`ENCODING=b`/bare `BASE64`: PHOTO, LOGO, SOUND, KEY)
     and for `BEGIN`, `END`, `VERSION` and `GEO` (values `vobject` does not
     unescape). Every other property is text and gets the next three steps.
   - **Decode** the value to plain text:
     - quoted-printable (`ENCODING=QUOTED-PRINTABLE` or bare
       `QUOTED-PRINTABLE`): decode the bytes with the `CHARSET` parameter
       (default UTF-8). No backslash escapes are interpreted afterwards —
       Android does not escape quoted-printable text.
     - otherwise: backslash escapes `\\`, `\;`, `\,`, `\:` become the
       character (the ones Android's own 2.1 parser unescapes) and `\n`/`\N`
       a newline; any other backslash is a literal character (Android's 2.1
       writer does not escape backslashes).
     - Structured properties are split into components on the separator
       first, then each component is decoded: `N`, `ADR`, `ORG` and
       `X-ANDROID-CUSTOM` on `;` (Android writes X-ANDROID-CUSTOM as
       `<mimetype>;<col 1>;<col 2>;...` and quoted-printable-encodes each
       component on its own, so a literal `;` separates components while an
       encoded `=3B` or an escaped `\;` is part of one); `CATEGORIES` on `,`.
     - `N` may have at most 5 components and `ADR` 7 (the ones `vobject`
       keeps); trailing empty extras are dropped, non-empty extras make the
       card unparsed rather than silently losing them.
   - **Re-encode** as vCard 3.0 text: in each component, `\` → `\\`, `;` →
     `\;`, `,` → `\,`, and a line break (CRLF, CR or LF) → `\n`; rejoin
     components with their separator. Remove `ENCODING=QUOTED-PRINTABLE`,
     bare `QUOTED-PRINTABLE`, `7BIT`/`8BIT` encodings and `CHARSET`.
   - Newlines are the one normalization: vCard 3.0 has only `\n`, so a CRLF
     inside a value comes back as LF. Everything else survives exactly.
2. **Parse** the prepared card with `vobject.readOne`.
3. **`X-ANDROID-CUSTOM`** keeps the prepared vCard 3.0 value as written, so its
   `;` column separators stay unescaped (Android re-imports the columns;
   `vobject` alone would escape them as text).
4. **`GROUP_MEMBER` → `CATEGORIES`.** Collect every `GROUP_MEMBER` value on the
   card (after any existing `CATEGORIES` values), de-duplicated in first-seen
   order, into a single `CATEGORIES` property; remove all `GROUP_MEMBER`
   properties. A group name with a comma stays one category.
5. **`DEPARTMENT` → `ORG`.** Append *every* `DEPARTMENT` value, in order, as
   extra units after the existing components of the first `ORG`; if the card
   has no `ORG`, create one with the departments as its units. Remove
   `DEPARTMENT`.
6. **Synthesize `FN` if missing**, using the first non-empty of:
   `N` (prefix, given, additional, family, suffix joined by single spaces) →
   first `ORG` component → first `EMAIL` → first `TEL` → `"Unknown"`.
7. **Convert vCard 2.1 parameters to 3.0 form, on every property.**
   (Added during planning: prototyping showed `vobject` does *not* do this on
   its own — it re-emits `TEL;CELL;PREF` in 2.1 style and crashes serializing
   a 2.1 `PHOTO;ENCODING=BASE64` photo.)
   - bare 2.1 parameters (`CELL`, `WORK`, `PREF`, `JPEG`, ...) become `TYPE`
     values, in order, without duplicates (`TEL;CELL;PREF` →
     `TEL;TYPE=CELL,PREF`);
   - `ENCODING=BASE64` becomes `ENCODING=b`;
   - `CHARSET` parameters are dropped (vCard 3.0 is UTF-8);
   - on `PHOTO` and `LOGO`, `TYPE` is the image format in vCard 3.0, so it
     keeps only image formats (`JPEG`, `PNG`, `GIF`, `BMP`, `TIFF`, ... — the
     vCard 2.1 list plus `PNG`), dropping `PREF` and Samsung's `SUPREF`; with
     none left, `TYPE` is removed.
8. **Set `VERSION` to `3.0`** (a card without `VERSION` gets `VERSION:3.0`
   from `vobject`) and **serialize** with `vobject` (UTF-8, no
   quoted-printable, photo as base64). Real-data check after the fix: all
   798 cards export, 0 unparsed, and every source value — unfolded and
   quoted-printable-decoded independently — equals the re-parsed exported
   value.

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
  `CONTACT` category, no `.vcf` sources, nothing exported, a file that cannot
  be read or written).

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
    parse;
  - a card `vobject` parses but cannot serialize (two `N`), a truncated card
    at the end and in the middle → unparsed, neighbours still export; a card
    without `VERSION` → exported as 3.0;
  - value fidelity, each asserting the exact decoded value after export and
    re-parse: `NOTE`, `TITLE`, an `X-` property, `ORG` (incl. `Acme, Inc.`),
    `GROUP_MEMBER`, `N` and `X-ANDROID-CUSTOM` with commas and semicolons,
    each plain *and* quoted-printable (incl. Android soft line breaks, a value
    ending exactly on a soft break, emoji, newlines, a non-UTF-8 `CHARSET`),
    Android backslash escapes, and U+2028/U+0085/`\x0b`/`\x0c` inside values;
  - several `DEPARTMENT`s; `PHOTO`/`LOGO` `TYPE` reduced to the image format;
    `FN` fallbacks to `ORG`, `EMAIL` and `"Unknown"`.
- `export_contacts`: end to end on the fake scan dir → output re-parses with
  `vobject` card by card, every card is `VERSION:3.0` with an `FN`, counts
  match `per_source`; `_unparsed.vcf` exists only when there were failures, is
  byte-exact, and a stale one is deleted on a clean run; an unwritable output
  or side file raises `ContactExportError`; every source value of the
  fabricated tricky cards, decoded by an independent reference decoder,
  appears whole in the re-parsed export.
- CLI: success (exit 0, summary printed), missing `report.json` and an
  unwritable `--out` (exit 1, `error: ...` on stderr).

Manual, local-only validation (never committed): run the export on the real
scan output (writing only outside the repository) and check 798 cards
exported, 0 unparsed, the phone-only contacts and the profile present — and,
at the value level, that for every card each source property value
(unfolded and quoted-printable-decoded independently of the exporter) equals
the re-parsed exported value. Counting cards is not enough: the first
validation counted 798 good cards while a NOTE and an X-ANDROID-CUSTOM were
truncated.

## Constraints

- Python 3.10+.
- New runtime dependency: `vobject>=0.9.9` (pulls in `python-dateutil`, `pytz`,
  `six`). No other new dependencies.
- `core/` never prints; only `cli/` does.
- No real personal data in the repository, tests or fixtures.
- No attribution lines in commit messages; commits stay local — nothing is
  pushed until the project owner says so.
