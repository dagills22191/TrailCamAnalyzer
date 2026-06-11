# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller onefile spec for TrailCam Sorter portable executable
# Build from the project root:
#   pyinstaller installer\TrailCamSorter.onefile.spec --clean -y
#
# Output: dist\TrailCamSorter-Portable.exe
# Model weights are NOT bundled — downloaded at first run to %USERPROFILE%\.cache\kagglehub\

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

for pkg in ['customtkinter', 'speciesnet', 'yolov5']:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ['..\\trailcam_sorter.py'],
    pathex=['..'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + [
        'speciesnet',
        'tkinter',
        'tkinter.filedialog',
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='TrailCamSorter-Portable',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)
