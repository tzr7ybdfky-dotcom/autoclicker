"""Движок кликов.

Работает в отдельном потоке (не в GUI-потоке). Клики планируются по времени
начала нажатий, поэтому длительность удержания не прибавляется к интервалу.
Все ожидания прерываемы (Event.wait короткими порциями, без busy-wait): остановка
сразу будит задержку старта, ожидание интервала и удержание кнопки. Отпускание
нажатой приложением кнопки гарантируется через try/finally при любой остановке,
ошибке или закрытии.
"""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Callable, Protocol

from .model import MouseButton, PositionMode, Settings, StopMode


class State(str, Enum):
    STOPPED = "stopped"
    WAITING = "waiting"
    RUNNING = "running"
    ERROR = "error"


class StopReason(str, Enum):
    MANUAL = "manual"  # кнопка «Стоп»
    HOTKEY = "hotkey"  # сочетание-переключатель
    ESCAPE = "escape"  # аварийная остановка Esc
    CORNER = "corner"  # курсор в защитном углу
    COUNT = "count"  # выполнено N кликов
    TIME = "time"  # истекло заданное время
    CLOSING = "closing"  # закрытие приложения
    ERROR = "error"  # ошибка


class MouseAdapter(Protocol):
    """Платформенный адаптер. Координаты — в системе адаптера (см. platform/)."""

    def press(self, button: MouseButton) -> None: ...
    def release(self, button: MouseButton) -> None: ...
    def move_to(self, x: int, y: int) -> None: ...
    def get_position(self) -> tuple[int, int]: ...
    def corner_region(self) -> tuple[int, int, int, int]: ...
    def point_available(self, x: int, y: int) -> bool: ...


# --- чистые функции планирования (покрыты тестами) ---------------------------


def next_slot_index(t0: float, now: float, interval_s: float, last_k: int) -> int:
    """Индекс следующего слота нажатия (время слота k = t0 + k·интервал).

    Обычно это ``last_k + 1``. Если ОС задержала выполнение и этот слот уже
    в прошлом, все просроченные слоты пропускаются разом: возвращается первый
    слот строго после ``now``. Очереди «догоняющих» кликов не бывает.
    """
    k = last_k + 1
    if t0 + k * interval_s <= now:
        k = int((now - t0) / interval_s) + 1
        while t0 + k * interval_s <= now:  # защита от погрешности деления
            k += 1
    return k


def in_region(x: float, y: float, region: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = region
    return x0 <= x < x1 and y0 <= y < y1


class PointUnavailableError(RuntimeError):
    """Фиксированная точка не лежит ни на одном подключённом мониторе."""


# Результат прерываемого ожидания.
_DONE = "done"
_STOP = "stop"
_CORNER = "corner"
_TIME = "time"


class ClickEngine:
    """Потокобезопасный движок. Повторный ``start`` во время работы игнорируется.

    GUI не трогается из рабочего потока: состояние и счётчики читаются как
    простые атрибуты (``state``, ``clicks``, ``elapsed()``…), а о завершении
    движок сообщает через ``on_finished`` — его GUI превращает в Qt-сигнал.
    """

    def __init__(
        self,
        adapter: MouseAdapter,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        on_finished: Callable[[], None] | None = None,
        on_session_start: Callable[[], None] | None = None,
        on_session_end: Callable[[], None] | None = None,
        poll_s: float = 0.02,
    ) -> None:
        self._adapter = adapter
        self._mono = monotonic
        self._on_finished = on_finished
        self._on_session_start = on_session_start
        self._on_session_end = on_session_end
        self._poll_s = poll_s

        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._settings: Settings | None = None

        self._state = State.STOPPED
        self._clicks = 0
        self._skipped = 0
        self._run_start: float | None = None
        self._run_end: float | None = None
        self._countdown_end: float | None = None
        self._stop_reason: StopReason | None = None
        self._error = ""
        self._held: MouseButton | None = None
        self._held_lock = threading.Lock()
        self._corner: tuple[int, int, int, int] | None = None
        self._corner_at = 0.0

    # --- чтение состояния (из любого потока) ---------------------------------

    @property
    def state(self) -> State:
        return self._state

    @property
    def clicks(self) -> int:
        return self._clicks

    @property
    def skipped_slots(self) -> int:
        return self._skipped

    @property
    def stop_reason(self) -> StopReason | None:
        return self._stop_reason

    @property
    def error(self) -> str:
        return self._error

    def countdown_remaining(self) -> float:
        end = self._countdown_end
        if end is None or self._state is not State.WAITING:
            return 0.0
        return max(0.0, end - self._mono())

    def elapsed(self) -> float:
        """Рабочее время, с. Отсчёт начинается после задержки старта."""
        start = self._run_start
        if start is None:
            return 0.0
        end = self._run_end if self._run_end is not None else self._mono()
        return max(0.0, end - start)

    def is_active(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    # --- управление ----------------------------------------------------------

    def start(self, settings: Settings) -> bool:
        """Запустить цикл. ``False`` — уже работает (второй поток не создаётся)."""
        with self._lock:
            if self.is_active():
                return False
            self._stop.clear()
            self._settings = settings
            self._clicks = 0
            self._skipped = 0
            self._run_start = None
            self._run_end = None
            self._stop_reason = None
            self._error = ""
            self._corner = None
            self._countdown_end = self._mono() + settings.start_delay_s
            self._state = State.WAITING if settings.start_delay_s > 0 else State.RUNNING
            self._thread = threading.Thread(target=self._run, name="click-engine", daemon=True)
            self._thread.start()
            return True

    def stop(self, reason: StopReason = StopReason.MANUAL) -> None:
        """Попросить остановиться. Не блокирует; безопасно из любого потока."""
        if self._stop_reason is None:
            self._stop_reason = reason
        self._stop.set()

    def join(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return not self.is_active()

    def force_release(self) -> None:
        """Аварийно отпустить кнопку, если она нажата приложением (выход, atexit)."""
        with self._held_lock:
            button = self._held
            self._held = None
        if button is not None:
            try:
                self._adapter.release(button)
            except Exception:  # noqa: BLE001
                pass

    # --- рабочий цикл --------------------------------------------------------

    def _run(self) -> None:
        settings = self._settings
        assert settings is not None
        if self._on_session_start is not None:
            try:
                self._on_session_start()
            except Exception:  # noqa: BLE001
                pass
        try:
            if settings.start_delay_s > 0:
                if not self._countdown(settings.start_delay_s):
                    return
            self._loop(settings)
        except Exception as exc:  # noqa: BLE001 — ошибка не должна оставить кнопку нажатой
            self._error = str(exc) or exc.__class__.__name__
            if self._stop_reason is None:
                self._stop_reason = StopReason.ERROR
            self._state = State.ERROR
        finally:
            self.force_release()  # гарантированное отпускание
            if self._state is not State.ERROR:
                self._state = State.STOPPED
            if self._run_start is not None:
                self._run_end = self._mono()
            if self._on_session_end is not None:
                try:
                    self._on_session_end()
                except Exception:  # noqa: BLE001
                    pass
            if self._on_finished is not None:
                try:
                    self._on_finished()
                except Exception:  # noqa: BLE001
                    pass

    def _loop(self, settings: Settings) -> None:
        interval_s = settings.interval_ms / 1000.0
        hold_s = settings.hold_ms / 1000.0

        # Переход в «Работает». Первый клик — сразу.
        t0 = self._mono()
        self._run_start = t0
        self._state = State.RUNNING
        deadline = t0 + settings.stop_seconds if settings.stop_mode is StopMode.TIME else None
        k = 0

        while True:
            if self._stop.is_set():
                return
            if self._corner_hit():
                self._finish(StopReason.CORNER)
                return
            if deadline is not None and self._mono() >= deadline:
                self._finish(StopReason.TIME)
                return

            result = self._click(settings, hold_s, deadline)
            if result == _STOP:
                return
            if result == _CORNER:
                self._finish(StopReason.CORNER)
                return
            if result == _TIME:
                self._finish(StopReason.TIME)
                return

            if settings.stop_mode is StopMode.COUNT and self._clicks >= settings.stop_count:
                self._finish(StopReason.COUNT)
                return

            # Следующий слот — по времени НАЧАЛА нажатия; просроченные пропускаем.
            new_k = next_slot_index(t0, self._mono(), interval_s, k)
            self._skipped += new_k - k - 1
            k = new_k
            result = self._wait_until(t0 + k * interval_s, deadline)
            if result == _STOP:
                return
            if result == _CORNER:
                self._finish(StopReason.CORNER)
                return
            if result == _TIME:
                self._finish(StopReason.TIME)
                return

    def _finish(self, reason: StopReason) -> None:
        if self._stop_reason is None:
            self._stop_reason = reason
        self._stop.set()

    def _click(self, settings: Settings, hold_s: float, deadline: float | None) -> str:
        """Один полный цикл нажатия-отпускания.

        Счётчик растёт только после отпускания. Если удержание прервано
        остановкой, кнопка тут же отпускается и этот завершённый цикл (down и up
        отправлены) учитывается.
        """
        button = settings.button
        if settings.position_mode is PositionMode.FIXED:
            x, y = settings.fixed_x, settings.fixed_y
            if not self._adapter.point_available(x, y):
                raise PointUnavailableError(
                    f"Точка ({x}, {y}) недоступна: монитор отключён или координаты вне экранов."
                )
            self._adapter.move_to(x, y)

        with self._held_lock:
            # Помечаем до вызова: если press упадёт посередине, finally всё равно отпустит.
            self._held = button
        self._adapter.press(button)
        try:
            result = self._wait_until(self._mono() + hold_s, deadline)
        finally:
            with self._held_lock:
                still_held = self._held is not None
                self._held = None
            if still_held:
                self._adapter.release(button)
        self._clicks += 1
        return result

    def _countdown(self, seconds: float) -> bool:
        """Задержка старта. True — отсчёт завершён, False — остановлено."""
        end = self._mono() + seconds
        self._countdown_end = end
        result = self._wait_until(end, None)
        if result == _CORNER:
            self._finish(StopReason.CORNER)
        return result == _DONE

    def _wait_until(self, target: float, deadline: float | None) -> str:
        """Прерываемое ожидание момента ``target`` по монотонным часам.

        Спит порциями не длиннее ``poll_s`` (это не busy-wait: поток блокируется
        в Event.wait), между порциями проверяет защитный угол и дедлайн времени.
        """
        while True:
            if self._stop.is_set():
                return _STOP
            if self._corner_hit():
                return _CORNER
            now = self._mono()
            if deadline is not None and now >= deadline:
                return _TIME
            remaining = target - now
            if deadline is not None:
                remaining = min(remaining, deadline - now)
            if remaining <= 0:
                return _DONE
            self._stop.wait(min(self._poll_s, remaining))

    def _corner_hit(self) -> bool:
        # Границы основного экрана меняются редко — обновляем их раз в секунду,
        # а позицию курсора проверяем при каждом опросе.
        now = self._mono()
        if self._corner is None or now - self._corner_at >= 1.0:
            self._corner = self._adapter.corner_region()
            self._corner_at = now
        x, y = self._adapter.get_position()
        return in_region(x, y, self._corner)
