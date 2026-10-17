"""Точка входа: создание приложения, окна и платформенных адаптеров.

Приложение никогда не начинает кликать само: движок запускается только кнопкой
«Старт» или горячей клавишей.
"""

from __future__ import annotations

import argparse
import atexit
import signal
import sys
import tempfile
from pathlib import Path

from . import __version__


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="autoclicker", description="AutoClicker")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="проверить, что приложение и все модули загружаются, и выйти (без кликов и окон)",
    )
    parser.add_argument("--version", action="version", version=f"AutoClicker {__version__}")
    # PyInstaller на macOS может передать -psn_…; Qt — свои аргументы. Лишнее игнорируем.
    args, _unknown = parser.parse_known_args(argv)
    return args


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = _parse_args(argv[1:])

    from .platform import IS_MAC, IS_WIN

    if not (IS_MAC or IS_WIN):
        print("AutoClicker поддерживает только macOS и Windows.", file=sys.stderr)
        return 2

    from PySide6.QtCore import QStandardPaths, QTimer
    from PySide6.QtWidgets import QApplication

    from . import platform as plat
    from .gui.icon import app_icon
    from .gui.main_window import MainWindow
    from .gui.theme import apply_theme
    from .storage import SettingsStore

    QApplication.setApplicationName("AutoClicker")
    QApplication.setApplicationDisplayName("AutoClicker")
    QApplication.setApplicationVersion(__version__)
    app = QApplication(argv)
    apply_theme(app)
    app.setWindowIcon(app_icon())

    if args.smoke_test:
        return _smoke_test(app)

    config_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    store = SettingsStore(config_dir)
    stored = store.load()

    adapter = plat.get_mouse_adapter()
    listener = plat.get_key_listener()
    window = MainWindow(adapter, listener, store, stored)
    # Если процесс завершается нештатно — всё равно отпустить кнопку мыши.
    atexit.register(window.emergency_release)

    # Ctrl+C в терминале: закрыть окно штатно (с отпусканием кнопки и сохранением).
    signal.signal(signal.SIGINT, lambda *_: window.close())
    wake = QTimer()
    wake.start(250)  # даёт интерпретатору обработать сигнал во время цикла Qt
    wake.timeout.connect(lambda: None)

    window.show()
    return app.exec()


def _smoke_test(app) -> int:  # noqa: ANN001
    """Проверка сборки: модули, Qt-плагины, адаптер (только чтение), окно — без кликов,
    без глобального слушателя и без записи настроек пользователя."""
    from . import platform as plat
    from .engine import ClickEngine
    from .gui.main_window import MainWindow
    from .model import Settings, validate
    from .storage import SettingsStore, Stored

    errors: list[str] = []
    previous_hook = sys.excepthook

    def hook(exc_type, exc, tb):  # noqa: ANN001
        errors.append(f"{exc_type.__name__}: {exc}")
        previous_hook(exc_type, exc, tb)

    sys.excepthook = hook  # исключения в слотах Qt иначе только печатаются

    adapter = plat.get_mouse_adapter()
    x, y = adapter.get_position()
    corner = adapter.corner_region()
    perms = plat.check_permissions()
    assert not validate(Settings())
    with tempfile.TemporaryDirectory() as tmp:
        window = MainWindow(adapter, None, SettingsStore(Path(tmp)), Stored())
        assert isinstance(window.engine, ClickEngine)
        assert not window.engine.is_active()
        window.grab()  # отрисовка без показа на экране
        window.close()
    app.processEvents()
    sys.excepthook = previous_hook
    if errors:
        print("SMOKE FAILED: " + "; ".join(errors), file=sys.stderr)
        return 1
    print(
        f"SMOKE OK: AutoClicker {__version__}; курсор ({x}, {y}); угол {corner}; "
        f"мышь={perms.can_control_mouse.value}, клавиатура={perms.can_listen_input.value}"
    )
    return 0
