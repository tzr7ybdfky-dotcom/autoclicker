"""Движок с подставным адаптером: реальные клики не отправляются."""

from __future__ import annotations

import threading
import time

import pytest

from autoclicker.engine import ClickEngine, State, StopReason, next_slot_index
from autoclicker.model import MouseButton, PositionMode, Settings, StopMode

from .fakes import FakeAdapter


def make(**kw) -> Settings:
    base = dict(interval_ms=10.0, hold_ms=1, start_delay_s=0)
    base.update(kw)
    return Settings(**base)


def run_to_end(engine: ClickEngine, settings: Settings, timeout: float = 10.0) -> None:
    assert engine.start(settings)
    assert engine.join(timeout), "движок не остановился вовремя"


def test_exactly_n_clicks_and_down_up_order():
    a = FakeAdapter()
    e = ClickEngine(a)
    run_to_end(e, make(stop_mode=StopMode.COUNT, stop_count=7))
    assert e.clicks == 7
    assert a.kinds() == ["down", "up"] * 7
    assert e.stop_reason is StopReason.COUNT
    assert e.state is State.STOPPED
    assert not a.pressed


@pytest.mark.parametrize("button", list(MouseButton))
def test_selected_button_is_used(button):
    a = FakeAdapter()
    e = ClickEngine(a)
    run_to_end(e, make(stop_mode=StopMode.COUNT, stop_count=2, button=button))
    assert {arg for k, arg, _t in a.events if k in ("down", "up")} == {button}


def test_stop_during_hold_releases_immediately_and_counts_cycle():
    a = FakeAdapter()
    e = ClickEngine(a)
    assert e.start(make(interval_ms=60_000, hold_ms=59_999))
    assert a.press_event.wait(2)
    time.sleep(0.05)
    t = time.monotonic()
    e.stop(StopReason.MANUAL)
    assert e.join(1.0)
    assert time.monotonic() - t < 0.3
    assert a.kinds() == ["down", "up"]
    assert e.clicks == 1  # прерванный, но завершённый цикл down+up засчитан
    assert e.stop_reason is StopReason.MANUAL
    assert not a.pressed


def test_stop_during_long_interval():
    a = FakeAdapter()
    e = ClickEngine(a)
    assert e.start(make(interval_ms=60_000, hold_ms=1))
    assert a.wait_presses(1)
    time.sleep(0.05)
    t = time.monotonic()
    e.stop(StopReason.HOTKEY)
    assert e.join(1.0)
    assert time.monotonic() - t < 0.3
    assert e.clicks == 1
    assert e.stop_reason is StopReason.HOTKEY


def test_stop_during_start_delay():
    a = FakeAdapter()
    e = ClickEngine(a)
    assert e.start(make(start_delay_s=30))
    time.sleep(0.05)
    assert e.state is State.WAITING
    assert 29 < e.countdown_remaining() <= 30
    t = time.monotonic()
    e.stop(StopReason.ESCAPE)
    assert e.join(1.0)
    assert time.monotonic() - t < 0.3
    assert a.events == []
    assert e.clicks == 0
    assert e.elapsed() == 0.0  # время не шло: отсчёт начинается после задержки
    assert e.state is State.STOPPED


def test_start_delay_then_first_click_immediately():
    a = FakeAdapter()
    e = ClickEngine(a)
    t = time.monotonic()
    assert e.start(make(start_delay_s=1, stop_mode=StopMode.COUNT, stop_count=1))
    assert e.join(3)
    first_down = a.times("down")[0]
    assert 0.95 <= first_down - t < 1.3


def test_release_after_press_error():
    a = FakeAdapter()
    a.fail_press_on = 3
    e = ClickEngine(a)
    run_to_end(e, make())
    assert e.state is State.ERROR
    assert e.stop_reason is StopReason.ERROR
    assert "сбой" in e.error
    assert e.clicks == 2
    # После ошибки кнопка, помеченная как нажатая, отпущена.
    assert a.kinds()[-1] == "up"
    assert not a.pressed


def test_release_after_error_during_hold():
    a = FakeAdapter()
    a.fail_position_after_press = 1  # проверка угла падает, пока кнопка удерживается
    e = ClickEngine(a)
    run_to_end(e, make(interval_ms=1000, hold_ms=500))
    assert e.state is State.ERROR
    assert a.kinds() == ["down", "up"]
    assert not a.pressed


def test_second_start_does_not_create_second_thread():
    a = FakeAdapter()
    e = ClickEngine(a)
    assert e.start(make(interval_ms=60_000))
    assert not e.start(make(interval_ms=10))
    assert not e.start(make(interval_ms=10))
    engine_threads = [t for t in threading.enumerate() if t.name == "click-engine"]
    assert len(engine_threads) == 1
    e.stop()
    assert e.join(1)


def test_time_limit_releases_button_immediately():
    a = FakeAdapter()
    e = ClickEngine(a)
    t = time.monotonic()
    run_to_end(e, make(interval_ms=60_000, hold_ms=59_999, stop_mode=StopMode.TIME, stop_seconds=1))
    up = a.times("up")
    assert len(up) == 1
    assert 0.95 <= up[0] - t < 1.25  # отпущена по истечении 1 с, а не через 59,999 с
    assert e.stop_reason is StopReason.TIME
    assert e.clicks == 1
    assert 0.95 <= e.elapsed() < 1.25


def test_time_limit_counts_from_after_delay():
    a = FakeAdapter()
    e = ClickEngine(a)
    t = time.monotonic()
    run_to_end(e, make(start_delay_s=1, interval_ms=60_000, stop_mode=StopMode.TIME, stop_seconds=1))
    assert 1.9 <= time.monotonic() - t < 2.4
    assert 0.95 <= e.elapsed() < 1.25


def test_next_slot_index_skips_overdue_slots():
    # Обычный случай — следующий слот.
    assert next_slot_index(0.0, 0.05, 0.1, 0) == 1
    # ОС задержала поток на 0,55 с: слоты 1–5 просрочены — сразу слот 6, без серии.
    assert next_slot_index(0.0, 0.55, 0.1, 0) == 6
    # Ровно на границе слота: этот слот уже наступил, берём следующий.
    assert next_slot_index(0.0, 0.75, 0.25, 2) == 4
    # Защита от погрешности деления float.
    k = next_slot_index(0.0, 1.0, 1 / 3, 0)
    assert k * (1 / 3) > 1.0


def test_no_catch_up_burst_after_stall():
    a = FakeAdapter()
    a.stall_press_on = 2
    a.stall_s = 0.3  # «подвисание» ОС длиной в 6 интервалов
    e = ClickEngine(a)
    run_to_end(e, make(interval_ms=50, hold_ms=1, stop_mode=StopMode.COUNT, stop_count=6))
    downs = a.times("down")
    gaps = [b - a_ for a_, b in zip(downs[1:], downs[2:])]
    # После задержки нет пачки кликов подряд: каждый следующий — не раньше ~интервала.
    assert all(g >= 0.035 for g in gaps), gaps
    assert e.skipped_slots >= 4


def test_schedule_by_press_start_not_accumulating_hold():
    a = FakeAdapter()
    e = ClickEngine(a)
    run_to_end(e, make(interval_ms=50, hold_ms=30, stop_mode=StopMode.COUNT, stop_count=11))
    downs = a.times("down")
    # 10 интервалов по 50 мс ≈ 0,5 с (удержание не прибавляется к интервалу).
    assert 0.48 <= downs[-1] - downs[0] < 0.65


def test_corner_stops_during_hold_and_wait():
    a = FakeAdapter()
    e = ClickEngine(a)
    assert e.start(make(interval_ms=60_000, hold_ms=59_999))
    assert a.press_event.wait(2)
    a.position = (2, 3)  # курсор в защитном углу
    assert e.join(1)
    assert e.stop_reason is StopReason.CORNER
    assert a.kinds() == ["down", "up"]

    a2 = FakeAdapter()
    a2.position = (0, 0)
    e2 = ClickEngine(a2)
    run_to_end(e2, make())
    assert e2.stop_reason is StopReason.CORNER
    assert a2.events == []  # в углу запуск сразу останавливается, кликов нет


def test_corner_stops_during_start_delay():
    a = FakeAdapter()
    e = ClickEngine(a)
    assert e.start(make(start_delay_s=30))
    time.sleep(0.05)
    a.position = (4, 4)
    assert e.join(1)
    assert e.stop_reason is StopReason.CORNER
    assert a.events == []


def test_fixed_point_moves_before_each_press():
    a = FakeAdapter()
    e = ClickEngine(a)
    run_to_end(
        e,
        make(position_mode=PositionMode.FIXED, fixed_x=-1200, fixed_y=300,
             stop_mode=StopMode.COUNT, stop_count=3),
    )
    kinds = [k for k, _a, _t in a.events]
    assert kinds == ["move", "down", "up"] * 3
    assert all(arg == (-1200, 300) for k, arg, _t in a.events if k == "move")


def test_fixed_point_on_disconnected_monitor_is_error_without_click():
    a = FakeAdapter()
    a.available = False
    e = ClickEngine(a)
    run_to_end(e, make(position_mode=PositionMode.FIXED, fixed_x=5000, fixed_y=5000))
    assert e.state is State.ERROR
    assert "монитор" in e.error
    assert a.events == []


def test_counters_reset_on_each_start_and_session_hooks():
    a = FakeAdapter()
    calls: list[str] = []
    e = ClickEngine(
        a,
        on_session_start=lambda: calls.append("start"),
        on_session_end=lambda: calls.append("end"),
        on_finished=lambda: calls.append("finished"),
    )
    run_to_end(e, make(stop_mode=StopMode.COUNT, stop_count=3))
    assert e.clicks == 3
    run_to_end(e, make(stop_mode=StopMode.COUNT, stop_count=2))
    assert e.clicks == 2
    assert calls == ["start", "end", "finished"] * 2


def test_force_release_from_other_thread():
    a = FakeAdapter()
    e = ClickEngine(a)
    assert e.start(make(interval_ms=60_000, hold_ms=59_999))
    assert a.press_event.wait(2)
    e.force_release()  # как при аварийном выходе
    assert not a.pressed
    e.stop()
    assert e.join(1)
    assert a.kinds().count("up") == 1  # повторного отпускания нет
