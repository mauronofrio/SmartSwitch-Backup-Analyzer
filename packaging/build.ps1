# Build the Windows package: .\packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venv = Join-Path $root "build\venv"
if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
python -m venv $venv
if ($LASTEXITCODE -ne 0) { throw "python -m venv failed" }
& "$venv\Scripts\python.exe" -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip install --upgrade pip failed" }
& "$venv\Scripts\python.exe" -m pip install ".[gui,build]"
if ($LASTEXITCODE -ne 0) { throw "pip install .[gui,build] failed" }
& "$venv\Scripts\pyinstaller.exe" --noconfirm --distpath dist --workpath build\pyinstaller packaging\ssba.spec
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }
$version = (& "$venv\Scripts\python.exe" -c "import importlib.metadata as m; print(m.version('smartswitch-backup-analyzer'))").Trim()
if ($LASTEXITCODE -ne 0) { throw "version query failed" }
$app = Join-Path $root "dist\SmartSwitch-Backup-Analyzer"
Copy-Item (Join-Path $root "LICENSE") (Join-Path $app "LICENSE.txt")
Copy-Item (Join-Path $root "packaging\LEGGIMI.txt") (Join-Path $app "LEGGIMI - README.txt")
$zip = Join-Path $root "dist\SmartSwitch-Backup-Analyzer-$version-windows.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $root "dist\SmartSwitch-Backup-Analyzer\*") -DestinationPath $zip
Write-Host "Built $zip"
