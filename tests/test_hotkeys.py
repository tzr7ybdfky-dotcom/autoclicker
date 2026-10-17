from __future__ import annotations

import threading

from autoclicker.hotkeys import Action, HotkeyMatcher, validate_hotkey
from autoclicker.model import DEFAULT_TOGGLE_HOTKEY, Hotkey
from autoclicker.platform.base import KeyEventKind, RawKeyEvent
from autoclicker.platform.keymaps import format_hotkey

CA = frozenset({"ctrl", "alt"})


def down(key, mods=CA, repeat=False):
    return RawKeyEvent(KeyEventKind.DOWN, key, frozenset(mods), repeat)


def up(key, mods=CA):
    return RawKeyEvent(KeyEventKind.UP, key, frozenset(mods), False)


def actions(matcher, events):
    out = []
    for ev in events:
        r = matcher.feed(ev)
        if r is not None:
            out.append(r.action)
    return out


def test_default_hotkey_labels():
    assert DEFAULT_TOGGLE_HOTKEY == Hotkey(CA, "F8")
    assert format_hotkey(CA, "F8", "win32") == "Ctrl + Alt + F8"
    assert format_hotkey(CA, "F8", "darwin") == "Control + Option + F8"
    assert format_hotkey(frozenset({"meta", "shift"}), "K", "darwin") == "Shift + Command + K"


def test_toggle_fires_once_while_held_autorepeat_suppressed():
    m = HotkeyMatcher(DEFAULT_TOGGLE_HOTKEY)
    events = [
        down("F8"),
        down("F8", repeat=True),
        down("F8", repeat=True),
        down("F8"),  # повторный DOWN без флага автоповтора — тоже игнорируется
        up("F8"),
        down("F8"),  # после отпускания — снова срабатывает
        up("F8"),
    ]
    assert actions(m, events) == [Action.TOGGLE, Action.TOGGLE]


def test_modifiers_must_match_exactly():
    m = HotkeyMatcher(DEFAULT_TOGGLE_HOTKEY)
    assert actions(m, [down("F8", {"ctrl"}), up("F8", {"ctrl"})]) == []
    assert actions(m, [down("F8", {"ctrl", "alt", "shift"}), up("F8")]) == []
    assert actions(m, [down("F8", set()), up("F8", set())]) == []
    assert actions(m, [down("F7"), up("F7")]) == []
    assert actions(m, [down("F8"), up("F8")]) == [Action.TOGGLE]


def test_pure_modifier_events_do_nothing():
    m = HotkeyMatcher(DEFAULT_TOGGLE_HOTKEY)
    assert actions(m, [down("", {"ctrl"}), down("", CA), up("", {"ctrl"}), up("", set())]) == []


def test_escape_is_emergency_and_not_repeated():
    m = HotkeyMatcher(DEFAULT_TOGGLE_HOTKEY)
    evs = [down("ESC", set()), down("ESC", set(), repeat=True), down("ESC", set()), up("ESC", set()), down("ESC", {"shift"})]
    assert actions(m, evs) == [Action.ESCAPE, Action.ESCAPE]


def test_recording_mode_never_toggles_and_esc_cancels():
    m = HotkeyMatcher(DEFAULT_TOGGLE_HOTKEY)
    m.start_recording()
    assert actions(m, [down("ESC", set())]) == [Action.ESCAPE]
    assert not m.recording
    assert m.hotkey == DEFAULT_TOGGLE_HOTKEY  # сочетание не изменилось


def test_recording_new_combo_replaces_pattern_without_triggering():
    m = HotkeyMatcher(DEFAULT_TOGGLE_HOTKEY)
    m.start_recording()
    r = m.feed(down("F8"))  # старое сочетание во время назначения не запускает клики
    assert r.action is Action.RECORDED and r.hotkey == DEFAULT_TOGGLE_HOTKEY
    m.start_recording()
    r = m.feed(down("K", {"ctrl", "shift"}))
    assert r.action is Action.RECORDED and r.hotkey == Hotkey(frozenset({"ctrl", "shift"}), "K")
    assert not m.recording
    # Только что записанное сочетание ещё удерживается — не срабатывает.
    assert actions(m, [down("K", {"ctrl", "shift"}, repeat=True), down("K", {"ctrl", "shift"})]) == []
    assert actions(m, [up("K", {"ctrl", "shift"})]) == []
    # Старое сочетание больше не работает, новое — работает (обработчик один).
    assert actions(m, [down("F8"), up("F8")]) == []
    assert actions(m, [down("K", {"ctrl", "shift"}), up("K")]) == [Action.TOGGLE]


def test_recording_invalid_combo_keeps_recording():
    m = HotkeyMatcher(DEFAULT_TOGGLE_HOTKEY)
    m.start_recording()
    r = m.feed(down("A", set()))
    assert r.action is Action.RECORDED and validate_hotkey(r.hotkey) is not None
    assert m.recording
    assert m.hotkey == DEFAULT_TOGGLE_HOTKEY


def test_set_hotkey_from_gui_thread_is_atomic():
    m = HotkeyMatcher(DEFAULT_TOGGLE_HOTKEY)
    new = Hotkey(frozenset({"alt"}), "F9")
    results = []

    def feeder():
        for _ in range(2000):
            r = m.feed(down("F9", {"alt"}))
            m.feed(up("F9", {"alt"}))
            if r is not None:
                results.append(r.action)

    t = threading.Thread(target=feeder)
    t.start()
    m.set_hotkey(new)
    t.join()
    assert m.hotkey == new
    assert all(a is Action.TOGGLE for a in results)


def test_validate_hotkey_rules():
    assert validate_hotkey(Hotkey(frozenset(), "ESC")) is not None
    assert validate_hotkey(Hotkey(CA, "ESC")) is not None  # Esc нельзя даже с модификаторами
    assert validate_hotkey(Hotkey(CA, "")) is not None  # только модификаторы
    assert validate_hotkey(Hotkey(frozenset(), "A")) is not None
    assert validate_hotkey(Hotkey(frozenset(), "F9")) is None
    assert validate_hotkey(Hotkey(frozenset({"meta"}), "1")) is None
    assert validate_hotkey(Hotkey(CA, "KEY200")) is not None
    assert validate_hotkey(DEFAULT_TOGGLE_HOTKEY) is None


def test_qt_bridge_delivers_signals_in_gui_thread(qapp):
    from PySide6.QtCore import QThread

    from autoclicker.hotkeys import qt_bridge_class

    bridge = qt_bridge_class()(HotkeyMatcher(DEFAULT_TOGGLE_HOTKEY))
    got: list[tuple[str, bool]] = []
    main = QThread.currentThread()
    bridge.toggle.connect(lambda: got.append(("toggle", QThread.currentThread() is main)))
    bridge.escape.connect(lambda: got.append(("escape", QThread.currentThread() is main)))

    def listener_thread():
        bridge.on_raw_event(down("F8"))
        bridge.on_raw_event(up("F8"))
        bridge.on_raw_event(down("ESC", set()))

    t = threading.Thread(target=listener_thread)
    t.start()
    t.join()
    assert got == []  # обработчики не вызываются в потоке слушателя
    for _ in range(20):
        qapp.processEvents()
    assert got == [("toggle", True), ("escape", True)]
