"""Перевод клавиатурных событий Qt в нормализованные события слушателя.

Используется, когда глобальный слушатель недоступен (например, на macOS ещё нет
разрешения «Мониторинг ввода»): назначение сочетания и Esc тогда работают, пока
окно AutoClicker активно.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from ..platform import IS_MAC
from ..platform.base import KeyEventKind, RawKeyEvent
from ..platform.keymaps import MAC_CODE_TO_NAME, WIN_VK_TO_NAME

Key = Qt.Key

_MODIFIER_KEYS = {
    Key.Key_Control,
    Key.Key_Shift,
    Key.Key_Alt,
    Key.Key_Meta,
    Key.Key_AltGr,
    Key.Key_CapsLock,
    Key.Key_Super_L,
    Key.Key_Super_R,
}

_QT_NAMED = {
    Key.Key_Escape: "ESC",
    Key.Key_Space: "SPACE",
    Key.Key_Return: "RETURN",
    Key.Key_Enter: "RETURN",
    Key.Key_Tab: "TAB",
    Key.Key_Delete: "DELETE",
    Key.Key_Backspace: "BACKSPACE",
    Key.Key_Left: "LEFT",
    Key.Key_Right: "RIGHT",
    Key.Key_Up: "UP",
    Key.Key_Down: "DOWN",
    Key.Key_Home: "HOME",
    Key.Key_End: "END",
    Key.Key_PageUp: "PAGEUP",
    Key.Key_PageDown: "PAGEDOWN",
}


def qt_key_name(qt_key: int, native_vk: int, *, is_mac: bool = IS_MAC) -> str:
    """Каноническое имя клавиши. Сначала по нативному коду (не зависит от раскладки),
    иначе по коду Qt."""
    if native_vk:
        table = MAC_CODE_TO_NAME if is_mac else WIN_VK_TO_NAME
        name = table.get(native_vk)
        if name:
            return name
    if Key.Key_A.value <= qt_key <= Key.Key_Z.value:
        return chr(ord("A") + qt_key - Key.Key_A.value)
    if Key.Key_0.value <= qt_key <= Key.Key_9.value:
        return chr(ord("0") + qt_key - Key.Key_0.value)
    if Key.Key_F1.value <= qt_key <= Key.Key_F24.value:
        return f"F{qt_key - Key.Key_F1.value + 1}"
    for k, name in _QT_NAMED.items():
        if k.value == qt_key:
            return name
    return f"KEY{native_vk or qt_key}"


def qt_modifiers(mods: Qt.KeyboardModifier, *, is_mac: bool = IS_MAC) -> frozenset[str]:
    """Модификаторы Qt → канонические имена.

    На macOS Qt по умолчанию меняет местами Control и Command:
    ControlModifier — это Command, MetaModifier — Control.
    """
    M = Qt.KeyboardModifier
    result = set()
    if mods & M.ShiftModifier:
        result.add("shift")
    if mods & M.AltModifier:
        result.add("alt")
    if is_mac:
        if mods & M.ControlModifier:
            result.add("meta")
        if mods & M.MetaModifier:
            result.add("ctrl")
    else:
        if mods & M.ControlModifier:
            result.add("ctrl")
        if mods & M.MetaModifier:
            result.add("meta")
    return frozenset(result)


def qt_event_to_raw(event: QKeyEvent) -> RawKeyEvent:
    kind = KeyEventKind.DOWN if event.type() == QEvent.Type.KeyPress else KeyEventKind.UP
    qt_key = event.key()
    if qt_key in _MODIFIER_KEYS:
        key = ""
    else:
        key = qt_key_name(int(qt_key), int(event.nativeVirtualKey()))
    return RawKeyEvent(
        kind=kind,
        key=key,
        modifiers=qt_modifiers(event.modifiers()),
        autorepeat=event.isAutoRepeat(),
    )
