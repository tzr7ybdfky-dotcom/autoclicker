"""Адаптеры macOS: мышь через Quartz CGEvent, глобальные клавиши через CGEventTap.

Нужные разрешения («Системные настройки → Конфиденциальность и безопасность»):
  • «Универсальный доступ» — отправка событий мыши в другие приложения
    (проверка: CGPreflightPostEventAccess).
  • «Мониторинг ввода» — глобальное сочетание и Esc через event tap в режиме
    listen-only (проверка: CGPreflightListenEventAccess).
Запись экрана не нужна и не запрашивается.

Координаты: глобальное пространство Quartz в логических точках с началом в левом
верхнем углу основного экрана. На Retina одна точка — это 2×2 физических пикселя;
Quartz сам переводит точки в пиксели, поэтому отдельный пересчёт не нужен.
Мониторы левее/выше основного дают отрицательные координаты — это нормально.
"""

from __future__ import annotations

import threading
from typing import Callable

import Foundation
import Quartz

from ..model import MouseButton
from .base import KeyEventKind, PermissionInfo, PermissionState, RawKeyEvent
from .keymaps import MAC_CODE_TO_NAME, MAC_MODIFIER_CODES

CORNER_LOGICAL = 5

_DOWN = {
    MouseButton.LEFT: Quartz.kCGEventLeftMouseDown,
    MouseButton.RIGHT: Quartz.kCGEventRightMouseDown,
    MouseButton.MIDDLE: Quartz.kCGEventOtherMouseDown,
}
_UP = {
    MouseButton.LEFT: Quartz.kCGEventLeftMouseUp,
    MouseButton.RIGHT: Quartz.kCGEventRightMouseUp,
    MouseButton.MIDDLE: Quartz.kCGEventOtherMouseUp,
}
_BTN = {
    MouseButton.LEFT: Quartz.kCGMouseButtonLeft,
    MouseButton.RIGHT: Quartz.kCGMouseButtonRight,
    MouseButton.MIDDLE: Quartz.kCGMouseButtonCenter,
}


def _cursor_point():  # noqa: ANN202
    return Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))


class MacMouseAdapter:
    def __init__(self) -> None:
        self._source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        # Без этого после программного перемещения система на ~0,25 с «глушит»
        # реальную мышь — пользователь не смог бы увести курсор в угол остановки.
        Quartz.CGEventSourceSetLocalEventsSuppressionInterval(self._source, 0.0)

    def _post_mouse(self, event_type: int, button: MouseButton, point) -> None:  # noqa: ANN001
        event = Quartz.CGEventCreateMouseEvent(self._source, event_type, point, _BTN[button])
        Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventClickState, 1)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def press(self, button: MouseButton) -> None:
        # Нажатие в текущей позиции курсора: курсор не двигается.
        self._post_mouse(_DOWN[button], button, _cursor_point())

    def release(self, button: MouseButton) -> None:
        self._post_mouse(_UP[button], button, _cursor_point())

    def move_to(self, x: int, y: int) -> None:
        point = Quartz.CGPointMake(float(x), float(y))
        event = Quartz.CGEventCreateMouseEvent(
            self._source, Quartz.kCGEventMouseMoved, point, Quartz.kCGMouseButtonLeft
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def get_position(self) -> tuple[int, int]:
        p = _cursor_point()
        return int(round(p.x)), int(round(p.y))

    def corner_region(self) -> tuple[int, int, int, int]:
        b = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())  # origin основного экрана = (0, 0)
        x0, y0 = int(b.origin.x), int(b.origin.y)
        return (x0, y0, x0 + CORNER_LOGICAL, y0 + CORNER_LOGICAL)

    def point_available(self, x: int, y: int) -> bool:
        err, _displays, count = Quartz.CGGetDisplaysWithPoint((float(x), float(y)), 1, None, None)
        return err == 0 and count > 0


# --- глобальный слушатель клавиатуры -----------------------------------------

_MOD_FLAGS = (
    (Quartz.kCGEventFlagMaskControl, "ctrl"),
    (Quartz.kCGEventFlagMaskAlternate, "alt"),
    (Quartz.kCGEventFlagMaskShift, "shift"),
    (Quartz.kCGEventFlagMaskCommand, "meta"),
)


def flags_to_modifiers(flags: int) -> frozenset[str]:
    return frozenset(name for mask, name in _MOD_FLAGS if flags & mask)


class MacKeyListener:
    """CGEventTap в режиме listen-only на своём потоке с собственным CFRunLoop.

    Событие возвращается системе без изменений: клавиши не подавляются и доходят
    до активного приложения (в том числе Esc). Модификаторы берутся из флагов
    самого события, автоповтор — из поля kCGKeyboardEventAutorepeat.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop_requested = False
        self._tap = None
        self._handler = None  # ссылка на колбэк, чтобы его не собрал GC
        self._callback: Callable[[RawKeyEvent], None] | None = None
        self._available = False
        self._error = ""

    @property
    def available(self) -> bool:
        return self._available

    @property
    def error(self) -> str:
        return self._error

    def start(self, callback: Callable[[RawKeyEvent], None]) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._callback = callback
        self._stop_requested = False
        self._ready.clear()
        self._available = False
        self._error = ""
        self._thread = threading.Thread(target=self._run, name="mac-key-tap", daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        self._stop_requested = True
        thread = self._thread
        if thread is not None:
            thread.join(1.0)
        self._available = False

    def _run(self) -> None:
        mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
            | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        )

        def handler(proxy, event_type, event, refcon):  # noqa: ANN001, ARG001
            try:
                if event_type in (
                    Quartz.kCGEventTapDisabledByTimeout,
                    Quartz.kCGEventTapDisabledByUserInput,
                ):
                    # Система временно выключила tap — включаем обратно.
                    if self._tap is not None:
                        Quartz.CGEventTapEnable(self._tap, True)
                else:
                    self._dispatch(event_type, event)
            except Exception:  # noqa: BLE001 — слушатель не должен падать
                pass
            return event

        self._handler = handler
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            handler,
            None,
        )
        if not tap:
            self._error = (
                "Глобальные клавиши недоступны: нет разрешения «Мониторинг ввода». "
                "Выдайте его в «Системные настройки → Конфиденциальность и безопасность» "
                "и перезапустите приложение."
            )
            self._ready.set()
            return

        self._tap = tap
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(loop, source, Quartz.kCFRunLoopDefaultMode)
        Quartz.CGEventTapEnable(tap, True)
        self._available = True
        self._ready.set()
        try:
            while not self._stop_requested:
                Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.25, False)
        finally:
            Quartz.CGEventTapEnable(tap, False)
            Quartz.CFRunLoopRemoveSource(loop, source, Quartz.kCFRunLoopDefaultMode)
            Quartz.CFMachPortInvalidate(tap)
            self._tap = None
            self._available = False

    def _dispatch(self, event_type: int, event) -> None:  # noqa: ANN001
        callback = self._callback
        if callback is None:
            return
        modifiers = flags_to_modifiers(Quartz.CGEventGetFlags(event))
        code = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode))

        if event_type == Quartz.kCGEventFlagsChanged:
            mod = MAC_MODIFIER_CODES.get(code)
            if mod is None:
                return  # CapsLock, Fn и т. п.
            kind = KeyEventKind.DOWN if mod in modifiers else KeyEventKind.UP
            callback(RawKeyEvent(kind=kind, key="", modifiers=modifiers, autorepeat=False))
            return

        autorepeat = bool(
            Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat)
        )
        kind = KeyEventKind.DOWN if event_type == Quartz.kCGEventKeyDown else KeyEventKind.UP
        key = MAC_CODE_TO_NAME.get(code, f"KEY{code}")
        callback(RawKeyEvent(kind=kind, key=key, modifiers=modifiers, autorepeat=autorepeat))


# --- разрешения --------------------------------------------------------------


def check_permissions() -> PermissionInfo:
    try:
        can_post = bool(Quartz.CGPreflightPostEventAccess())
    except Exception:  # noqa: BLE001
        can_post = False
    try:
        can_listen = bool(Quartz.CGPreflightListenEventAccess())
    except Exception:  # noqa: BLE001
        can_listen = False
    return PermissionInfo(
        can_control_mouse=PermissionState.GRANTED if can_post else PermissionState.DENIED,
        can_listen_input=PermissionState.GRANTED if can_listen else PermissionState.DENIED,
        details="",
    )


def request_mouse_permission() -> None:
    """Показать системный запрос «Универсальный доступ» (добавляет приложение в список)."""
    try:
        Quartz.CGRequestPostEventAccess()
    except Exception:  # noqa: BLE001
        pass


def request_input_permission() -> None:
    """Показать системный запрос «Мониторинг ввода»."""
    try:
        Quartz.CGRequestListenEventAccess()
    except Exception:  # noqa: BLE001
        pass


SETTINGS_URLS = {
    "mouse": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "input": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
}


# --- сессия работы: не давать App Nap замедлять таймеры ----------------------

_activity = None


def begin_session() -> None:
    """Во время работы просим macOS не «усыплять» процесс (App Nap) и не уходить
    в сон по бездействию — иначе в свёрнутом окне паузы между кликами растягиваются.
    """
    global _activity
    try:
        options = Foundation.NSActivityUserInitiated | Foundation.NSActivityLatencyCritical
        _activity = Foundation.NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
            options, "AutoClicker: выполняются клики"
        )
    except Exception:  # noqa: BLE001
        _activity = None


def end_session() -> None:
    global _activity
    if _activity is not None:
        try:
            Foundation.NSProcessInfo.processInfo().endActivity_(_activity)
        except Exception:  # noqa: BLE001
            pass
        _activity = None
