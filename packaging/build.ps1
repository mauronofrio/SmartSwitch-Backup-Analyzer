# Build the Windows package: .\packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venv = Join-Path $root "build\venv"
if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
python -m venv $venv
& "$venv\Scripts\python.exe" -m pip install --upgrade pip
& "$venv\Scripts\python.exe" -m pip install ".[gui,build]"
& "$venv\Scripts\pyinstaller.exe" --noconfirm --distpath dist --workpath build\pyinstaller packaging\ssba.spec
$version = (& "$venv\Scripts\python.exe" -c "import importlib.metadata as m; print(m.version('smartswitch-backup-analyzer'))").Trim()
$zip = Join-Path $root "dist\SmartSwitch-Backup-Analyzer-$version-windows.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $root "dist\SmartSwitch-Backup-Analyzer\*") -DestinationPath $zip
Write-Host "Built $zip"
