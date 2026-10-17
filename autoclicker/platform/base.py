"""Платформенно-независимые протоколы адаптеров и модель разрешений."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from ..model import MouseButton


class PermissionState(str, Enum):
    GRANTED = "granted"  # разрешение есть
    DENIED = "denied"  # разрешения нет
    UNKNOWN = "unknown"  # система не позволяет узнать точно


@dataclass
class PermissionInfo:
    can_control_mouse: PermissionState
    can_listen_input: PermissionState
    details: str  # пояснение для пользователя (куда идти в настройках)


class MouseAdapter(Protocol):
    def press(self, button: MouseButton) -> None: ...
    def release(self, button: MouseButton) -> None: ...
    def move_to(self, x: int, y: int) -> None: ...
    def get_position(self) -> tuple[int, int]: ...
    def corner_region(self) -> tuple[int, int, int, int]: ...
    def point_available(self, x: int, y: int) -> bool: ...


class KeyEventKind(str, Enum):
    DOWN = "down"
    UP = "up"


@dataclass
class RawKeyEvent:
    """Нормализованное событие клавиши от платформенного слушателя."""

    kind: KeyEventKind
    key: str  # каноническое имя клавиши ("F8", "A", "ESC", "") или "" для чистого модификатора
    modifiers: frozenset[str]  # активные модификаторы в момент события
    autorepeat: bool  # True, если это автоповтор удержания


class KeyListener(Protocol):
    """Глобальный слушатель клавиатуры. Не подавляет передачу клавиш приложениям."""

    def start(self, callback: Callable[[RawKeyEvent], None]) -> None: ...
    def wait_ready(self, timeout: float) -> bool: ...
    def stop(self) -> None: ...
    @property
    def available(self) -> bool: ...
    @property
    def error(self) -> str: ...
