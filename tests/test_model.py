from __future__ import annotations

import pytest

from autoclicker.model import (
    CPS_MAX,
    CPS_MIN,
    PositionMode,
    Settings,
    StopMode,
    cps_in_range,
    cps_to_interval_ms,
    format_cps,
    format_interval,
    interval_to_cps,
    parse_number,
    validate,
)


def fields(settings: Settings, corner=(5, 5)) -> dict[str, str]:
    return {i.field: i.message for i in validate(settings, corner)}


def test_defaults_are_valid():
    s = Settings()
    assert s.interval_ms == 100 and s.cps == 10 and s.hold_ms == 20
    assert validate(s, (5, 5)) == []


def test_exact_conversion_without_rounding_loss():
    assert cps_to_interval_ms(3) == 1000 / 3
    assert interval_to_cps(cps_to_interval_ms(3)) == pytest.approx(3, abs=1e-12)
    assert cps_to_interval_ms(100) == 10
    assert cps_to_interval_ms(1000 / 60000) == pytest.approx(60000)
    assert CPS_MIN == pytest.approx(0.0166666667)
    assert CPS_MAX == 100
    assert format_cps(CPS_MIN) == "0,016667"
    assert format_interval(1000 / 3) == "333,333"
    with pytest.raises(ValueError):
        cps_to_interval_ms(0)


def test_cps_range_with_tolerance():
    assert cps_in_range(100) and cps_in_range(0.016667) and cps_in_range(1000 / 60000)
    assert not cps_in_range(100.01) and not cps_in_range(0.0166)


def test_interval_bounds():
    assert "interval_ms" in fields(Settings(interval_ms=9.99, hold_ms=1))
    assert "interval_ms" in fields(Settings(interval_ms=60000.5))
    assert "interval_ms" not in fields(Settings(interval_ms=10, hold_ms=1))
    assert "interval_ms" not in fields(Settings(interval_ms=60000, hold_ms=59999))


def test_hold_must_be_shorter_than_interval_by_1ms():
    msg = fields(Settings(interval_ms=100, hold_ms=100))["hold_ms"]
    assert "короче интервала" in msg and "1 мс" in msg
    assert "hold_ms" in fields(Settings(interval_ms=100, hold_ms=150))
    assert "hold_ms" not in fields(Settings(interval_ms=100, hold_ms=99))
    # Дробный интервал: 33,333 мс — нажатие 33 мс уже слишком длинное.
    assert "hold_ms" in fields(Settings(interval_ms=1000 / 30, hold_ms=33))
    assert "hold_ms" not in fields(Settings(interval_ms=1000 / 30, hold_ms=32))
    # Значения не исправляются молча.
    s = Settings(interval_ms=100, hold_ms=150)
    validate(s)
    assert s.hold_ms == 150 and s.interval_ms == 100


def test_hold_bounds():
    assert "hold_ms" in fields(Settings(hold_ms=0))
    assert "hold_ms" in fields(Settings(interval_ms=60000, hold_ms=60000))


def test_fixed_point_not_in_corner():
    s = Settings(position_mode=PositionMode.FIXED, fixed_x=4, fixed_y=0)
    assert "fixed_point" in fields(s)
    s.fixed_x = 5
    assert "fixed_point" not in fields(s)
    s.fixed_x, s.fixed_y = -3, 2  # левее основного экрана — это не угол
    assert "fixed_point" not in fields(s)
    # Учёт масштаба: угол 10×10 физических пикселей при 200 %.
    assert "fixed_point" in fields(Settings(position_mode=PositionMode.FIXED, fixed_x=8, fixed_y=8), (10, 10))
    # В режиме текущей позиции координаты не проверяются.
    assert "fixed_point" not in fields(Settings(fixed_x=0, fixed_y=0))


def test_stop_conditions_and_delay():
    assert "stop_count" in fields(Settings(stop_mode=StopMode.COUNT, stop_count=0))
    assert "stop_count" in fields(Settings(stop_mode=StopMode.COUNT, stop_count=1_000_001))
    assert "stop_count" not in fields(Settings(stop_mode=StopMode.COUNT, stop_count=1_000_000))
    assert "stop_count" not in fields(Settings(stop_mode=StopMode.MANUAL, stop_count=0))
    assert "stop_seconds" in fields(Settings(stop_mode=StopMode.TIME, stop_seconds=0))
    assert "stop_seconds" in fields(Settings(stop_mode=StopMode.TIME, stop_seconds=86401))
    assert "stop_seconds" not in fields(Settings(stop_mode=StopMode.TIME, stop_seconds=86400))
    assert "start_delay_s" in fields(Settings(start_delay_s=31))
    assert "start_delay_s" not in fields(Settings(start_delay_s=0))


@pytest.mark.parametrize(
    ("text", "integer", "expected"),
    [
        ("100", False, 100.0),
        ("33,5", False, 33.5),
        (" 2.25 ", False, 2.25),
        ("1 000", True, 1000.0),
        ("12,5", True, None),
        ("abc", False, None),
        ("", False, None),
        ("inf", False, None),
        ("nan", False, None),
        ("-15", True, -15.0),
    ],
)
def test_parse_number(text, integer, expected):
    assert parse_number(text, integer=integer) == expected
