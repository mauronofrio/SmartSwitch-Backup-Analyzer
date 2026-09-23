"""Command-line entry point for the Smart Switch backup analyzer."""

from __future__ import annotations

import argparse
import functools
import sys
from pathlib import Path

from ssba.core.discovery import default_roots, find_backups, format_size
from ssba.core.errors import UnsupportedBackupError
from ssba.core.parsers.apps import AppsExportError, export_apps
from ssba.core.parsers.blocked import BlockedExportError, export_blocked_numbers
from ssba.core.parsers.browser import BrowserExportError, export_browser
from ssba.core.parsers.calls import CallExportError, export_calls
from ssba.core.parsers.clipboard import ClipboardExportError, export_clipboard
from ssba.core.parsers.clock import ClockExportError, export_clock
from ssba.core.parsers.contact import ContactExportError, export_contacts
from ssba.core.parsers.files import (
    ORIGINALS_FOLDER,
    FilesExportError,
    check_out_dir,
    export_files,
    found_categories,
)
from ssba.core.parsers.messages import MessageExportError, export_messages
from ssba.core.parsers.notes import NotesExportError, export_notes
from ssba.core.parsers.wifi import WifiExportError, export_wifi
from ssba.core.recovery import EXPORTS
from ssba.core.scanner import scan_backup, write_report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ssba",
        description="Recover data from a Samsung Smart Switch PC backup.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser(
        "scan", help="decrypt every category of a Smart Switch backup"
    )
    scan_parser.add_argument(
        "backup_root",
        type=Path,
        help="path to the backup folder (contains backupHistoryInfo.xml)",
    )
    scan_parser.add_argument(
        "--out", type=Path, required=True, help="output directory for decrypted data"
    )
    scan_parser.add_argument(
        "--category",
        dest="categories",
        action="append",
        default=None,
        metavar="NAME",
        help="only scan this category (repeatable); defaults to every category found",
    )

    backups_parser = subparsers.add_parser(
        "backups", help="list the Smart Switch backups found on this PC"
    )
    backups_parser.add_argument(
        "--root",
        dest="roots",
        action="append",
        type=Path,
        default=None,
        metavar="FOLDER",
        help="folder to search (repeatable); defaults to Smart Switch's backup folders",
    )

    export_parser = subparsers.add_parser(
        "export", help="turn `ssba scan` output into files you can import elsewhere"
    )
    export_kinds = export_parser.add_subparsers(dest="export_kind", required=True)
    exports = (
        ("contacts", "merge the recovered contacts into one vCard 3.0 file", "the .vcf file to write"),
        ("messages", "write the recovered text messages as SMS Backup & Restore XML", "the .xml file to write"),
        ("calls", "write the recovered call log as SMS Backup & Restore XML", "the .xml file to write"),
        ("wifi", "list the saved Wi-Fi networks with passwords and QR codes", "the .html file to write"),
        ("blocked-numbers", "list the blocked phone numbers", "the .txt file to write"),
        ("browser", "export Samsung Internet bookmarks and history", "the directory to write"),
        ("clipboard", "export the keyboard clipboard texts and images", "the directory to write"),
        ("clock", "list alarms, timers and world clock cities", "the .html file to write"),
        ("notes", "export Samsung Notes as text files and attachments in folders", "the directory to write"),
        ("apps", "list the installed apps with Play Store links", "the .html file to write"),
        ("files", "merge photos, videos, music and documents into one Android folder tree", "the directory to write"),
        ("all", "run every export above into one directory", "the directory to write"),
    )
    kind_parsers = {}
    for name, help_text, out_help in exports:
        kind_parser = export_kinds.add_parser(name, help=help_text)
        kind_parser.add_argument(
            "scan_dir", type=Path, help="directory written by `ssba scan --out`"
        )
        kind_parser.add_argument("--out", type=Path, required=True, help=out_help)
        kind_parsers[name] = kind_parser
    kind_parsers["files"].add_argument(
        "--mode",
        choices=("none", "copy", "move"),
        required=True,
        help="move or copy the files into one Android tree, or leave them in their category folders",
    )
    kind_parsers["all"].add_argument(
        "--files",
        choices=("none", "copy", "move"),
        default="none",
        help="what `export files` does inside --out (default: none)",
    )

    return parser


def _run_export_contacts(scan_dir: Path, out: Path) -> int:
    try:
        result = export_contacts(scan_dir, out)
    except ContactExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for label, count in result.per_source.items():
        print(f"{label}: {count} contacts")
    print(f"\n{result.exported} contacts written to {out}")
    if result.unparsed:
        print(
            f"{result.unparsed} contacts could not be parsed; "
            f"kept unchanged in {result.unparsed_path}"
        )
    return 0


def _run_export_messages(scan_dir: Path, out: Path) -> int:
    try:
        result = export_messages(scan_dir, out)
    except MessageExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{result.exported} messages written to {out}")
    if result.rcs_as_sms:
        print(f"{result.rcs_as_sms} RCS messages converted to SMS")
    if result.system_skipped:
        print(f"{result.system_skipped} system messages skipped")
    if result.unsupported:
        print(
            f"{result.unsupported} messages could not be converted; "
            f"kept in {result.unsupported_path}"
        )
    if result.replaced_chars:
        print(f"{result.replaced_chars} invalid characters replaced")
    return 0


def _run_export_calls(scan_dir: Path, out: Path) -> int:
    try:
        result = export_calls(scan_dir, out)
    except CallExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{result.exported} calls written to {out}")
    if result.unknown_types:
        print(f"{result.unknown_types} calls have an unknown type (kept as is)")
    if result.unsupported:
        print(
            f"{result.unsupported} calls could not be converted; "
            f"kept in {result.unsupported_path}"
        )
    if result.replaced_chars:
        print(f"{result.replaced_chars} invalid characters replaced")
    return 0


def _run_export_wifi(scan_dir: Path, out: Path) -> int:
    try:
        result = export_wifi(scan_dir, out)
    except WifiExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"{result.networks} Wi-Fi networks written to {out} "
        f"({result.with_password} with a password)"
    )
    if result.skipped:
        print(f"{result.skipped} network entries without a name skipped")
    print(f"warning: {out} contains Wi-Fi passwords in clear text", file=sys.stderr)
    return 0


def _run_export_blocked_numbers(scan_dir: Path, out: Path) -> int:
    try:
        result = export_blocked_numbers(scan_dir, out)
    except BlockedExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{result.exported} blocked numbers written to {out}")
    if result.skipped:
        print(f"{result.skipped} rows without a number skipped")
    return 0


def _run_export_browser(scan_dir: Path, out: Path) -> int:
    try:
        result = export_browser(scan_dir, out)
    except BrowserExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"{result.bookmarks} bookmarks in {result.folders} folders and "
        f"{result.quick_access} quick access items written to {out / 'bookmarks.html'}"
    )
    print(
        f"{result.history} visited sites and {result.downloads} downloads "
        f"written to {out / 'history.html'}"
    )
    if result.skipped:
        print(f"{result.skipped} entries without an address skipped")
    return 0


def _run_export_clipboard(scan_dir: Path, out: Path) -> int:
    try:
        result = export_clipboard(scan_dir, out)
    except ClipboardExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{result.texts} texts and {result.images} images written to {out / 'index.html'}")
    if result.missing_images:
        print(f"{result.missing_images} clipboard images were missing from the backup")
    if result.other_types:
        print(f"{result.other_types} entries of an unknown type included as text")
    return 0


def _run_export_clock(scan_dir: Path, out: Path) -> int:
    try:
        result = export_clock(scan_dir, out)
    except ClockExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"{result.alarms} alarms, {result.timers} timers and "
        f"{result.cities} world clock cities written to {out}"
    )
    return 0


def _run_export_notes(scan_dir: Path, out: Path) -> int:
    try:
        result = export_notes(scan_dir, out)
    except NotesExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"{result.notes} notes written to {out} "
        f"({result.text_notes} with text, {result.attachments} attachments)"
    )
    if result.trashed:
        print(f"{result.trashed} notes from the trash in {out / 'Trash'}")
    if result.preview_only:
        print(f"{result.preview_only} notes only had a text preview (it may be cut short)")
    if result.handwriting_only:
        print(
            f"{result.handwriting_only} notes contain only handwriting or drawings, "
            "which cannot be exported"
        )
    if result.with_drawings:
        print(f"{result.with_drawings} notes had handwriting or drawings that are not exported")
    if result.missing_files:
        print(
            f"{result.missing_files} notes had no file in the backup "
            "(title and saved text only)"
        )
    return 0


def _run_export_apps(scan_dir: Path, out: Path) -> int:
    try:
        result = export_apps(scan_dir, out)
    except AppsExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{result.apps} apps listed in {out}")
    if result.skipped:
        print(f"{result.skipped} entries without a package skipped")
    return 0


def _run_export_files(scan_dir: Path, out: Path, mode: str) -> int:
    if mode == "none":
        try:
            categories = found_categories(scan_dir)
        except FilesExportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"files left in their category folders in {scan_dir}: {', '.join(categories)}")
        return 0
    try:
        result = export_files(scan_dir, out, mode)
    except FilesExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    verb = "moved" if mode == "move" else "copied"
    print(f"{result.placed} files {verb} into {out}")
    if result.merged:
        print(f"{result.merged} duplicate files of the backup merged")
    if result.already_present:
        print(f"{result.already_present} files were already there")
    if result.conflicts:
        print(
            f"{result.conflicts} files had the same path but different content; "
            "kept as '<name> (2)'"
        )
    if result.originals:
        print(f"{result.originals} originals of edited photos in {out / ORIGINALS_FOLDER}")
    if result.dated:
        print(f"{result.dated} files got their original date back")
    if result.missing:
        print(f"{result.missing} files listed by Smart Switch were not found in the scan")
    if result.bad_manifests:
        print(f"{result.bad_manifests} Smart Switch file lists could not be read")
    if result.leftover_partials:
        print(
            f"{result.leftover_partials} unfinished '.ssba-*.partial' files from an "
            f"interrupted run are in {out}; they can be deleted"
        )
    return 0


_CLI_RUNNERS = {
    "contacts": _run_export_contacts,
    "messages": _run_export_messages,
    "calls": _run_export_calls,
    "wifi": _run_export_wifi,
    "blocked-numbers": _run_export_blocked_numbers,
    "browser": _run_export_browser,
    "clipboard": _run_export_clipboard,
    "clock": _run_export_clock,
    "notes": _run_export_notes,
    "apps": _run_export_apps,
}

# Every kind `export all` runs, in order, with the name it writes inside --out;
# `files` is added by _run_export_all because it needs the chosen mode.
_ALL_EXPORTS = tuple((e.key, _CLI_RUNNERS[e.key], e.target) for e in EXPORTS if e.key != "files")
_FILES_TARGET = next(e.target for e in EXPORTS if e.key == "files")


def _run_export_all(scan_dir: Path, out: Path, files_mode: str = "none") -> int:
    if not (scan_dir / "report.json").is_file():
        print(f"error: report.json not found in {scan_dir}", file=sys.stderr)
        return 1
    if files_mode in ("copy", "move"):
        # Before any exporter writes: an --out inside a category folder must not
        # get the other exports written into the scan either.
        try:
            check_out_dir(scan_dir, out / _FILES_TARGET)
        except FilesExportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    jobs = list(_ALL_EXPORTS) + [
        ("files", functools.partial(_run_export_files, mode=files_mode), _FILES_TARGET),
    ]
    written = 0
    for name, runner, target in jobs:
        print(f"== {name} ==")
        try:
            if runner(scan_dir, out / target) == 0:
                written += 1
        except Exception as exc:  # an unexpected bug in one exporter must not stop the rest
            print(f"error: {name} failed unexpectedly: {exc}", file=sys.stderr)
    print(f"\n{written} of {len(jobs)} exports written to {out}")
    return 0 if written else 1


_EXPORT_RUNNERS = {name: runner for name, runner, _ in _ALL_EXPORTS}


def run(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        try:
            report = scan_backup(args.backup_root, args.out, categories=args.categories)
        except UnsupportedBackupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        report_path = write_report(report, args.out)

        any_success = False
        for category in report.categories:
            counts = category.counts()
            total = sum(counts.values())
            if total == 0:
                continue
            if counts["decrypted"] or counts["plaintext_passthrough"]:
                any_success = True
            print(
                f"{category.category}: {counts['decrypted']} decrypted, "
                f"{counts['plaintext_passthrough']} plaintext, "
                f"{counts['undecoded']} undecoded, "
                f"{counts['error']} errors"
            )
        print(f"\nfull report written to {report_path}")
        return 0 if any_success else 1

    if args.command == "backups":
        roots = args.roots if args.roots is not None else default_roots()
        found = find_backups(roots)
        if not found:
            print(f"no Smart Switch backups found in {', '.join(str(r) for r in roots) or '(no folder)'}")
            return 0
        for backup in found:
            name = f"{backup.device_name} " if backup.device_name else ""
            when = backup.saved_at.strftime("%Y-%m-%d %H:%M") if backup.saved_at else "?"
            print(f"{backup.path}  {name}({backup.model})  {when}  {format_size(backup.size)}")
        return 0

    if args.command == "export":
        if args.export_kind == "all":
            return _run_export_all(args.scan_dir, args.out, args.files)
        if args.export_kind == "files":
            return _run_export_files(args.scan_dir, args.out, args.mode)
        return _EXPORT_RUNNERS[args.export_kind](args.scan_dir, args.out)

    return 1


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    sys.exit(run())
