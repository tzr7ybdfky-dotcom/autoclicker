"""Сохранение настроек в JSON-файле в стандартной папке настроек пользователя.

Каждое поле читается и проверяется отдельно: повреждённый файл, неверный тип или
значение вне диапазона заменяются значением по умолчанию только для этого поля и
не мешают запуску. Запись атомарная (временный файл + замена), чтобы сбой во время
записи не оставил полупустой файл. Никаких сетевых запросов и телеметрии.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import model as m
from .hotkeys import validate_hotkey
from .model import Hotkey, MouseButton, PositionMode, Settings, StopMode

FILE_NAME = "settings.json"
FORMAT_VERSION = 1


@dataclass
class Stored:
    settings: Settings = field(default_factory=Settings)
    window_geometry: str = ""  # QWidget.saveGeometry() в base64
    warnings: list[str] = field(default_factory=list)  # что пришлось сбросить при чтении


def _number(raw: Any, lo: float, hi: float, *, integer: bool) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if not math.isfinite(value) or not (lo <= value <= hi):
        return None
    if integer and not value.is_integer():
        return None
    return value


def _enum(raw: Any, enum_type):  # noqa: ANN001, ANN202
    try:
        return enum_type(raw)
    except (ValueError, TypeError):
        return None


def settings_to_dict(settings: Settings) -> dict:
    return {
        "interval_ms": settings.interval_ms,
        "hold_ms": settings.hold_ms,
        "button": settings.button.value,
        "position_mode": settings.position_mode.value,
        "fixed_x": settings.fixed_x,
        "fixed_y": settings.fixed_y,
        "stop_mode": settings.stop_mode.value,
        "stop_count": settings.stop_count,
        "stop_seconds": settings.stop_seconds,
        "start_delay_s": settings.start_delay_s,
        "toggle_hotkey": settings.toggle_hotkey.to_dict(),
    }


_COORD_LIMIT = 1_000_000  # координаты виртуального рабочего стола заведомо меньше


def settings_from_dict(data: Any, warnings: list[str] | None = None) -> Settings:
    """Собрать Settings из словаря, заменяя каждое негодное поле значением по умолчанию."""
    defaults = Settings()
    s = Settings()
    warn = warnings if warnings is not None else []
    if not isinstance(data, dict):
        warn.append("файл настроек имеет неверный формат")
        return s

    def take(name: str, parse: Callable[[Any], Any]) -> None:
        if name not in data:
            return
        value = parse(data[name])
        if value is None:
            warn.append(name)
            setattr(s, name, getattr(defaults, name))
        else:
            setattr(s, name, value)

    take("interval_ms", lambda v: _number(v, m.INTERVAL_MIN_MS, m.INTERVAL_MAX_MS, integer=False))
    take("hold_ms", lambda v: _intify(_number(v, m.HOLD_MIN_MS, m.HOLD_MAX_MS, integer=True)))
    take("button", lambda v: _enum(v, MouseButton))
    take("position_mode", lambda v: _enum(v, PositionMode))
    take("fixed_x", lambda v: _intify(_number(v, -_COORD_LIMIT, _COORD_LIMIT, integer=True)))
    take("fixed_y", lambda v: _intify(_number(v, -_COORD_LIMIT, _COORD_LIMIT, integer=True)))
    take("stop_mode", lambda v: _enum(v, StopMode))
    take("stop_count", lambda v: _intify(_number(v, m.COUNT_MIN, m.COUNT_MAX, integer=True)))
    take("stop_seconds", lambda v: _intify(_number(v, m.DURATION_MIN_S, m.DURATION_MAX_S, integer=True)))
    take(
        "start_delay_s",
        lambda v: _intify(_number(v, m.START_DELAY_MIN_S, m.START_DELAY_MAX_S, integer=True)),
    )

    def parse_hotkey(v: Any) -> Hotkey | None:
        if not isinstance(v, dict):
            return None
        hk = Hotkey.from_dict(v)
        return hk if validate_hotkey(hk) is None else None

    take("toggle_hotkey", parse_hotkey)

    # Несовместимая пара «нажатие ≥ интервал − 1» не исправляется молча на этапе
    # чтения: GUI покажет ошибку у поля и не даст запустить. Но если такое сочетание
    # пришло из повреждённого файла, безопаснее вернуть обе величины по умолчанию.
    if s.hold_ms > s.interval_ms - 1:
        warn.append("hold_ms")
        s.interval_ms = defaults.interval_ms
        s.hold_ms = defaults.hold_ms
    return s


def _intify(value: float | None) -> int | None:
    return None if value is None else int(value)


class SettingsStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.path = self.directory / FILE_NAME

    def load(self) -> Stored:
        stored = Stored()
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return stored
        except OSError as exc:
            stored.warnings.append(f"не удалось прочитать файл: {exc}")
            return stored
        try:
            data = json.loads(text)
        except (ValueError, UnicodeDecodeError):
            stored.warnings.append("файл настроек повреждён и будет перезаписан")
            return stored
        if not isinstance(data, dict):
            stored.warnings.append("файл настроек имеет неверный формат")
            return stored
        stored.settings = settings_from_dict(data.get("settings"), stored.warnings)
        geometry = data.get("window_geometry", "")
        if isinstance(geometry, str) and len(geometry) < 10_000:
            stored.window_geometry = geometry
        return stored

    def save(self, settings: Settings, window_geometry: str = "") -> None:
        """Атомарно записать настройки. Ошибку записи поднимает OSError."""
        payload = {
            "version": FORMAT_VERSION,
            "settings": settings_to_dict(settings),
            "window_geometry": window_geometry,
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
