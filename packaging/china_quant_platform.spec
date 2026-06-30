# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPECPATH).parent
if not (project_root / "src").exists():
    project_root = project_root.parent
src_root = project_root / "src"
block_cipher = None

a = Analysis(
    [str(src_root / "china_quant_platform" / "__main__.py")],
    pathex=[str(src_root)],
    binaries=[],
    datas=[
        (str(project_root / "assets"), "assets"),
        (str(project_root / "docs"), "docs"),
        (str(project_root / "spec"), "spec"),
        (str(project_root / "MANIFEST.sha256"), "."),
    ],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="china-quant-platform",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="china-quant-platform",
)
