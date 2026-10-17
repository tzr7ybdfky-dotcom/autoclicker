from __future__ import annotations

import json

from autoclicker.model import Hotkey, MouseButton, PositionMode, Settings, StopMode
from autoclicker.storage import FILE_NAME, SettingsStore


def test_roundtrip(tmp_path):
    store = SettingsStore(tmp_path / "cfg")
    s = Settings(
        interval_ms=1000 / 3,
        hold_ms=50,
        button=MouseButton.MIDDLE,
        position_mode=PositionMode.FIXED,
        fixed_x=-1920,
        fixed_y=-200,
        stop_mode=StopMode.TIME,
        stop_count=42,
        stop_seconds=3725,
        start_delay_s=0,
        toggle_hotkey=Hotkey(frozenset({"meta", "shift"}), "K"),
    )
    store.save(s, "Z2VvbWV0cnk=")
    loaded = store.load()
    assert loaded.settings == s
    assert loaded.settings.interval_ms == 1000 / 3  # точность сохранена
    assert loaded.window_geometry == "Z2VvbWV0cnk="
    assert loaded.warnings == []
    assert [p.name for p in (tmp_path / "cfg").iterdir()] == [FILE_NAME]  # без временных файлов


def test_missing_file_gives_defaults(tmp_path):
    loaded = SettingsStore(tmp_path).load()
    assert loaded.settings == Settings()
    assert loaded.warnings == []


def test_corrupted_json_does_not_break_start(tmp_path):
    (tmp_path / FILE_NAME).write_bytes(b"\x00{not json")
    loaded = SettingsStore(tmp_path).load()
    assert loaded.settings == Settings()
    assert loaded.warnings


def test_bad_fields_fall_back_individually(tmp_path):
    data = {
        "settings": {
            "interval_ms": "fast",
            "hold_ms": 30,
            "button": "laser",
            "position_mode": "fixed",
            "fixed_x": 12.5,
            "fixed_y": 40,
            "stop_mode": "count",
            "stop_count": 10_000_000,
            "stop_seconds": True,
            "start_delay_s": 5,
            "toggle_hotkey": {"modifiers": [], "key": "ESC"},
        },
        "window_geometry": 123,
    }
    (tmp_path / FILE_NAME).write_text(json.dumps(data), encoding="utf-8")
    loaded = SettingsStore(tmp_path).load()
    s, d = loaded.settings, Settings()
    assert s.interval_ms == d.interval_ms
    assert s.hold_ms == 30
    assert s.button == d.button
    assert s.position_mode is PositionMode.FIXED
    assert s.fixed_x == d.fixed_x and s.fixed_y == 40
    assert s.stop_mode is StopMode.COUNT and s.stop_count == d.stop_count
    assert s.stop_seconds == d.stop_seconds
    assert s.start_delay_s == 5
    assert s.toggle_hotkey == d.toggle_hotkey  # Esc назначить нельзя
    assert loaded.window_geometry == ""
    assert set(loaded.warnings) >= {"interval_ms", "button", "fixed_x", "stop_count", "stop_seconds", "toggle_hotkey"}


def test_incompatible_hold_from_file_is_reset(tmp_path):
    data = {"settings": {"interval_ms": 50, "hold_ms": 50}}
    (tmp_path / FILE_NAME).write_text(json.dumps(data), encoding="utf-8")
    loaded = SettingsStore(tmp_path).load()
    assert loaded.settings.interval_ms == 100 and loaded.settings.hold_ms == 20
    assert "hold_ms" in loaded.warnings


def test_wrong_top_level_type(tmp_path):
    (tmp_path / FILE_NAME).write_text("[1, 2, 3]", encoding="utf-8")
    assert SettingsStore(tmp_path).load().settings == Settings()
