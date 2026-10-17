"""Подставной адаптер мыши: только записывает вызовы, реальных кликов нет."""

from __future__ import annotations

import threading
import time

from autoclicker.model import MouseButton


class FakeAdapter:
    def __init__(self) -> None:
        self.events: list[tuple[str, object, float]] = []  # (действие, аргумент, время)
        self.lock = threading.Lock()
        self.position = (500, 500)
        self.corner = (0, 0, 5, 5)
        self.available = True
        self.fail_press_on: int | None = None  # номер нажатия (с 1), на котором press падает
        self.fail_position_after_press: int | None = None
        self.stall_press_on: int | None = None  # номер нажатия, на котором ОС «подвисает»
        self.stall_s = 0.0
        self.pressed: set[MouseButton] = set()
        self.press_count = 0
        self.press_event = threading.Event()

    def _log(self, kind: str, arg: object) -> None:
        with self.lock:
            self.events.append((kind, arg, time.monotonic()))

    def press(self, button: MouseButton) -> None:
        self.press_count += 1
        n = self.press_count
        if self.stall_press_on == n:
            time.sleep(self.stall_s)
        if self.fail_press_on == n:
            raise RuntimeError("сбой отправки события")
        self.pressed.add(button)
        self._log("down", button)
        self.press_event.set()

    def release(self, button: MouseButton) -> None:
        self.pressed.discard(button)
        self._log("up", button)

    def move_to(self, x: int, y: int) -> None:
        self._log("move", (x, y))
        self.position = (x, y)

    def get_position(self) -> tuple[int, int]:
        if self.fail_position_after_press is not None and self.press_count >= self.fail_position_after_press:
            raise RuntimeError("позиция недоступна")
        return self.position

    def corner_region(self) -> tuple[int, int, int, int]:
        return self.corner

    def point_available(self, x: int, y: int) -> bool:
        return self.available

    # --- помощники для проверок ---

    def kinds(self) -> list[str]:
        with self.lock:
            return [k for k, _a, _t in self.events if k in ("down", "up")]

    def times(self, kind: str) -> list[float]:
        with self.lock:
            return [t for k, _a, t in self.events if k == kind]

    def wait_presses(self, n: int, timeout: float = 5.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if len(self.times("down")) >= n:
                return True
            time.sleep(0.002)
        return False
