"""Небольшие виджеты интерфейса: числовое поле с −/+, сегменты, карточки."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..model import format_number, parse_number


def repolish(widget: QWidget) -> None:
    """Применить стили после смены динамического свойства."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def label(text: str = "", name: str | None = None, *, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    if wrap:
        lbl.setWordWrap(True)
    return lbl


class NumberField(QWidget):
    """Поле ввода числа с кнопками «−» и «+».

    Значение никогда не исправляется молча: текст хранится как ввёл пользователь,
    ``value()`` возвращает число или ``None`` (не число). Проверку диапазона делает
    окно и показывает ошибку рядом с полем через ``set_invalid``. Кнопки −/+
    меняют значение на шаг и останавливаются на границах диапазона.
    """

    edited = Signal()  # только изменения пользователем (ввод или −/+)

    def __init__(
        self,
        *,
        minimum: float,
        maximum: float,
        step: float = 1,
        decimals: int = 0,
        width: int = 84,
        accessible_name: str = "",
    ) -> None:
        super().__init__()
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.decimals = decimals

        self.minus = QPushButton("−")
        self.plus = QPushButton("+")
        for b, tip in ((self.minus, "Уменьшить"), (self.plus, "Увеличить")):
            b.setObjectName("stepButton")
            b.setAutoRepeat(True)
            b.setAutoRepeatDelay(400)
            b.setAutoRepeatInterval(60)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolTip(tip)
        self.edit = QLineEdit()
        self.edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit.setFixedWidth(width)
        self.edit.setAccessibleName(accessible_name)
        self.edit.setProperty("invalid", False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.minus)
        lay.addWidget(self.edit)
        lay.addWidget(self.plus)

        self.minus.clicked.connect(lambda: self._step(-1))
        self.plus.clicked.connect(lambda: self._step(+1))
        self.edit.textEdited.connect(lambda _t: self.edited.emit())

    def value(self) -> float | None:
        return parse_number(self.edit.text(), integer=self.decimals == 0)

    def text(self) -> str:
        return self.edit.text()

    def set_value(self, value: float) -> None:
        """Программная установка (не испускает ``edited`` — нет циклов обновлений)."""
        self.edit.setText(format_number(value, self.decimals))

    def set_invalid(self, invalid: bool) -> None:
        if bool(self.edit.property("invalid")) != invalid:
            self.edit.setProperty("invalid", invalid)
            repolish(self.edit)

    def _step(self, direction: int) -> None:
        current = self.value()
        if current is None:
            current = self.minimum if direction > 0 else self.maximum
            new = current
        else:
            new = current + direction * self.step
            # Шаг с дробного значения ведёт к ближайшему целому в нужную сторону.
            if self.step >= 1 and not float(current).is_integer():
                new = math.floor(current) + 1 if direction > 0 else math.ceil(current) - 1
        new = min(self.maximum, max(self.minimum, new))
        self.set_value(new)
        self.edited.emit()


class Segmented(QWidget):
    """Группа взаимоисключающих кнопок."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]]) -> None:
        super().__init__()
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for i, (key, text) in enumerate(options):
            b = QPushButton(text)
            b.setObjectName("segment")
            b.setCheckable(True)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if i == 0:
                b.setProperty("pos", "first")
            elif i == len(options) - 1:
                b.setProperty("pos", "last")
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
            b.clicked.connect(lambda _c=False, k=key: self.changed.emit(k))

    def set_current(self, key: str) -> None:
        self.buttons[key].setChecked(True)

    def current(self) -> str:
        for key, b in self.buttons.items():
            if b.isChecked():
                return key
        return next(iter(self.buttons))


class Card(QFrame):
    """Карточка-секция с заголовком."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(14, 12, 14, 14)
        self.body.setSpacing(8)
        head = label(title.upper(), "cardTitle")
        self.body.addWidget(head)


class FieldRow(QWidget):
    """Строка «подпись — поле» с местом для ошибки под ней."""

    def __init__(self, caption: str, field: QWidget, extra: QWidget | None = None) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.caption = label(caption)
        row.addWidget(self.caption, 1)
        if extra is not None:
            row.addWidget(extra)
        row.addWidget(field)
        outer.addLayout(row)
        self.error = label("", "error", wrap=True)
        self.error.setVisible(False)
        outer.addWidget(self.error)

    def set_error(self, message: str | None) -> None:
        self.error.setText(message or "")
        self.error.setVisible(bool(message))
