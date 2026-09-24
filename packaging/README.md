# Windows package

`.\packaging\build.ps1` creates `dist\SmartSwitch-Backup-Analyzer\` with
`SmartSwitch Backup Analyzer.exe` (the wizard) and `ssba.exe` (the command
line), and zips it as `dist\SmartSwitch-Backup-Analyzer-<version>-windows.zip`.
Publishing the zip on GitHub Releases is done by hand.

The icon is `src/ssba/gui/icon.svg`; after changing it, run
`python packaging/make_icon.py` to regenerate `icon.ico`.
