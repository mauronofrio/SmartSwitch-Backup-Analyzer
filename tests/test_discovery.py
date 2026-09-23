from __future__ import annotations

from datetime import datetime

import pytest

from ssba.core.discovery import find_backups, format_size, read_backup
from ssba.core.errors import UnsupportedBackupError
from tests.discovery_fixtures import write_history


def _layout(root):
    old = write_history(root / "SM-X" / "SM-X_" / "SM-X_20260101", saved="2026-01-01T10:00:00")
    new = write_history(root / "SM-X" / "SM-X_" / "SM-X_20260301", saved="2026-03-01T10:00:00",
                        items=(("CONTACT\\Contact.spbm", 3), ("SAMSUNGNOTE\\sdoc.snmm", 7),
                               ("SAMSUNGNOTE\\other.bk", 1)))
    second = write_history(root / "SM-X" / "SM-X_2" / "SM-X_20260201", name="Altro",
                           saved="2026-02-01T10:00:00")
    return old, new, second


def test_backups_are_found_newest_first(tmp_path):
    old, new, second = _layout(tmp_path / "root")
    assert [b.path for b in find_backups([tmp_path / "root"])] == [new, second, old]


def test_backup_summary_is_read(tmp_path):
    _, new, _ = _layout(tmp_path / "root")
    info = read_backup(new)
    assert (info.device_name, info.model, info.size) == ("Telefono", "SM-X", 1234)
    assert info.saved_at == datetime(2026, 3, 1, 10, 0, 0)
    assert info.items == {"CONTACT": 3, "SAMSUNGNOTE": 8}


def test_folders_deeper_than_three_levels_are_ignored(tmp_path):
    write_history(tmp_path / "root" / "a" / "b" / "c" / "d")
    assert find_backups([tmp_path / "root"]) == []


def test_missing_roots_are_skipped(tmp_path):
    assert find_backups([tmp_path / "nowhere"]) == []


def test_malformed_history_still_yields_an_entry(tmp_path):
    folder = tmp_path / "root" / "SM-Y_1"
    folder.mkdir(parents=True)
    (folder / "backupHistoryInfo.xml").write_text("<not xml", encoding="utf-8")
    [info] = find_backups([tmp_path / "root"])
    assert (info.model, info.device_name, info.saved_at, info.size, info.items) == ("SM-Y_1", "", None, None, {})


def test_a_folder_without_history_is_not_a_backup(tmp_path):
    with pytest.raises(UnsupportedBackupError, match="backupHistoryInfo.xml"):
        read_backup(tmp_path)


@pytest.mark.parametrize("size, text", [(None, "?"), (512, "512 B"), (2048, "2.0 KB"), (58392323062, "54.4 GB")])
def test_format_size(size, text):
    assert format_size(size) == text
