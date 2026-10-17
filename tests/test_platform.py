"""Проверки платформенного кода, не отправляющие событий ввода."""

from __future__ import annotations

import ctypes
import sys

import pytest

from autoclicker.platform import windows as win
from autoclicker.platform.keymaps import MAC_CODE_TO_NAME, WIN_VK_MODIFIERS, WIN_VK_TO_NAME


def test_windows_structs_match_x64_layout():
    # Раскладка Windows x64 (её ждёт SendInput в cbSize).
    assert ctypes.sizeof(win.MOUSEINPUT) == 32
    assert ctypes.sizeof(win.KEYBDINPUT) == 24
    assert ctypes.sizeof(win.INPUT) == 40
    assert win.INPUT.u.offset == 8
    assert ctypes.sizeof(win.KBDLLHOOKSTRUCT) == 24
    assert ctypes.sizeof(win.MSG) == 48
    assert ctypes.sizeof(win.POINT) == 8
    assert ctypes.sizeof(win.PROCESS_POWER_THROTTLING_STATE) == 12


def test_windows_mouse_flags():
    from autoclicker.model import MouseButton

    assert win.MOUSE_FLAGS[(MouseButton.LEFT, True)] == 0x0002
    assert win.MOUSE_FLAGS[(MouseButton.LEFT, False)] == 0x0004
    assert win.MOUSE_FLAGS[(MouseButton.RIGHT, True)] == 0x0008
    assert win.MOUSE_FLAGS[(MouseButton.MIDDLE, False)] == 0x0040


def test_windows_modifier_state_drops_stuck_keys():
    # Отслеженный Ctrl, который система уже не считает нажатым, не учитывается.
    down = {0xA4}  # нажат только левый Alt
    mods = win.modifiers_from_state({"ctrl", "alt"}, lambda vk: vk in down)
    assert mods == frozenset({"alt"})


def test_key_tables_consistent():
    assert WIN_VK_TO_NAME[0x77] == "F8" and WIN_VK_TO_NAME[0x1B] == "ESC"
    assert MAC_CODE_TO_NAME[100] == "F8" and MAC_CODE_TO_NAME[53] == "ESC"
    assert not set(WIN_VK_MODIFIERS) & set(WIN_VK_TO_NAME)
    # Одинаковые имена клавиш на обеих платформах — настройки переносимы.
    assert set(MAC_CODE_TO_NAME.values()) <= set(WIN_VK_TO_NAME.values())


def test_qt_key_conversion_fallback_and_mac_modifier_swap(qapp):
    from PySide6.QtCore import Qt

    from autoclicker.gui.keys import qt_key_name, qt_modifiers

    K = Qt.Key
    assert qt_key_name(K.Key_F8.value, 0) == "F8"
    assert qt_key_name(K.Key_K.value, 0) == "K"
    assert qt_key_name(K.Key_Escape.value, 0) == "ESC"
    assert qt_key_name(0, 100, is_mac=True) == "F8"
    assert qt_key_name(0, 0x77, is_mac=False) == "F8"
    M = Qt.KeyboardModifier
    # На macOS Qt меняет местами Control и Command.
    assert qt_modifiers(M.ControlModifier | M.AltModifier, is_mac=True) == frozenset({"meta", "alt"})
    assert qt_modifiers(M.MetaModifier, is_mac=True) == frozenset({"ctrl"})
    assert qt_modifiers(M.ControlModifier | M.MetaModifier, is_mac=False) == frozenset({"ctrl", "meta"})


@pytest.mark.skipif(sys.platform != "darwin", reason="только macOS")
def test_mac_adapter_read_only_queries():
    from autoclicker.platform.macos import MacMouseAdapter, flags_to_modifiers

    import Quartz

    a = MacMouseAdapter()
    x, y = a.get_position()
    assert isinstance(x, int) and isinstance(y, int)
    assert a.corner_region() == (0, 0, 5, 5)
    assert a.point_available(x, y)
    assert not a.point_available(-10**6, -10**6)
    flags = Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskAlternate
    assert flags_to_modifiers(flags) == frozenset({"ctrl", "alt"})
