"""Глобальные горячие клавиши: проверка сочетаний, сопоставление событий и мост в Qt.

Слушатель платформы (platform/*) только наблюдает за клавиатурой и не мешает
клавишам доходить до активного приложения. Здесь — чистая логика:

• одно сочетание-переключатель «Старт/Стоп» срабатывает на нажатие основной
  клавиши при точном совпадении модификаторов; автоповтор удержания игнорируется,
  повторное срабатывание — только после отпускания основной клавиши;
• Esc — аварийная остановка (сообщается всегда, решение принимает GUI);
• режим назначения: следующее сочетание записывается, переключатель не срабатывает,
  Esc отменяет назначение. Новое сочетание применяется атомарно — обработчик один,
  меняется только образец для сравнения.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum

from .model import MODIFIERS, Hotkey
from .platform.base import KeyEventKind, RawKeyEvent

ESC = "ESC"
FUNCTION_KEYS = frozenset(f"F{i}" for i in range(1, 25))


def validate_hotkey(hotkey: Hotkey) -> str | None:
    """Текст ошибки или None, если сочетание можно назначить."""
    if hotkey.is_empty():
        return "Нажмите основную клавишу вместе с модификаторами."
    if hotkey.key == ESC:
        return "Esc зарезервирован для аварийной остановки и не может быть назначен."
    if any(m not in MODIFIERS for m in hotkey.modifiers):
        return "Неизвестный модификатор."
    if not hotkey.modifiers and hotkey.key not in FUNCTION_KEYS:
        return (
            "Без модификаторов можно назначить только F1–F24. "
            "Добавьте Ctrl/Control, Alt/Option, Shift или Win/Command."
        )
    if hotkey.key.startswith(("KEY", "VK")):
        return "Эта клавиша не поддерживается. Выберите букву, цифру или F1–F24."
    return None


class Action(str, Enum):
    TOGGLE = "toggle"  # сочетание-переключатель
    ESCAPE = "escape"  # аварийная остановка / отмена
    RECORDED = "recorded"  # в режиме назначения записано сочетание


@dataclass
class MatchResult:
    action: Action
    hotkey: Hotkey | None = None


class HotkeyMatcher:
    """Потокобезопасный разбор событий. Вызывается из потока слушателя."""

    def __init__(self, hotkey: Hotkey) -> None:
        self._lock = threading.Lock()
        self._hotkey = hotkey
        self._latched = False  # переключатель сработал, ждём отпускания основной клавиши
        self._recording = False
        self._esc_down = False

    @property
    def hotkey(self) -> Hotkey:
        return self._hotkey

    @property
    def recording(self) -> bool:
        return self._recording

    def set_hotkey(self, hotkey: Hotkey) -> None:
        with self._lock:
            self._hotkey = hotkey
            self._latched = False

    def start_recording(self) -> None:
        with self._lock:
            self._recording = True

    def cancel_recording(self) -> None:
        with self._lock:
            self._recording = False

    def feed(self, event: RawKeyEvent) -> MatchResult | None:
        with self._lock:
            key = event.key
            if key == ESC:
                if event.kind is KeyEventKind.UP:
                    self._esc_down = False
                    return None
                if event.autorepeat or self._esc_down:
                    return None
                self._esc_down = True
                self._recording = False  # Esc всегда отменяет назначение
                return MatchResult(Action.ESCAPE)

            if not key:
                return None  # чистый модификатор: только меняет состояние

            if event.kind is KeyEventKind.UP:
                if key == self._hotkey.key:
                    self._latched = False
                return None

            if event.autorepeat:
                return None

            if self._recording:
                recorded = Hotkey(modifiers=frozenset(event.modifiers), key=key)
                if validate_hotkey(recorded) is not None:
                    # Неподходящее сочетание сообщаем GUI, режим не выходит.
                    return MatchResult(Action.RECORDED, recorded)
                self._recording = False
                self._hotkey = recorded
                # Только что записанное сочетание ещё удерживается: без защёлки
                # оно бы сразу сработало как «Старт».
                self._latched = True
                return MatchResult(Action.RECORDED, recorded)

            hk = self._hotkey
            if hk.is_empty() or key != hk.key or frozenset(event.modifiers) != hk.modifiers:
                return None
            if self._latched:
                # Повторный DOWN без UP: автоповтор, у которого платформа не выставила флаг.
                return None
            self._latched = True
            return MatchResult(Action.TOGGLE)


def qt_bridge_class():  # noqa: ANN201
    """Класс-мост в Qt. Создаётся лениво, чтобы логика выше тестировалась без Qt."""
    from PySide6.QtCore import QObject, Signal

    class HotkeyBridge(QObject):
        """Переносит события из потока слушателя в GUI-поток.

        Сигналы испускаются в потоке слушателя; так как объект живёт в GUI-потоке,
        Qt доставляет их через очередь событий (AutoConnection → Queued). Обработчики
        клавиатуры никогда не трогают виджеты напрямую.
        """

        toggle = Signal()
        escape = Signal()
        recorded = Signal(object)  # Hotkey

        def __init__(self, matcher: HotkeyMatcher) -> None:
            super().__init__()
            self._matcher = matcher

        def on_raw_event(self, event: RawKeyEvent) -> None:
            result = self._matcher.feed(event)
            if result is None:
                return
            if result.action is Action.TOGGLE:
                self.toggle.emit()
            elif result.action is Action.ESCAPE:
                self.escape.emit()
            elif result.action is Action.RECORDED:
                self.recorded.emit(result.hotkey)

    return HotkeyBridge
