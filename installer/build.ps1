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
    [switch]$SkipInstaller,
    [switch]$OneFile,
    [switch]$OneFileOnly
)

$ErrorActionPreference = "Stop"

$OneDirSpecFile  = "$PSScriptRoot\TrailCamSorter.spec"
$OneFileSpecFile = "$PSScriptRoot\TrailCamSorter.onefile.spec"
$IssFile         = "$PSScriptRoot\setup.iss"

$BuildOneDir = -not $OneFileOnly
$BuildOneFile = $OneFile -or $OneFileOnly
if ($OneFileOnly) {
    $SkipInstaller = $true
}

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
Push-Location "$PSScriptRoot\.."
try {
    if ($BuildOneDir) {
        Write-Host "`n=== Step 1A: Building folder distribution (onedir) ===" -ForegroundColor Cyan
        Write-Host "This will take several minutes and produce dist\TrailCamSorter\." 
        & $PyInstallerPath $OneDirSpecFile --clean -y
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller onedir build failed (exit $LASTEXITCODE)" }
        Write-Host "Onedir build complete: dist\TrailCamSorter\" -ForegroundColor Green
    }

    if ($BuildOneFile) {
        Write-Host "`n=== Step 1B: Building portable single-file executable (onefile) ===" -ForegroundColor Cyan
        Write-Host "This can take longer and the executable may be large due to PyTorch dependencies." 
        & $PyInstallerPath $OneFileSpecFile --clean -y
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller onefile build failed (exit $LASTEXITCODE)" }
        Write-Host "Onefile build complete: dist\TrailCamSorter-Portable.exe" -ForegroundColor Green
    }
} finally {
    Pop-Location
}

# -- Step 2: Inno Setup (optional) --------------------------------------------
if ($BuildOneDir -and -not $SkipInstaller -and $InnoPath) {
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
    Write-Host "`n=== Step 2 skipped ===" -ForegroundColor Yellow
    if (-not $BuildOneDir) {
        Write-Host "Installer build skipped because -OneFileOnly was used."
    } else {
        Write-Host "Inno Setup not found or -SkipInstaller passed."
        Write-Host "To build the .exe installer:"
        Write-Host "  1. Install Inno Setup 6 from https://jrsoftware.org/isinfo.php"
        Write-Host "  2. Re-run this script (PyInstaller output will be reused)"
        Write-Host "  Or manually: `"<path-to-ISCC.exe>`" $IssFile"
    }
}

Write-Host "`nDone." -ForegroundColor Green
