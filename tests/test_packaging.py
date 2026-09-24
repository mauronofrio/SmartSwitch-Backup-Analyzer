from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_packaging_files_exist_and_name_both_programs():
    spec = (ROOT / "packaging" / "ssba.spec").read_text(encoding="utf-8")
    assert "SmartSwitch Backup Analyzer" in spec
    assert "name='ssba'" in spec
    assert (ROOT / "packaging" / "build.ps1").is_file()


def test_entry_scripts_call_the_right_main(monkeypatch):
    called = []
    monkeypatch.setattr("ssba.cli.main.main", lambda: called.append("cli"))
    runpy.run_path(str(ROOT / "packaging" / "ssba_cli.py"), run_name="__main__")
    assert called == ["cli"]


def test_both_programs_get_the_icon():
    spec = (ROOT / "packaging" / "ssba.spec").read_text(encoding="utf-8")
    assert spec.count("icon=ICON") == 2
    assert (ROOT / "src" / "ssba" / "gui" / "icon.svg").is_file()


def test_the_zip_gets_the_license_and_a_readme():
    script = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    assert "LICENSE.txt" in script
    assert "LEGGIMI" in script
    assert (ROOT / "packaging" / "LEGGIMI.txt").is_file()
