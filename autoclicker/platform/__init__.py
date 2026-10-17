"""Выбор платформенных адаптеров.

Для каждой ОС — свой нативный модуль (macos.py / windows.py): у систем разные
API ввода, разрешения и единицы координат, и общая прослойка их не скрывает.
"""

from __future__ import annotations

import sys

from .base import KeyListener, MouseAdapter, PermissionInfo, PermissionState

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")
# Ключ платформы для подписей клавиш (keymaps.format_hotkey).
PLATFORM_KEY = "darwin" if IS_MAC else "win32"


class UnsupportedPlatformError(RuntimeError):
    pass


def _unsupported() -> UnsupportedPlatformError:
    return UnsupportedPlatformError("Поддерживаются только macOS и Windows.")


def get_mouse_adapter() -> MouseAdapter:
    if IS_MAC:
        from .macos import MacMouseAdapter

        return MacMouseAdapter()
    if IS_WIN:
        from .windows import WinMouseAdapter

        return WinMouseAdapter()
    raise _unsupported()


def get_key_listener() -> KeyListener:
    if IS_MAC:
        from .macos import MacKeyListener

        return MacKeyListener()
    if IS_WIN:
        from .windows import WinKeyListener

        return WinKeyListener()
    raise _unsupported()


def check_permissions() -> PermissionInfo:
    if IS_MAC:
        from .macos import check_permissions as check

        return check()
    if IS_WIN:
        from .windows import check_permissions as check

        return check()
    return PermissionInfo(PermissionState.UNKNOWN, PermissionState.UNKNOWN, "ОС не поддерживается.")


def request_mouse_permission() -> None:
    """macOS: системный запрос «Универсальный доступ». На Windows не требуется."""
    if IS_MAC:
        from .macos import request_mouse_permission as request

        request()


def request_input_permission() -> None:
    """macOS: системный запрос «Мониторинг ввода». На Windows не требуется."""
    if IS_MAC:
        from .macos import request_input_permission as request

        request()


def settings_url(kind: str) -> str | None:
    """Ссылка на нужный раздел системных настроек ("mouse" или "input")."""
    if IS_MAC:
        from .macos import SETTINGS_URLS

        return SETTINGS_URLS.get(kind)
    return None


def begin_session() -> None:
    """Вызывается движком в рабочем потоке перед кликами (точные таймеры, без App Nap)."""
    if IS_MAC:
        from .macos import begin_session as begin

        begin()
    elif IS_WIN:
        from .windows import begin_session as begin

        begin()


def end_session() -> None:
    if IS_MAC:
        from .macos import end_session as end

        end()
    elif IS_WIN:
        from .windows import end_session as end

        end()


def probe_hotkey_conflict(modifiers: frozenset[str], key: str) -> bool | None:
    """True — сочетание занято другой программой, False — свободно, None — неизвестно.

    Проверка возможна только на Windows (RegisterHotKey) и находит не все конфликты.
    macOS не даёт API, чтобы узнать, занято ли сочетание другими приложениями.
    """
    if IS_WIN:
        from .windows import probe_hotkey_conflict as probe

        try:
            return probe(modifiers, key)
        except Exception:  # noqa: BLE001
            return None
    return None


def is_elevated() -> bool:
    """Windows: запущено ли приложение от имени администратора."""
    if IS_WIN:
        from .windows import is_elevated as elevated

        return elevated()
    return False


def coordinate_units() -> str:
    if IS_MAC:
        return "логические точки (Retina учитывается системой)"
    if IS_WIN:
        return "физические пиксели (с учётом масштабирования Windows)"
    return "пиксели"
