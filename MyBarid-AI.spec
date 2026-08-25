# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project = Path(SPECPATH)
hiddenimports = collect_submodules("webview.platforms")

a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[
        (str(project / "ui"), "ui"),
        (str(project / "config" / "v2_criteria.json"), "config"),
        (str(project / "config" / "criteria_guides.json"), "config"),
        (str(project / "VERSION"), "."),
        (str(project / "CHANGELOG.json"), "."),
    ],
    hiddenimports=hiddenimports,
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
    a.datas,
    [],
    name="MyBarid-AI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
