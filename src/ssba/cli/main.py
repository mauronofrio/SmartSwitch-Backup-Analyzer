"""Command-line entry point for the Smart Switch backup analyzer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ssba.core.errors import UnsupportedBackupError
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

    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        try:
            report = scan_backup(args.backup_root, args.out)
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

    return 1


def main() -> None:
    sys.exit(run())
