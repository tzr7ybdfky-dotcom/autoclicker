"""Таблицы клавиш для macOS (CGKeyCode) и Windows (виртуальные коды).

Канонические имена клавиш переносимы между платформами и сохраняются в настройках.
"""

from __future__ import annotations

# --- macOS: CGKeyCode -> каноническое имя ------------------------------------

MAC_CODE_TO_NAME: dict[int, str] = {
    0: "A", 11: "B", 8: "C", 2: "D", 14: "E", 3: "F", 5: "G", 4: "H",
    34: "I", 38: "J", 40: "K", 37: "L", 46: "M", 45: "N", 31: "O", 35: "P",
    12: "Q", 15: "R", 1: "S", 17: "T", 32: "U", 9: "V", 13: "W", 7: "X",
    16: "Y", 6: "Z",
    29: "0", 18: "1", 19: "2", 20: "3", 21: "4", 23: "5", 22: "6", 26: "7",
    28: "8", 25: "9",
    122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5", 97: "F6", 98: "F7",
    100: "F8", 101: "F9", 109: "F10", 103: "F11", 111: "F12", 105: "F13",
    107: "F14", 113: "F15", 106: "F16", 64: "F17", 79: "F18", 80: "F19", 90: "F20",
    49: "SPACE", 36: "RETURN", 48: "TAB", 51: "DELETE", 53: "ESC",
    123: "LEFT", 124: "RIGHT", 125: "DOWN", 126: "UP",
    115: "HOME", 119: "END", 116: "PAGEUP", 121: "PAGEDOWN",
    50: "`", 27: "-", 24: "=", 33: "[", 30: "]", 42: "\\",
    41: ";", 39: "'", 43: ",", 47: ".", 44: "/",
}

MAC_MODIFIER_CODES: dict[int, str] = {
    # left/right варианты
    59: "ctrl", 62: "ctrl",
    58: "alt", 61: "alt",
    56: "shift", 60: "shift",
    55: "meta", 54: "meta",  # Command
}


# --- Windows: виртуальный код (VK) -> каноническое имя -----------------------

WIN_VK_TO_NAME: dict[int, str] = {
    **{0x41 + i: chr(ord("A") + i) for i in range(26)},  # A..Z
    **{0x30 + i: str(i) for i in range(10)},  # 0..9
    **{0x70 + i: f"F{i + 1}" for i in range(24)},  # F1..F24
    0x20: "SPACE", 0x0D: "RETURN", 0x09: "TAB", 0x2E: "DELETE", 0x08: "BACKSPACE",
    0x1B: "ESC",
    0x25: "LEFT", 0x27: "RIGHT", 0x28: "DOWN", 0x26: "UP",
    0x24: "HOME", 0x23: "END", 0x21: "PAGEUP", 0x22: "PAGEDOWN",
    0xC0: "`", 0xBD: "-", 0xBB: "=", 0xDB: "[", 0xDD: "]", 0xDC: "\\",
    0xBA: ";", 0xDE: "'", 0xBC: ",", 0xBE: ".", 0xBF: "/",
}

# VK модификаторов -> канон (включая left/right)
WIN_VK_MODIFIERS: dict[int, str] = {
    0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
    0x12: "alt", 0xA4: "alt", 0xA5: "alt",
    0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    0x5B: "meta", 0x5C: "meta",  # Win
}


# --- человекочитаемые имена модификаторов ------------------------------------

def modifier_label(mod: str, platform: str) -> str:
    if platform == "darwin":
        return {"ctrl": "Control", "alt": "Option", "shift": "Shift", "meta": "Command"}.get(mod, mod)
    return {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "meta": "Win"}.get(mod, mod)


def format_hotkey(modifiers: frozenset[str], key: str, platform: str) -> str:
    if not key:
        return "—"
    order = ["ctrl", "alt", "shift", "meta"]
    parts = [modifier_label(m, platform) for m in order if m in modifiers]
    parts.append(key)
    return " + ".join(parts)
