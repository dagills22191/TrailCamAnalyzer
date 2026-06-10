# Build script for TrailCam Sorter Windows installer
# Run from the project root:  .\installer\build.ps1
#
# Requirements:
#   - trailcam conda environment (conda create -n trailcam python=3.11 pip -y && pip install -r requirements.txt)
#   - Inno Setup 6 installed (https://jrsoftware.org/isinfo.php) — for the .exe installer step

param(
    [string]$PyInstallerExe,
    [string]$PythonExe,
    [string]$InnoExe,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$SpecFile = "$PSScriptRoot\TrailCamSorter.spec"
$IssFile  = "$PSScriptRoot\setup.iss"

function Resolve-Executable {
    param(
        [string[]]$Candidates,
        [string]$CommandName
    )

    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    if ($CommandName) {
        $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
        if ($cmd) {
            return $cmd.Source
        }
    }

    return $null
}

$PyInstallerPath = Resolve-Executable -Candidates @(
    $PyInstallerExe,
    "$env:CONDA_PREFIX\Scripts\pyinstaller.exe",
    "$env:USERPROFILE\Miniconda3\envs\trailcam\Scripts\pyinstaller.exe",
    "$env:USERPROFILE\Anaconda3\envs\trailcam\Scripts\pyinstaller.exe"
) -CommandName "pyinstaller"

if (-not $PyInstallerPath) {
    throw "PyInstaller executable not found. Install pyinstaller or pass -PyInstallerExe <path>."
}

$PythonPath = Resolve-Executable -Candidates @(
    $PythonExe,
    "$env:CONDA_PREFIX\python.exe",
    "$env:USERPROFILE\Miniconda3\envs\trailcam\python.exe",
    "$env:USERPROFILE\Anaconda3\envs\trailcam\python.exe"
) -CommandName "python"

$InnoPath = Resolve-Executable -Candidates @(
    $InnoExe,
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) -CommandName "ISCC"

Write-Host "Using Python      : $PythonPath"
Write-Host "Using PyInstaller : $PyInstallerPath"
if ($InnoPath) {
    Write-Host "Using Inno Setup  : $InnoPath"
}

# -- Step 1: PyInstaller -------------------------------------------------------
Write-Host "`n=== Step 1: Building with PyInstaller ===" -ForegroundColor Cyan
Write-Host "This will take several minutes and produce a ~2-3 GB dist folder.`n"

Push-Location "$PSScriptRoot\.."
try {
    & $PyInstallerPath $SpecFile --clean -y
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

Write-Host "`nPyInstaller build complete: dist\TrailCamSorter\" -ForegroundColor Green

# -- Step 2: Inno Setup (optional) --------------------------------------------
if (-not $SkipInstaller -and $InnoPath) {
    Write-Host "`n=== Step 2: Building installer with Inno Setup ===" -ForegroundColor Cyan
    Push-Location "$PSScriptRoot\.."
    try {
        & $InnoPath $IssFile
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
    Write-Host "`nInstaller ready: installer\output\TrailCamSorter-Setup.exe" -ForegroundColor Green
} else {
    Write-Host "`n=== Step 2 skipped: Inno Setup not found or -SkipInstaller passed ===" -ForegroundColor Yellow
    Write-Host "To build the .exe installer:"
    Write-Host "  1. Install Inno Setup 6 from https://jrsoftware.org/isinfo.php"
    Write-Host "  2. Re-run this script (PyInstaller output will be reused)"
    Write-Host "  Or manually: `"<path-to-ISCC.exe>`" $IssFile"
}

Write-Host "`nDone." -ForegroundColor Green
