"""Создать файлы иконки для сборки: AutoClicker.icns (macOS) и AutoClicker.ico (Windows).

Иконка рисуется кодом (autoclicker/gui/icon.py) и сохраняется плагинами форматов Qt.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from autoclicker.gui.icon import render_icon  # noqa: E402


def main() -> int:
    app = QGuiApplication(sys.argv[:1])  # noqa: F841 — нужен для плагинов изображений
    out = ROOT / "build" / "icons"
    out.mkdir(parents=True, exist_ok=True)
    render_icon(1024).save(str(out / "AutoClicker.png"))
    ok_icns = render_icon(1024).save(str(out / "AutoClicker.icns"), "ICNS")
    ok_ico = render_icon(256).save(str(out / "AutoClicker.ico"), "ICO")
    print(f"icns: {ok_icns}, ico: {ok_ico} -> {out}")
    return 0 if (ok_ico and (ok_icns or sys.platform != "darwin")) else 1


if __name__ == "__main__":
    sys.exit(main())
