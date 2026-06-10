# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for TrailCam Sorter
# Build from the project root:
#   C:\Users\Tim\Miniconda3\envs\trailcam\Scripts\pyinstaller.exe installer\TrailCamSorter.spec
#
# Output: dist\TrailCamSorter\  (~2-3 GB due to PyTorch)
# Model weights are NOT bundled — downloaded at first run to %USERPROFILE%\.cache\kagglehub\

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

datas = []
binaries = []
hiddenimports = []

for pkg in ['customtkinter', 'speciesnet', 'yolov5']:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Copy package metadata for packages that read it at runtime via importlib.metadata
for pkg in ['cloudpathlib', 'kagglehub', 'speciesnet', 'torch', 'torchvision']:
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

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
        'pkg_resources.py2_warn',
        'onnx2torch',
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
    [],
    exclude_binaries=True,
    name='TrailCamSorter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='TrailCamSorter',
)
