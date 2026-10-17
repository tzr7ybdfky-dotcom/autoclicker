"""Окно в offscreen-режиме с подставным адаптером (без реальных кликов)."""

from __future__ import annotations

import time

import pytest

from autoclicker import platform as plat
from autoclicker.engine import StopReason
from autoclicker.model import Hotkey, Settings
from autoclicker.platform.base import KeyEventKind, PermissionInfo, PermissionState, RawKeyEvent
from autoclicker.storage import SettingsStore, Stored

from .fakes import FakeAdapter

GRANTED = PermissionInfo(PermissionState.GRANTED, PermissionState.GRANTED, "")


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    from autoclicker.gui.main_window import MainWindow

    monkeypatch.setattr(plat, "check_permissions", lambda: GRANTED)
    monkeypatch.setattr(plat, "begin_session", lambda: None)
    monkeypatch.setattr(plat, "end_session", lambda: None)
    adapter = FakeAdapter()
    w = MainWindow(adapter, None, SettingsStore(tmp_path), Stored())
    w.fake = adapter
    yield w
    w.close()


def pump(qapp, until, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if until():
            return True
        time.sleep(0.005)
    return False


def type_into(field, text):
    field.edit.setText(text)
    field.edit.textEdited.emit(text)


def test_defaults_summary_and_no_autostart(window):
    assert not window.engine.is_active()
    assert window.status_pill.text() == "Остановлен"
    assert window.summary.text() == "Левая кнопка · 10 кликов/с · удержание 20 мс · текущая позиция"
    assert window.interval_field.text() == "100"
    assert window.cps_field.text() == "10"
    assert window.hold_field.text() == "20"
    assert window.delay_field.text() == "3"
    assert window.start_button.isEnabled()


def test_cps_to_interval_is_exact_and_not_cyclic(window):
    type_into(window.cps_field, "3")
    assert window.settings.interval_ms == 1000 / 3
    assert window.interval_field.text() == "333,333"
    assert window.cps_field.text() == "3"  # частота не переписана обратно из округлённого интервала
    type_into(window.interval_field, "40")
    assert window.cps_field.text() == "25"
    window.preset_buttons[50].click()
    assert window.settings.interval_ms == 20
    assert window.preset_buttons[50].isChecked()


def test_incompatible_values_block_start_with_message(window):
    type_into(window.hold_field, "100")
    assert window.is_start_blocked()
    assert window.hold_row.error.isVisibleTo(window)
    assert "короче интервала" in window.hold_row.error.text()
    assert window.settings.hold_ms == 100  # значение не исправлено молча
    type_into(window.cps_field, "250")
    assert "от 0,016667 до 100" in window.cps_row.error.text()
    type_into(window.hold_field, "20")
    assert window.is_start_blocked()  # частота всё ещё неверна
    type_into(window.cps_field, "20")
    assert not window.is_start_blocked()


def test_start_runs_engine_and_returns_to_stopped(window, qapp):
    type_into(window.delay_field, "0")
    window.stop_seg.buttons["count"].click()
    type_into(window.count_field, "3")
    window.start_button.click()
    assert window.engine.is_active() or window.engine.clicks == 3
    window._try_start()  # повторный старт не создаёт второй поток
    assert pump(qapp, lambda: not window._ui_running)
    assert window.engine.clicks == 3
    assert window.fake.kinds() == ["down", "up"] * 3
    assert window.status_pill.text() == "Остановлен"
    assert "заданное число" in window.info.text()
    assert window.settings_box.isEnabled()


def test_settings_locked_and_stop_available_while_running(window, qapp):
    type_into(window.delay_field, "5")
    window.start_button.click()
    assert pump(qapp, lambda: window.status_pill.text() == "Ожидание старта")
    assert not window.settings_box.isEnabled()
    assert window.start_button.isEnabled() and window.start_button.text() == "Стоп"
    assert "Старт через" in window.info.text()
    window.start_button.click()
    assert pump(qapp, lambda: not window._ui_running)
    assert window.engine.stop_reason is StopReason.MANUAL
    assert window.fake.events == []
    assert "отменён" in window.info.text()


def test_escape_from_listener_stops(window, qapp):
    type_into(window.delay_field, "0")
    window.settings.interval_ms = 60_000
    window.start_button.click()
    assert window.fake.wait_presses(1)
    window._bridge.on_raw_event(RawKeyEvent(KeyEventKind.DOWN, "ESC", frozenset(), False))
    assert pump(qapp, lambda: not window._ui_running)
    assert window.engine.stop_reason is StopReason.ESCAPE
    assert not window.fake.pressed


def test_recording_hotkey_blocks_start_and_toggle(window, qapp):
    window.assign_button.click()
    assert window._recording and window.is_start_blocked()
    # Старое сочетание во время назначения не запускает автокликер.
    window._bridge.on_raw_event(RawKeyEvent(KeyEventKind.DOWN, "F8", frozenset({"ctrl", "alt"}), False))
    qapp.processEvents()
    assert not window.engine.is_active()
    assert window._recording is False  # сочетание записано (то же самое)
    window.assign_button.click()
    window._bridge.on_raw_event(RawKeyEvent(KeyEventKind.DOWN, "ESC", frozenset(), False))
    qapp.processEvents()
    assert not window._recording
    assert window.settings.toggle_hotkey == Hotkey(frozenset({"ctrl", "alt"}), "F8")

    window.assign_button.click()
    window._bridge.on_raw_event(RawKeyEvent(KeyEventKind.DOWN, "J", frozenset({"alt", "shift"}), False))
    qapp.processEvents()
    assert window.settings.toggle_hotkey == Hotkey(frozenset({"alt", "shift"}), "J")
    assert not window.engine.is_active()  # удерживаемое новое сочетание не стартует
    window._bridge.on_raw_event(RawKeyEvent(KeyEventKind.UP, "J", frozenset({"alt", "shift"}), False))
    window._bridge.on_raw_event(RawKeyEvent(KeyEventKind.DOWN, "J", frozenset({"alt", "shift"}), False))
    assert pump(qapp, lambda: window._ui_running)
    window._bridge.on_raw_event(RawKeyEvent(KeyEventKind.UP, "J", frozenset({"alt", "shift"}), False))
    window._bridge.on_raw_event(RawKeyEvent(KeyEventKind.DOWN, "J", frozenset({"alt", "shift"}), False))
    assert pump(qapp, lambda: not window._ui_running)
    assert window.engine.stop_reason is StopReason.HOTKEY


def test_fixed_point_in_corner_and_offscreen(window, qapp):
    window.pos_fixed.setChecked(True)
    type_into(window.x_field, "2")
    type_into(window.y_field, "2")
    assert window.is_start_blocked()
    assert "защитном углу" in window.coords_error.text()
    type_into(window.x_field, "-1500")
    assert not window.is_start_blocked()
    window.fake.available = False  # монитор отключён
    window.start_button.click()
    assert not window.engine.is_active()
    assert "монитор" in window.coords_error.text()


def test_pick_point_uses_cursor_without_click(window, qapp, monkeypatch):
    import autoclicker.gui.main_window as mw

    monkeypatch.setattr(mw, "PICK_SECONDS", 1)
    window._pick_timer.setInterval(10)
    window.pos_fixed.setChecked(True)
    window.fake.position = (-800, 1300)
    window.pick_button.click()
    assert window.is_start_blocked()
    assert pump(qapp, lambda: not window._picking)
    assert window.settings.fixed_x == -800 and window.settings.fixed_y == 1300
    assert window.fake.events == []  # никаких кликов

    window._pick_timer.setInterval(10_000)
    window.pick_button.click()
    window._bridge.on_raw_event(RawKeyEvent(KeyEventKind.DOWN, "ESC", frozenset(), False))
    assert pump(qapp, lambda: not window._picking)
    assert "отменён" in window.info.text()


def test_permission_missing_blocks_start_on_mac(window, qapp, monkeypatch):
    if not plat.IS_MAC:
        pytest.skip("только macOS")
    denied = PermissionInfo(PermissionState.DENIED, PermissionState.DENIED, "")
    monkeypatch.setattr(plat, "check_permissions", lambda: denied)
    type_into(window.delay_field, "0")
    window.start_button.click()
    assert not window.engine.is_active()
    assert window.status_pill.text() == "Нет разрешений"
    assert "Универсальный доступ" in window.info.text()


def test_settings_saved_on_close(qapp, tmp_path, monkeypatch):
    from autoclicker.gui.main_window import MainWindow

    monkeypatch.setattr(plat, "check_permissions", lambda: GRANTED)
    store = SettingsStore(tmp_path)
    w = MainWindow(FakeAdapter(), None, store, Stored(Settings()))
    type_into(w.cps_field, "4")
    w.button_seg.buttons["right"].click()
    w.close()
    loaded = store.load()
    assert loaded.settings.interval_ms == 250
    assert loaded.settings.button.value == "right"
    assert loaded.window_geometry


def test_fallback_keys_in_window_when_listener_unavailable(window, qapp):
    """Без глобального слушателя назначение и Esc работают внутри активного окна."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from autoclicker.gui.keys import qt_modifiers

    mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    window.assign_button.click()
    QTest.keyClick(window.keycap, Qt.Key.Key_K, mods)
    qapp.processEvents()
    assert window.settings.toggle_hotkey == Hotkey(qt_modifiers(mods), "K")

    window.assign_button.click()
    QTest.keyClick(window.assign_button, Qt.Key.Key_Space)  # пробел не «нажимает» кнопку «Отмена»
    qapp.processEvents()
    assert window._recording  # без модификатора — ошибка, назначение продолжается
    assert window.hotkey_error.isVisibleTo(window)
    QTest.keyClick(window.keycap, Qt.Key.Key_Escape)
    qapp.processEvents()
    assert not window._recording

    type_into(window.delay_field, "10")
    window.start_button.click()
    assert window.engine.is_active()
    QTest.keyClick(window.keycap, Qt.Key.Key_Escape)
    assert pump(qapp, lambda: not window._ui_running)
    assert window.engine.stop_reason is StopReason.ESCAPE
