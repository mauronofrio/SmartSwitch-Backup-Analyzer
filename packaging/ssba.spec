# PyInstaller spec: one folder with the GUI and the command-line program.
# Build with packaging/build.ps1.
from pathlib import Path

HERE = Path(SPECPATH)
SRC = str(HERE.parent / "src")

gui = Analysis([str(HERE / "ssba_gui.py")], pathex=[SRC])
cli = Analysis([str(HERE / "ssba_cli.py")], pathex=[SRC], excludes=["PySide6"])

gui_exe = EXE(
    PYZ(gui.pure), gui.scripts, [],
    exclude_binaries=True, name='SmartSwitch Backup Analyzer', console=False,
)
cli_exe = EXE(
    PYZ(cli.pure), cli.scripts, [],
    exclude_binaries=True, name='ssba', console=True,
)
COLLECT(
    gui_exe, gui.binaries, gui.datas,
    cli_exe, cli.binaries, cli.datas,
    name='SmartSwitch-Backup-Analyzer',
)
