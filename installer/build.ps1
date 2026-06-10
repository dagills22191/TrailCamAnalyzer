# Build script for TrailCam Sorter Windows installer
# Run from the project root:  .\installer\build.ps1
#
# Requirements:
#   - trailcam conda environment (conda create -n trailcam python=3.11 pip -y && pip install -r requirements.txt)
#   - Inno Setup 6 installed (https://jrsoftware.org/isinfo.php) — for the .exe installer step

$ErrorActionPreference = "Stop"

$Python  = "C:\Users\Tim\Miniconda3\envs\trailcam\python.exe"
$PyInst  = "C:\Users\Tim\Miniconda3\envs\trailcam\Scripts\pyinstaller.exe"
$SpecFile = "$PSScriptRoot\TrailCamSorter.spec"
$InnoExe  = if (Test-Path "C:\Program Files (x86)\Inno Setup 6\ISCC.exe") { "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" } else { "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" }
$IssFile  = "$PSScriptRoot\setup.iss"

# -- Step 1: PyInstaller -------------------------------------------------------
Write-Host "`n=== Step 1: Building with PyInstaller ===" -ForegroundColor Cyan
Write-Host "This will take several minutes and produce a ~2-3 GB dist folder.`n"

Push-Location "$PSScriptRoot\.."
try {
    & $PyInst $SpecFile --clean -y
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

Write-Host "`nPyInstaller build complete: dist\TrailCamSorter\" -ForegroundColor Green

# -- Step 2: Inno Setup (optional) --------------------------------------------
if (Test-Path $InnoExe) {
    Write-Host "`n=== Step 2: Building installer with Inno Setup ===" -ForegroundColor Cyan
    Push-Location "$PSScriptRoot\.."
    try {
        & $InnoExe $IssFile
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
    Write-Host "`nInstaller ready: installer\output\TrailCamSorter-Setup.exe" -ForegroundColor Green
} else {
    Write-Host "`n=== Step 2 skipped: Inno Setup not found ===" -ForegroundColor Yellow
    Write-Host "To build the .exe installer:"
    Write-Host "  1. Install Inno Setup 6 from https://jrsoftware.org/isinfo.php"
    Write-Host "  2. Re-run this script (PyInstaller output will be reused)"
    Write-Host "  Or manually: `"$InnoExe`" $IssFile"
}

Write-Host "`nDone." -ForegroundColor Green
