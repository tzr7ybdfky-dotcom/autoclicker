# -*- mode: python ; coding: utf-8 -*-
# Спецификация PyInstaller. Запускать на той ОС, для которой собирается приложение:
#   macOS:   packaging/build_macos.sh   → dist/AutoClicker.app
#   Windows: packaging\build_windows.ps1 → dist\AutoClicker\AutoClicker.exe
# Архитектура macOS задаётся переменной AUTOCLICKER_ARCH: arm64 | x86_64 | universal2
# (пусто — архитектура текущего Python).

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
ICONS = ROOT / "build" / "icons"
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")

sys.path.insert(0, str(ROOT))
from autoclicker import __version__  # noqa: E402

target_arch = os.environ.get("AUTOCLICKER_ARCH") or None

# Модули другой ОС и ненужные части Qt/stdlib в сборку не попадают.
excludes = ["tkinter", "unittest", "pydoc_data", "pytest", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick"]
if IS_WIN:
    excludes += ["Quartz", "Foundation", "AppKit", "objc", "autoclicker.platform.macos"]
if IS_MAC:
    excludes += ["autoclicker.platform.windows"]

a = Analysis(
    [str(ROOT / "packaging" / "run_autoclicker.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=["autoclicker.platform.macos"] if IS_MAC else ["autoclicker.platform.windows"],
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoClicker",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # без окна консоли
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=target_arch,
    codesign_identity=os.environ.get("AUTOCLICKER_CODESIGN_IDENTITY") or None,
    entitlements_file=None,
    icon=str(ICONS / ("AutoClicker.ico" if IS_WIN else "AutoClicker.icns")),
    uac_admin=False,  # права администратора не нужны и не запрашиваются
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AutoClicker")

if IS_MAC:
    app = BUNDLE(
        coll,
        name="AutoClicker.app",
        icon=str(ICONS / "AutoClicker.icns"),
        bundle_identifier="local.autoclicker.desktop",
        version=__version__,
        info_plist={
            "CFBundleName": "AutoClicker",
            "CFBundleDisplayName": "AutoClicker",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.utilities",
            "NSHumanReadableCopyright": "AutoClicker",
        },
    )
