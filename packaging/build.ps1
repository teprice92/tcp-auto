# Build the FlagPole Windows app. Run in PowerShell from the repo folder:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1          -> dist\FlagPole\FlagPole.exe (+ zip)
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -OneFile -> dist\FlagPole.exe
param([switch]$OneFile)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
py -3 -m venv .build-venv
. .\.build-venv\Scripts\Activate.ps1
python -m pip install --upgrade pip | Out-Null
pip install .\backend pyinstaller
if ($OneFile) {
  $env:FLAGPOLE_ONEFILE = "1"
  pyinstaller --noconfirm flagpole.spec
  Write-Host "Built dist\FlagPole.exe"
} else {
  pyinstaller --noconfirm flagpole.spec
  Compress-Archive -Path dist\FlagPole -DestinationPath dist\FlagPole-windows.zip -Force
  Write-Host "Built dist\FlagPole\FlagPole.exe and dist\FlagPole-windows.zip"
}
