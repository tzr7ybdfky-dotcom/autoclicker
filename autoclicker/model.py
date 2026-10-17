"""Модель настроек автокликера и их проверка.

Единица скорости — интервал в миллисекундах (время от начала одного нажатия
до начала следующего). Частота (кликов в секунду) — производная величина:
    CPS = 1000 / интервал_мс
Интервал хранится как основной параметр, частота только показывается.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# --- границы значений ---------------------------------------------------------

INTERVAL_MIN_MS = 10
INTERVAL_MAX_MS = 60_000
HOLD_MIN_MS = 1
HOLD_MAX_MS = 59_999
# Частота выводится из интервала: 1000/60000 ≈ 0,016667 … 1000/10 = 100.
CPS_MIN = 1000.0 / INTERVAL_MAX_MS
CPS_MAX = 1000.0 / INTERVAL_MIN_MS
# Допуск сравнения дробных интервалов (мс): защищает от погрешности float.
_EPS = 1e-9

START_DELAY_MIN_S = 0
START_DELAY_MAX_S = 30

COUNT_MIN = 1
COUNT_MAX = 1_000_000
DURATION_MIN_S = 1
DURATION_MAX_S = 24 * 3600

# Защитная область в левом верхнем углу основного экрана (логические пиксели).
CORNER_LOGICAL = 5


class MouseButton(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


class PositionMode(str, Enum):
    CURRENT = "current"  # кликать там, где курсор, не двигая его
    FIXED = "fixed"  # перед каждым нажатием вести курсор в сохранённую точку


class StopMode(str, Enum):
    MANUAL = "manual"  # до ручной остановки
    COUNT = "count"  # после N кликов
    TIME = "time"  # через заданное время


MODIFIERS = ("ctrl", "alt", "shift", "meta")


@dataclass(frozen=True)
class Hotkey:
    """Комбинация: набор модификаторов + основная клавиша.

    ``modifiers`` — подмножество :data:`MODIFIERS` (meta — Command на macOS,
    Win на Windows). ``key`` — каноническое имя клавиши, например ``"F8"``.
    """

    modifiers: frozenset[str] = frozenset()
    key: str = ""

    def is_empty(self) -> bool:
        return not self.key

    def to_dict(self) -> dict:
        return {"modifiers": sorted(self.modifiers), "key": self.key}

    @classmethod
    def from_dict(cls, data: object) -> "Hotkey":
        if not isinstance(data, dict):
            return cls()
        mods = data.get("modifiers", [])
        key = data.get("key", "")
        if not isinstance(key, str):
            return cls()
        mods = frozenset(m for m in mods if m in MODIFIERS) if isinstance(mods, list) else frozenset()
        return cls(modifiers=mods, key=key)


DEFAULT_TOGGLE_HOTKEY = Hotkey(modifiers=frozenset({"ctrl", "alt"}), key="F8")


@dataclass
class Settings:
    # Интервал — основной параметр скорости. Дробный, чтобы частота вроде
    # 3 клика/с (333,333… мс) не теряла точность при округлении.
    interval_ms: float = 100.0
    hold_ms: int = 20
    button: MouseButton = MouseButton.LEFT
    position_mode: PositionMode = PositionMode.CURRENT
    fixed_x: int = 0
    fixed_y: int = 0
    stop_mode: StopMode = StopMode.MANUAL
    stop_count: int = 100
    stop_seconds: int = 60
    start_delay_s: int = 3
    toggle_hotkey: Hotkey = field(default_factory=lambda: DEFAULT_TOGGLE_HOTKEY)

    # --- производные величины -------------------------------------------------

    @property
    def cps(self) -> float:
        return 1000.0 / self.interval_ms

    @property
    def hold_s(self) -> float:
        return self.hold_ms / 1000.0

    @property
    def interval_s(self) -> float:
        return self.interval_ms / 1000.0


def cps_to_interval_ms(cps: float) -> float:
    """Точный интервал для частоты: 1000 / CPS (без округления и без обрезки).

    Выход за границы не исправляется молча — это ловит :func:`validate`.
    """
    if cps <= 0:
        raise ValueError("Частота должна быть больше нуля")
    return 1000.0 / cps


def interval_to_cps(interval_ms: float) -> float:
    return 1000.0 / interval_ms


def cps_in_range(cps: float) -> bool:
    return CPS_MIN - _EPS <= cps <= CPS_MAX + _EPS


def _trim(text: str) -> str:
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_number(value: float, decimals: int) -> str:
    """Число с запятой (русская локаль), без лишних нулей в дробной части."""
    return _trim(f"{value:.{decimals}f}").replace(".", ",")


def format_interval(interval_ms: float) -> str:
    return format_number(interval_ms, 3)


def format_cps(cps: float) -> str:
    """Частота с точностью до 6 знаков (видно и 0,016667, и 3,000003)."""
    return format_number(cps, 6)


def parse_number(text: str, *, integer: bool = False) -> float | None:
    """Разобрать ввод пользователя: допускается запятая или точка. None — не число."""
    t = text.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
    if not t:
        return None
    try:
        value = float(t)
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    if integer:
        if not value.is_integer():
            return None
        return float(int(value))
    return value


@dataclass
class ValidationIssue:
    field: str
    message: str


def validate(settings: Settings, corner_size: tuple[int, int] | None = None) -> list[ValidationIssue]:
    """Вернуть список проблем. Пустой список — запуск разрешён.

    Значения не исправляются молча: о каждой несовместимости сообщается отдельно.
    ``corner_size`` — размер защитной области (в координатах адаптера) для проверки
    фиксированной точки; ``None`` отключает эту проверку.
    """

    issues: list[ValidationIssue] = []

    if not (INTERVAL_MIN_MS - _EPS <= settings.interval_ms <= INTERVAL_MAX_MS + _EPS):
        issues.append(
            ValidationIssue(
                "interval_ms",
                f"Интервал должен быть от {INTERVAL_MIN_MS} до {INTERVAL_MAX_MS} мс.",
            )
        )
    if not (HOLD_MIN_MS <= settings.hold_ms <= HOLD_MAX_MS):
        issues.append(
            ValidationIssue(
                "hold_ms",
                f"Длительность нажатия должна быть от {HOLD_MIN_MS} до {HOLD_MAX_MS} мс.",
            )
        )
    # Длительность нажатия должна быть меньше интервала минимум на 1 мс.
    elif settings.hold_ms > settings.interval_ms - 1 + _EPS:
        issues.append(
            ValidationIssue(
                "hold_ms",
                f"Нажатие ({settings.hold_ms} мс) должно быть короче интервала "
                f"({format_interval(settings.interval_ms)} мс) хотя бы на 1 мс. "
                "Уменьшите нажатие или увеличьте интервал.",
            )
        )

    if settings.position_mode is PositionMode.FIXED and corner_size is not None:
        cw, ch = corner_size
        if 0 <= settings.fixed_x < cw and 0 <= settings.fixed_y < ch:
            issues.append(
                ValidationIssue(
                    "fixed_point",
                    "Фиксированная точка не может быть в защитном углу "
                    f"(меньше {cw}×{ch} от левого верхнего края основного экрана).",
                )
            )

    if settings.stop_mode is StopMode.COUNT:
        if not (COUNT_MIN <= settings.stop_count <= COUNT_MAX):
            issues.append(
                ValidationIssue(
                    "stop_count",
                    f"Число кликов должно быть от {COUNT_MIN} до {COUNT_MAX}.",
                )
            )
    if settings.stop_mode is StopMode.TIME:
        if not (DURATION_MIN_S <= settings.stop_seconds <= DURATION_MAX_S):
            issues.append(
                ValidationIssue(
                    "stop_seconds",
                    "Время работы должно быть от 1 секунды до 24 часов.",
                )
            )

    if not (START_DELAY_MIN_S <= settings.start_delay_s <= START_DELAY_MAX_S):
        issues.append(
            ValidationIssue(
                "start_delay_s",
                f"Задержка старта должна быть от {START_DELAY_MIN_S} до {START_DELAY_MAX_S} с.",
            )
        )

    return issues
