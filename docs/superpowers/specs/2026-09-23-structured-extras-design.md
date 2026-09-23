# Structured Extras Export (Phase 2, sub-project 2, part 2)

Status: implemented.
Date: 2026-09-23

## Purpose

Finish sub-project 2 ("SMS, calls and other structured data"): export the
remaining structured data the research spike found — Wi-Fi networks, blocked
numbers, Samsung Internet bookmarks and history, the keyboard clipboard, and
alarms/timers/world clock — and add one command that runs every exporter.

The project owner chose all four groups, one `ssba export <kind>` command per
kind (like `contacts`, `messages`, `calls`), and also one command that runs
them all.

What can be restored on a stock Android phone (from the spike):

| Data | Restorable? | Output |
|---|---|---|
| Wi-Fi | No bulk import without root on Android 10+; each network can be added by scanning a `WIFI:` QR code in Settings → Wi-Fi | page with passwords and one QR code per network |
| Blocked numbers | Re-entered by hand | plain text list |
| Bookmarks | Chrome/Firefox import the Netscape bookmark file format | `bookmarks.html` |
| History, downloads, clipboard, clock | Not restorable | read-only pages |

## What Phase 1 gives us (verified against the real backup)

### Wi-Fi — `WIFICONFIG`

`WIFICONFIG.zip/WifiConfigStore.xml` is **not XML**. It holds two parts:

1. `Old_Version_Style` followed by `wpa_supplicant`-style blocks:
   ```
   network={
   	ssid="<name>"
   	scan_ssid=1          (hidden network; optional)
   	psk="<password>"     (optional)
   	key_mgmt=WPA-PSK     (SAE, WPA-PSK, NONE or OWE)
   }
   ```
   81 blocks for 40 networks: a WPA2/WPA3 network appears twice (`SAE` and
   `WPA-PSK`, same `psk`), an open one twice (`NONE` and `OWE`).
2. `New_Version_Style` followed by Android's `WifiBackupData` XML — 37
   networks, all also present in part 1 with the same passwords.

`wpa_supplicant.conf` in the same folder is a copy of part 1. Real data:
40 networks, 30 with a password, 2 hidden (3 hidden blocks), no WEP or EAP,
no hex SSIDs.

### Blocked numbers — `CALLOGSETTING`

`CALLOGSETTING.zip/com.samsung.android.app.telephonyui.callsettings.api.entity.BlockNumberItem.csv`,
tab-separated with a header:

```
_id	reject_number	reject_match
4	<number or text>	0
…
```

Real data: 5 rows, all `reject_match` 0 (exact match). The meaning of other
`reject_match` values is not verified. `PhotoRingBlockNumberItem.csv` is a
different list and is not exported.

### Samsung Internet — `SBROWSER`

`SBROWSER.zip/backup.enc` is a plain **ZIP** (not encrypted) holding the app's
data directory. Used members:

- `databases/SBrowser.db`, table `BOOKMARKS`: `_ID`, `URL`, `TITLE`,
  `FOLDER` (1 = folder), `PARENT` (`_ID` of the parent folder), `POSITION`,
  `DELETED`. Real data: 2 folders, 3 bookmarks, nested
  (`_ID -3` → `_ID 0` → bookmarks), `CREATED` always 0.
- `databases/quickaccess.db`, table `quickaccess_item`: `title`, `url`,
  `position`, `deleted`. Real data: 10 items.
- `app_sbrowser/Default/History` (Chromium schema): `urls` (`url`, `title`,
  `visit_count`, `last_visit_time`), `downloads` (`id`, `target_path`,
  `start_time`, `total_bytes`, `state`), `downloads_url_chains` (`id`,
  `chain_index`, `url`). Times are Chromium times: microseconds since
  1601-01-01 UTC. Real data: 696 URLs, 440 downloads.

### Clipboard — `CLIPBOARD`

`CLIPBOARD.zip/clipboard_backup_keyboard.zip` is a ZIP holding:

- `BackupClipItem.db`, table `clip_table`: `time_stamp` (ms since epoch),
  `type` (1 text, 2 image, 4 HTML), `text`, `html`. Real data: 34 text,
  8 image, 14 HTML rows.
- `clipboard/<time_stamp ms>/clip`: one image per folder (JPEG in the real
  data). 687 folders; only 8 match a `clip_table` row — the other 679 images
  outlived their rows but are real clipboard content.

### Clock — `ALARM`, `WORLDCLOCK`

- `ALARM.zip/alarm.exml`: `<Alarms>` with `<alarm>` elements: `alarmtime`
  (`HHMM` as an integer, e.g. `530` = 05:30), `active` (1/0), `name`,
  `repeattype` (Samsung bit field, **not decoded** — shown raw). 1 alarm.
- `WORLDCLOCK.zip/timer.exml`: `<Timer><timerlife><item>` with `timername`
  and `time` (`HH:MM:SS`). 3 timers.
- `WORLDCLOCK.zip/worldclock.exml`: `<Worldclocks><worldclock><item>` with
  `city` and `gmt`. 2 cities.

## Scope

In: the five exporters below, `ssba export all`, a shared HTML page helper,
and a `MissingCategoryError` subclass so callers can tell "category absent"
from "report broken".

Out (non-goals):
- Decoding Samsung's alarm `repeattype`.
- `reject_match` meanings other than 0; `PhotoRingBlockNumberItem.csv`.
- WEP/EAP Wi-Fi QR codes (listed without a QR code; none in the real data).
- Open tabs, saved passwords, cookies and other Samsung Internet files.
- Importing anything into a phone or a browser automatically.

## Architecture

```
src/ssba/core/parsers/
├── scan_report.py   # + MissingCategoryError(ScanReportError)
├── html_page.py     # NEW: page(), esc(), format_time()
├── wifi.py          # NEW
├── blocked.py       # NEW
├── browser.py       # NEW
├── clipboard.py     # NEW
└── clock.py         # NEW
src/ssba/cli/main.py # export wifi | blocked-numbers | browser | clipboard | clock | all
```

`core/` never prints and only writes where its caller says. Every HTML page
is a single self-contained UTF-8 file: inline CSS, no scripts, no external
resources, so it works offline and nothing in the backup can run code.

### `scan_report`

- `MissingCategoryError(ScanReportError)`: raised by `category_files` when
  the category is absent (same message as today). Existing callers keep
  working (it is a `ScanReportError`).
- `category_zip(scan_dir, category, member) -> Path | None`: the first file
  of `category_files(scan_dir, category)` that is a ZIP containing `member`
  (unreadable or non-ZIP files are passed over). Used by `browser` and
  `clipboard`.

### `html_page`

- `esc(text: str) -> str` — `html.escape(text, quote=True)`.
- `page(title: str, body: str) -> str` — a complete HTML5 document
  (`<!DOCTYPE html>`, `<meta charset="utf-8">`, escaped `<title>`, a small
  inline `<style>`, `<h1>` with the escaped title, then `body` as given).
- `format_time(seconds: float | None) -> str` — local time
  `YYYY-MM-DD HH:MM:SS`; `None` or ≤ 0 → `""`.
- `safe_link(url: str, text: str) -> str` — an `<a href>` only for
  `http://` and `https://` URLs (case-insensitive), otherwise the escaped
  text alone. Both escaped.
- `write_output(path, text, error)` — creates the parent directory and
  writes UTF-8 text; any `OSError` is raised as
  `error("cannot write <path>: <reason>")`. Used by every new exporter.

### `wifi` — `ssba export wifi <scan_dir> --out <wifi.html>`

- `WifiNetwork` dataclass: `ssid: str`, `security: str` (`"WPA"`,
  `"WPA-nopass"`, `"open"` or `"other"`), `password: str | None`,
  `hidden: bool`.
- `read_networks(scan_dir) -> tuple[list[WifiNetwork], int]` — networks and
  the number of blocks skipped:
  - Sources: `category_files(scan_dir, "WIFICONFIG")` whose text contains
    `network={`, read as UTF-8 (`errors="replace"`). Only the text before
    `New_Version_Style` (if present) is parsed.
  - A block is the lines between `network={` and the next line that is
    exactly `}`; each line `key=value` (whitespace-stripped).
  - Values: `"…"` → the text between the quotes. An unquoted `ssid` is
    hex-encoded bytes → decoded as UTF-8 (`errors="replace"`) when it is
    valid even-length hex, else kept as written. An unquoted `psk` is a raw
    64-hex-digit key → kept as written (Android accepts it as the password).
  - A block still open at the end of the text is kept (truncated file).
  - A block without `ssid` → skipped (counted).
  - Blocks are grouped by SSID in first-seen order. `password` = first
    non-empty `psk`. `hidden` = any block has `scan_ssid=1`.
    `security`: `"other"` if any block has `key_mgmt` containing `EAP` or a
    key starting with `wep_key` (any index, not only `wep_key0`); else
    `"WPA"` if there is a password; else `"WPA-nopass"` if any block's
    `key_mgmt` (upper-cased, space-split) contains `WPA-PSK`, `SAE`,
    `WPA-PSK-SHA256` or `FT-PSK` — the network is protected but the
    password was not recovered; else `"open"`.
- `qr_payload(network) -> str | None` (ZXing `WIFI:` format; `None` for
  `"other"` and for `"WPA-nopass"` — a `nopass` QR would create a useless
  open network profile). Special characters `\ ; , : "` in SSID and
  password are escaped with a backslash:
  - WPA: `WIFI:T:WPA;S:<ssid>;P:<password>;` + `H:true;` if hidden + `;`
  - open: `WIFI:T:nopass;S:<ssid>;` + `H:true;` if hidden + `;`
- `export_wifi(scan_dir, out_path) -> WifiExportResult` (`networks`,
  `with_password`, `skipped`). Page: one table row per network — SSID,
  security (`WPA/WPA2/WPA3`, `WPA (password not in backup)`, `Open`,
  `Other (EAP/WEP)`), password (or `—`), hidden (`yes`/`no`), QR code as
  inline SVG (`segno.make(payload, error="m",
  micro=False).svg_inline(scale=4)`) or `—`. A note at the top says the
  page contains passwords.
- `WifiExportError`: category/report errors, no network found, write
  failure (`cannot write …`).

### `blocked` — `ssba export blocked-numbers <scan_dir> --out <file.txt>`

- Source: `category_files(scan_dir, "CALLOGSETTING")` whose name ends with
  `.BlockNumberItem.csv` and is not `…PhotoRingBlockNumberItem.csv`. Parsed
  with `csv.DictReader(delimiter="\t")` from UTF-8 text.
- Rows ordered by `_id` as an integer (non-integer `_id` last, file order).
  A row with an empty `reject_number` → skipped (counted).
- Output: one line per number; if `reject_match` is not `0`, the line is
  `<number>\t(match type <value>)`.
- `export_blocked_numbers(scan_dir, out_path) -> BlockedExportResult`
  (`exported`, `skipped`). `BlockedExportError` when no source, zero rows
  exported, or write failure.

### `browser` — `ssba export browser <scan_dir> --out <dir>`

- Source: the first `category_files(scan_dir, "SBROWSER")` entry that is a
  ZIP (`zipfile.is_zipfile`) containing `databases/SBrowser.db`. None →
  `BrowserExportError`. Members are extracted to a temporary directory and
  opened read-only; missing `quickaccess.db` or `History` → that section is
  empty, not an error.
- `bookmarks.html` (Netscape format, importable):
  ```
  <!DOCTYPE NETSCAPE-Bookmark-file-1>
  <META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
  <TITLE>Bookmarks</TITLE>
  <H1>Bookmarks</H1>
  <DL><p>
      <DT><H3>folder title</H3>
      <DL><p>
          <DT><A HREF="url">title</A>
      </DL><p>
  </DL><p>
  ```
  - Rows with `DELETED` = 1 are ignored. Folders: `FOLDER` = 1. Tree by
    `PARENT`; a row whose `PARENT` is not a (non-deleted) folder's `_ID` is
    top level. Siblings ordered by `POSITION`, then `_ID`. A bookmark with an
    empty `URL` → skipped (counted). Empty title → the URL (bookmark) or
    `Untitled folder`.
  - Quick access items (`deleted` = 0, ordered by `position`) go in a
    top-level folder `Quick access`, after the tree; empty `url` → skipped.
  - Titles and URLs are escaped with a bookmark-file-specific escaper, not
    `esc`: Chrome's bookmark importer decodes only `&lt; &gt; &amp; &quot;
    &#39;` and reads the file line by line, so `\r`/`\n` are first turned
    into a space, then `html.escape(text, quote=False)`, then `"` →
    `&quot;` and `'` → `&#39;` (not `&#x27;`).
- `history.html` (read-only): "Visited sites" table (last visit, title,
  `safe_link(url)`, visit count), ordered by last visit, newest first; and
  "Downloads" table (start time, file = `target_path`, source URL = the
  chain URL with the highest `chain_index`, size in bytes), newest first.
  Chromium time `t` → Unix seconds `t / 1e6 - 11644473600`; `t` ≤ 0 → `""`.
- `export_browser(scan_dir, out_dir) -> BrowserExportResult`
  (`bookmarks`, `folders`, `quick_access`, `history`, `downloads`,
  `skipped`). Write failure → `BrowserExportError("cannot write …")`.

### `clipboard` — `ssba export clipboard <scan_dir> --out <dir>`

- Source: `category_files(scan_dir, "CLIPBOARD")` entry that is a ZIP
  containing `BackupClipItem.db` (none → `ClipboardExportError`).
- Entries:
  - each `clip_table` row of type 1 or 4: its `text`, or — when `text` is
    empty — its `html` shown as escaped source;
  - each file member under `clipboard/<folder>/`: an image, dated by
    `<folder>` when it is an integer of milliseconds, else undated.
  - A type-2 row whose `clipboard/<time_stamp>/` folder has no member →
    listed as "image missing" and counted in `missing_images`.
  - Rows of any other type → listed with their type and text, counted in
    `other_types`.
- Images are written to `<out>/images/<YYYY-MM-DD_HH-MM-SS>.<ext>` (local
  time of the folder's ms; `_2`, `_3`… on collision; undated → `clip-<n>`).
  `<ext>` from content: JPEG `jpg`, PNG `png`, GIF `gif`, WebP `webp`,
  otherwise `bin`.
- `<out>/index.html`: all entries in time order (undated last), each with
  its date and either the escaped text in a `<pre>` or an `<img>` with a
  relative `src` to the written file (bin files as a link).
- `export_clipboard(scan_dir, out_dir) -> ClipboardExportResult` (`texts`,
  `images`, `missing_images`, `other_types`). Write failure →
  `ClipboardExportError`.

### `clock` — `ssba export clock <scan_dir> --out <clock.html>`

- Sources (each optional): `category_files(scan_dir, "ALARM")` named
  `alarm.exml`; `category_files(scan_dir, "WORLDCLOCK")` named `timer.exml`
  and `worldclock.exml`. `MissingCategoryError` → that source is absent;
  other `ScanReportError` → `ClockExportError`. No source at all →
  `ClockExportError`. A file that is not well-formed XML → `ClockExportError`
  naming it.
- Alarms: time from `alarmtime` (`HHMM` integer → `HH:MM`; invalid → the raw
  text), `active` (`1` → `on`, else `off`), `name`, `repeattype` raw.
- Timers: `timername` (empty → `Timer <n>`), `time`.
- World clock: `city`, `gmt`.
- `export_clock(scan_dir, out_path) -> ClockExportResult` (`alarms`,
  `timers`, `cities`). Write failure → `ClockExportError`.

## CLI

- `ssba export wifi|blocked-numbers|clock <scan_dir> --out <file>` and
  `ssba export browser|clipboard <scan_dir> --out <dir>`: print what was
  written (counts, and skipped/missing counts when non-zero); exit 0; on the
  module's error `error: …` on stderr, exit 1. `wifi` also prints
  `warning: <out> contains Wi-Fi passwords in clear text` on stderr.
- The nine `export` subparsers (the three existing ones included) are
  declared through one small helper instead of repeating the
  `scan_dir`/`--out` pair.
- `ssba export all <scan_dir> --out <dir>`:
  - Missing `<scan_dir>/report.json` → `error: report.json not found in …`,
    exit 1, nothing run.
  - Runs, in order, each kind's existing CLI runner with fixed targets:
    `contacts.vcf`, `sms.xml`, `calls.xml`, `wifi.html`,
    `blocked-numbers.txt`, `browser/`, `clipboard/`, `clock.html`, printing
    `== <kind> ==` before each. A failing kind prints its usual `error: …`
    and the run continues. Each kind also runs inside a
    `try/except Exception`: an unexpected exception from a runner (a bug,
    not a module's own export error) prints
    `error: <kind> failed unexpectedly: <exc>` on stderr, counts as not
    written, and the remaining kinds still run — one exporter's crash must
    never stop `export all`.
  - Ends with `<n> of 8 exports written to <dir>`; exit 0 if at least one
    succeeded, else 1.

## Testing

Fabricated data only. Per module:
- `html_page`: escaping, `safe_link` for http/https/`javascript:`/mixed
  case, `format_time` edge cases, `page` escapes the title.
- `wifi`: grouping of SAE/WPA-PSK and NONE/OWE duplicates; hidden; hex
  SSID; missing ssid skipped; EAP → other without QR; `New_Version_Style`
  part ignored; payload escaping of `\ ; , : "`; page contains one SVG per
  QR-able network and escapes `<script>` in an SSID; errors.
- `blocked`: order by `_id`, match type suffix, empty number skipped,
  PhotoRing file ignored, errors.
- `browser`: nested folders and ordering, deleted rows ignored, top-level
  fallback, empty URL skipped, quick-access folder, escaping of titles/URLs
  with `"` and `<`, the bookmark file re-parses with `html.parser` into the
  expected tree; history ordering, Chromium time conversion, `javascript:`
  URL not linked, download source URL from the highest `chain_index`;
  missing History/quickaccess tolerated; errors.
- `clipboard`: text/HTML/image rows, orphan images, missing image, name
  collisions, extension sniffing, escaping of `<script>` text, relative
  `src`; errors.
- `clock`: each source alone and together, `HHMM` formatting, invalid
  values, malformed XML, no source.
- CLI: each subcommand success and error; `export all` on a scan dir that
  has only some categories (partial success, exit 0), with no report
  (exit 1), and with nothing exportable (exit 1).

Manual, local-only validation on the real scan (outputs under the
git-ignored `out/`): 40 networks (30 with password, 2 hidden) and each QR
payload re-derived from the source; 5 blocked numbers; 3 bookmarks in 2
folders + 10 quick access; 696 history rows, 440 downloads; 48 text/HTML
entries and 8 image rows + 687 images written and byte-identical to the ZIP
members; 1 alarm, 3 timers, 2 cities; `export all` → 8 of 8.

## Constraints

- Python 3.10+. New runtime dependency: `segno>=1.6` (pure Python, no
  dependencies), used only to draw QR codes; the QR payload is built by this
  project (segno's `make_wifi_data` mis-escapes some characters).
- `core/` never prints; only `cli/` does.
- No real personal data in the repository, tests or fixtures.
- No attribution lines in commit messages; commits stay local — nothing is
  pushed until the project owner says so. Work directly on `master`.
