"""Command-line entry point for the Smart Switch backup analyzer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ssba.core.errors import UnsupportedBackupError
from ssba.core.parsers.calls import CallExportError, export_calls
from ssba.core.parsers.contact import ContactExportError, export_contacts
from ssba.core.parsers.messages import MessageExportError, export_messages
from ssba.core.scanner import scan_backup


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

    export_parser = subparsers.add_parser(
        "export", help="turn `ssba scan` output into files you can import elsewhere"
    )
    export_kinds = export_parser.add_subparsers(dest="export_kind", required=True)
    contacts_parser = export_kinds.add_parser(
        "contacts", help="merge the recovered contacts into one vCard 3.0 file"
    )
    contacts_parser.add_argument(
        "scan_dir", type=Path, help="directory written by `ssba scan --out`"
    )
    contacts_parser.add_argument(
        "--out", type=Path, required=True, help="path of the .vcf file to write"
    )

    messages_parser = export_kinds.add_parser(
        "messages", help="write the recovered text messages as SMS Backup & Restore XML"
    )
    messages_parser.add_argument(
        "scan_dir", type=Path, help="directory written by `ssba scan --out`"
    )
    messages_parser.add_argument(
        "--out", type=Path, required=True, help="path of the .xml file to write"
    )
    calls_parser = export_kinds.add_parser(
        "calls", help="write the recovered call log as SMS Backup & Restore XML"
    )
    calls_parser.add_argument(
        "scan_dir", type=Path, help="directory written by `ssba scan --out`"
    )
    calls_parser.add_argument(
        "--out", type=Path, required=True, help="path of the .xml file to write"
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


def run(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        try:
            report = scan_backup(args.backup_root, args.out, categories=args.categories)
        except UnsupportedBackupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        args.out.mkdir(parents=True, exist_ok=True)
        report_path = args.out / "report.json"
        report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

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

    if args.command == "export" and args.export_kind == "contacts":
        return _run_export_contacts(args.scan_dir, args.out)

    if args.command == "export" and args.export_kind == "messages":
        return _run_export_messages(args.scan_dir, args.out)

    if args.command == "export" and args.export_kind == "calls":
        return _run_export_calls(args.scan_dir, args.out)

    return 1


def main() -> None:
    sys.exit(run())
