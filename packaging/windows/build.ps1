# Build the Windows app and its installer.
# --collect-submodules: the platform modules are imported by name at run time.
#   powershell -File packaging\windows\build.ps1 -Version 0.6.0
# Signing runs only when the certificate secrets are set (see docs/phat-hanh.md):
#   WIN_SIGN_COMMAND  the full signing command, with $f where the file goes, e.g.
#                     signtool sign /fd sha256 /tr http://ts.ssl.com /td sha256 /sha1 <thumbprint> $f
param([Parameter(Mandatory = $true)][string]$Version)
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root

python -m pip install -q -r requirements-build.txt
if (Test-Path dist\PCCleaner) { Remove-Item -Recurse -Force dist\PCCleaner }
python -m PyInstaller --noconfirm --windowed --name PCCleaner --collect-submodules pccleaner --add-data "pccleaner/web;pccleaner/web" run.py
if ($LASTEXITCODE) { throw "PyInstaller failed" }

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
  choco install innosetup -y --no-progress | Out-Null
  $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
}

$isccArgs = @("/DAppVersion=$Version")  # not $args: that name is taken by PowerShell
if ($env:WIN_SIGN_COMMAND) {
  # Sign the program itself first, then let Inno Setup sign the installer and uninstaller.
  & cmd /c ($env:WIN_SIGN_COMMAND -replace '\$f', '"dist\PCCleaner\PCCleaner.exe"')
  if ($LASTEXITCODE) { throw "signing PCCleaner.exe failed" }
  $isccArgs += "/DSignCommand=1"
  $isccArgs += "/Spcc=$env:WIN_SIGN_COMMAND"  # Inno Setup puts the file where $f is
}
& $iscc @isccArgs packaging\windows\pccleaner.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }
Write-Host "Built dist\PCCleaner-Setup-$Version.exe"
