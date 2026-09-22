# SmartSwitch Backup Analyzer

Recover data from a Samsung Smart Switch PC backup — even from a phone you
can no longer use (broken screen, dead device, etc.) — as long as you still
have the backup folder Smart Switch created on your PC.

## What this does (today)

Smart Switch "basic" (no backup password) backups encrypt most of their
content with a per-backup key that isn't published, but *is* fully
recoverable from data already inside the backup. This tool:

1. Recovers that per-backup key from `backupHistoryInfo.xml`.
2. Walks every category folder in the backup (Notes, Contacts, Call log,
   ...) and decrypts every encrypted file it finds, whatever the category —
   without needing to understand what the data means.
3. Writes everything it could decrypt (or that was already plaintext) to an
   output folder you choose, plus a `report.json` summarizing what was
   recovered per category.

Turning that raw decrypted data into something readable per category (e.g.
notes as browsable HTML, contacts as a `.vcf` you can import) is a separate,
ongoing effort — see "Status" below.

## Status

- Generic decryption engine (this repo, Phase 1): done
- Per-category readable exports (Notes, Contacts, Call log planned next): not started
- Graphical interface (planned once the above are in place): not started

## Install

Requires Python 3.10+.

```bash
pip install -e .
```

## Usage

```bash
ssba scan "C:\Users\<you>\Samsung\SmartSwitch\backup\<device>\<backup_folder>" --out ./recovered
```

This writes decrypted category data under `./recovered/<CATEGORY>/...` and a
`./recovered/report.json` summary.

Then turn the recovered contacts into one file you can import on any phone or
contacts service (Google Contacts, iCloud, Outlook, another Android phone):

```bash
ssba export contacts ./recovered --out contacts.vcf
```

It merges every account's contacts found in the backup — including contacts
that were stored only on the phone and never synced anywhere — plus your own
profile card, as vCard 3.0. Any card that can't be read is kept unchanged in
`contacts_unparsed.vcf` instead of being dropped.

**This tool only supports "basic" (no backup password) Smart Switch
backups.** Password/PIN-protected backups are not supported yet.

## Your data, your responsibility

The whole point of this tool is to recover *your own personal data*. Never
commit a real backup, or anything this tool recovers from one, to a public
Git repository. `.gitignore` in this repo already excludes the conventional
`backups/`, `out/`, and `output/` folders — keep your own data outside the
repo entirely if you can.

## License

AGPL-3.0 (see `LICENSE`). If you want to use this project commercially
without the obligations of the AGPL, open a GitHub issue or contact the
maintainer to discuss a commercial license.
