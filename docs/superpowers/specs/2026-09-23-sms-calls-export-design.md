# SMS and Call Log Export (Phase 2, sub-project 2)

Status: approved design, not yet implemented.
Date: 2026-09-23

## Purpose

Turn the text messages and the call log recovered by Phase 1 (`ssba scan`)
into files that any Android phone can restore, without root and without a
Samsung phone.

The research spike that preceded this spec found:

- The only widely used way to restore SMS and calls on a stock Android device
  is the app **SMS Backup & Restore** (SyncTech). Its XML format is documented
  (<https://www.synctech.com.au/sms-backup-restore/fields-in-xml-backup-files/>,
  XSD: `https://synctech.com.au/wp-content/uploads/2018/01/sms.xsd_.txt`).
  Restoring requires making it the default SMS app for the duration of the
  restore; no root. The project owner chose this format.
- Everything else structured in the backup (Wi-Fi, bookmarks, clipboard,
  alarms, blocked numbers) is either view-only or needs its own format; it is
  out of scope here.

## What Phase 1 gives us (verified against the real backup)

Prerequisite, already done: decryption now removes PKCS#7 padding (commit
`97a9728`). Before it, every decrypted file ended in 1-16 stray bytes and
`call_log.exml` was not well-formed XML.

### Messages — `GMMESSAGE` category

The backup has no Samsung `MESSAGE` category: the phone used Google Messages,
whose device-to-device backup lands in `GMMESSAGE/` as

- `d2d_item_info.json` (metadata), and
- `item_instant_<timestamp>_size_<n>_id_<k>` — a **plain SQLite database**
  (the file name varies per backup; recognize it by content).

Relevant tables and columns (Google Messages schema version 440):

| Table | Columns used |
|---|---|
| `messages_backup` | `_id`, `conversation_id`, `sender_participant_id`, `message_status`, `read`, `received_timestamp`, `sent_timestamp`, `protocol` |
| `parts_backup` | `message_id`, `_id`, `text`, `content_type` |
| `participants_backup` | `_id`, `is_self`, `send_destination`, `normalized_destination`, `display_destination`, `full_name` |
| `conversation_participants_backup` | `conversation_id`, `participant_id` |

Real data: 2018 messages in 245 conversations, all one-to-one. 1791 parts,
all `text/plain` except one RCS bot card (`application/vnd.gsma.botmessage.v1.0+json`,
which also carries text). **No media parts** — the backup holds no MMS
attachments. `protocol`: 0 = SMS (1916), 3 = RCS (101), 5 = RCS business (1).

`message_status` (Google Messages "Bugle" status codes):

| Status | Meaning | Real count |
|---|---|---|
| 1-99 | outgoing (1 complete, 2 delivered, 3 draft, 4-7 pending, 8-9 failed, 11 RCS read) | 269 |
| 100-199 | incoming | 1520 |
| ≥ 200 | system/tombstone rows (e.g. "chat started"), no parts, no text | 229 |

Outgoing rows have a self `sender_participant_id`, incoming rows a non-self
one — consistent in all 2018 rows.

### Call log — `CALLLOG` category

`CALLLOG/CALLLOG.zip/call_log.exml` is plain XML:

```xml
<CallLogs><CallLog><name>…</name><date>ms</date><duration>s</duration>
<number>…</number><presentation>1</presentation><type>1</type>
<is_read/><new/><logtype>1000</logtype><sec_icc_id/>
<subscription_component_name/><subscription_id>3</subscription_id>
<data1/>…<sim_id>0</sim_id></CallLog>…</CallLogs>
```

Real data: 2000 calls (07/2025-07/2026). `type`: 1 incoming (541),
2 outgoing (1064), 3 missed (348), 5 rejected (46), 6 blocked (1) — the same
codes Android and SMS Backup & Restore use. `logtype` 100 and 1000 are both
ordinary phone calls; both are exported. No XML-invalid control characters
in either source.

## Scope

In:
- `ssba export messages`: every SMS/RCS text message → one SMS Backup &
  Restore `sms-*.xml`-style file of `<sms>` elements.
- `ssba export calls`: every call → one `calls-*.xml`-style file of `<call>`
  elements.
- A shared helper that reads `report.json` for any category (extracted from
  the contacts exporter, which then uses it).
- Never drop data silently: rows that cannot be converted go, with their
  source values, to a side file and are counted.

Out (non-goals):
- MMS and group conversations (none in the real data). Messages whose
  conversation does not have exactly one other participant are counted as
  unsupported and written to the side file.
- RCS-specific data (reactions, read reports, replies, link previews): RCS
  messages are exported as plain SMS with their text.
- The SMS Import/Export (F-Droid) format.
- Blocked numbers, Wi-Fi, bookmarks and the other structured categories.
- Test-restoring on a real device: compatibility is checked offline against
  the published XSD and sample; the device test is the project owner's.

## Architecture

```
src/ssba/core/parsers/
├── scan_report.py   # NEW: read report.json, list a category's files safely
├── contact.py       # uses scan_report
├── messages.py      # NEW: Google Messages SQLite -> SMS Backup & Restore XML
└── calls.py         # NEW: Samsung call_log.exml -> SMS Backup & Restore XML
src/ssba/cli/main.py # new subcommands: ssba export messages | calls
```

`core/` never prints and only writes to paths its caller passes in.

### `ssba.core.parsers.scan_report`

- `ScanReportError(Exception)`.
- `category_files(scan_dir: Path, category: str) -> list[Path]`
  - Reads `scan_dir / "report.json"`; missing, unreadable, non-UTF-8,
    invalid JSON or wrong shape → `ScanReportError` (same messages the
    contacts exporter uses today: `report.json not found in …`,
    `report.json is not readable: …`).
  - No category named exactly `category` → `ScanReportError("the scan report
    has no <category> category")`.
  - Returns, in report order, `scan_dir / category / <path>` for every entry
    that is a dict with a non-empty string `path`, whose `status` is
    `"decrypted"` or `"plaintext_passthrough"`, whose resolved path stays
    inside `scan_dir / category`, and which is a file on disk. Anything else
    is skipped.
- `find_contact_sources` keeps its behaviour and messages; it calls
  `category_files(scan_dir, "CONTACT")`, filters `.vcf`, and re-raises
  `ScanReportError` as `ContactExportError`.

### Shared XML rules (messages and calls)

- Characters XML 1.0 forbids (U+0000-U+0008, U+000B, U+000C,
  U+000E-U+001F, U+FFFE, U+FFFF, lone surrogates) are replaced with U+FFFD
  and counted in the result.
- Written with `xml.etree.ElementTree`, UTF-8, with the XML declaration;
  attribute values escape `& < > "` and newlines/tabs/CRs as character
  references, so multi-line bodies round-trip exactly.
- Elements are ordered by `date`, then by source order.
- Side file for rows that cannot be converted: `<out stem>_unsupported.json`
  next to the output — a JSON list of objects holding the row's source
  values and a `reason`. Written only when there is at least one such row;
  otherwise a stale one from an earlier run is deleted.
- Output or side file that cannot be written → the module's export error.

### `ssba.core.parsers.messages`

- `MessageExportError(Exception)`.
- `MessageExportResult`: dataclass `exported: int`, `rcs_as_sms: int`,
  `system_skipped: int`, `unsupported: int`, `unsupported_path: Path | None`,
  `replaced_chars: int`.
- `export_messages(scan_dir: Path, out_path: Path) -> MessageExportResult`
  - Sources: `category_files(scan_dir, "GMMESSAGE")` whose first 16 bytes are
    `SQLite format 3\0`. None → `MessageExportError`. Each is opened
    read-only (`sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)`); a
    database missing one of the four tables above → `MessageExportError`
    naming the file. Several sources are exported into the same file.
  - Per message (`messages_backup` row):
    - `message_status >= 200` → skipped, counted in `system_skipped`.
    - `body`: the non-null `text` of its parts ordered by part `_id`, joined
      with `"\n"`. No text at all → unsupported (`reason: "no text"`).
    - `type`: status 3 → 3 (draft); 8 or 9 → 5 (failed); other 1-99 → 2
      (sent); 100-199 → 1 (received); ≤ 0 → unsupported.
    - `address`: for received messages, the sender participant; for the
      others, the conversation's participants that are not self — exactly
      one is required, otherwise unsupported (`reason: "group or no
      recipient"`). Value: first non-empty of `send_destination`,
      `normalized_destination`, `display_destination`; none → unsupported.
    - `date`: `received_timestamp`, or `sent_timestamp` if that is 0/NULL;
      both missing → unsupported. `date_sent`: `sent_timestamp` when > 0,
      else omitted.
    - `read`: 1 if the `read` column is truthy, else 0.
    - `contact_name`: that participant's `full_name` when non-empty, else
      omitted.
    - Fixed: `protocol="0"`, `status="-1"`, `locked="0"`.
    - `protocol` ≠ 0 in the source (RCS) → counted in `rcs_as_sms`.
  - Root: `<smses count="<exported>">`.
  - `exported == 0` → `MessageExportError`.

### `ssba.core.parsers.calls`

- `CallExportError(Exception)`.
- `CallExportResult`: dataclass `exported: int`, `unknown_types: int`,
  `unsupported: int`, `unsupported_path: Path | None`, `replaced_chars: int`.
- `export_calls(scan_dir: Path, out_path: Path) -> CallExportResult`
  - Sources: `category_files(scan_dir, "CALLLOG")` ending in `.exml`
    (case-insensitive). None → `CallExportError`. Not well-formed XML, or a
    root other than `CallLogs` → `CallExportError` naming the file.
  - Per `<CallLog>`:
    - `number`: text of `number` (may be empty — private numbers).
    - `date`, `duration`, `type`: must be integers, otherwise unsupported
      (`reason` names the field). `duration` missing → 0.
    - `presentation`: its integer value, default 1.
    - `contact_name`: text of `name` when non-empty, else omitted.
    - `type` outside 1-7 is kept as is and counted in `unknown_types`.
    - Not exported: `subscription_id`, `sim_id`, `sec_icc_id` (they identify
      SIM slots of the old phone and would mislabel calls on a new one),
      `logtype`, `is_read`, `new`, `data1`-`data4`.
  - Root: `<calls count="<exported>">`.
  - `exported == 0` → `CallExportError`.

## CLI

```
ssba export messages <scan_dir> --out <sms.xml>
ssba export calls    <scan_dir> --out <calls.xml>
```

- Messages prints `<n> messages written to <out>`, then — when non-zero —
  `<n> RCS messages converted to SMS`, `<n> system messages skipped`,
  `<n> messages could not be converted; kept in <side file>`,
  `<n> invalid characters replaced`.
- Calls prints `<n> calls written to <out>`, then — when non-zero — unknown
  types, unsupported (with the side file) and replaced characters.
- Exit 0 on success; exit 1 with a one-line `error: …` on stderr on the
  module's export error.

## Testing

All automated tests use fabricated data built in the test code — a SQLite
database created with a reduced copy of the real schema, and a hand-written
`call_log.exml`. No real messages, numbers or names in the repository.

- `scan_report`: missing/invalid `report.json`, missing category, skipped
  entries (bad status, non-string path, path traversal, missing file), order
  kept. Contact tests stay green unchanged.
- `messages`: incoming and outgoing SMS; RCS counted; status 3/8/9/≥200/≤0;
  multi-part body; message without parts; group conversation and missing
  address → side file with reason; `date` fallback and omitted `date_sent`;
  `contact_name` present/omitted; body with `& < > "`, newlines, tab, CR,
  emoji and a control character (replaced and counted) round-trips exactly
  after re-parsing the output; missing table and no SQLite source → error;
  several sources merged; stale side file deleted; unwritable output → error.
  The output validates against the attribute rules of the published XSD
  (required attributes present, integer types).
- `calls`: each type; private number; missing name; non-integer date → side
  file; unknown type kept and counted; malformed XML and wrong root → error;
  ordering by date; SIM fields not exported.
- CLI: success output and exit 0; missing `report.json` and unwritable
  `--out` → exit 1 with `error:`.

Manual, local-only validation (never committed; outputs under the
git-ignored `out/`): export from the real scan and check that
- both files re-parse as XML and `count` equals the number of elements;
- messages: exported + system_skipped + unsupported = 2018, and every
  source part text appears whole in the matching `body`;
- calls: 2000 exported, every source number/date/duration/type equal.

## Constraints

- Python 3.10+. No new dependencies (`sqlite3`, `xml.etree` are stdlib).
- `core/` never prints; only `cli/` does.
- No real personal data in the repository, tests or fixtures.
- No attribution lines in commit messages; commits stay local — nothing is
  pushed until the project owner says so.
