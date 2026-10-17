"""Главное окно.

GUI-поток только читает состояние движка (таймер ~8 раз/с) и получает сигналы
Qt. Движок и слушатель клавиатуры работают в своих потоках и не трогают виджеты:
события доходят сюда через сигналы в очереди Qt.
"""

from __future__ import annotations

import math
from dataclasses import replace

from PySide6.QtCore import QByteArray, QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import model as m
from .. import platform as plat
from ..engine import ClickEngine, State, StopReason
from ..hotkeys import HotkeyMatcher, qt_bridge_class, validate_hotkey
from ..model import (
    MouseButton,
    PositionMode,
    Settings,
    StopMode,
    cps_in_range,
    cps_to_interval_ms,
    format_number,
    validate,
)
from ..platform.base import PermissionState
from ..platform.keymaps import format_hotkey
from ..storage import SettingsStore, Stored
from .keys import qt_event_to_raw
from .widgets import Card, FieldRow, NumberField, Segmented, label, repolish

PRESETS_CPS = (1, 5, 10, 20, 50)
PICK_SECONDS = 3
UI_TICK_MS = 125  # 8 обновлений в секунду

BUTTON_NAMES = {
    MouseButton.LEFT: "Левая кнопка",
    MouseButton.RIGHT: "Правая кнопка",
    MouseButton.MIDDLE: "Средняя кнопка",
}

STOP_MESSAGES = {
    StopReason.MANUAL: "Остановлено кнопкой «Стоп».",
    StopReason.HOTKEY: "Остановлено горячей клавишей.",
    StopReason.ESCAPE: "Аварийная остановка: нажата Esc.",
    StopReason.CORNER: "Аварийная остановка: курсор в левом верхнем углу основного экрана.",
    StopReason.COUNT: "Готово: выполнено заданное число кликов.",
    StopReason.TIME: "Готово: заданное время истекло.",
    StopReason.CLOSING: "Остановлено при закрытии.",
}


def format_duration(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def format_speed(cps: float) -> str:
    return format_number(cps, 3 if cps >= 0.1 else 6)


class EngineSignals(QObject):
    finished = Signal()


class MainWindow(QMainWindow):
    def __init__(
        self,
        adapter: plat.MouseAdapter,
        listener: plat.KeyListener | None,
        store: SettingsStore,
        stored: Stored,
    ) -> None:
        super().__init__()
        self._adapter = adapter
        self._listener = listener
        self._store = store
        self._settings: Settings = replace(stored.settings)
        self._platform_key = plat.PLATFORM_KEY

        self._parse_errors: dict[str, str] = {}
        self._point_error = ""
        self._error_text = ""  # текст последней ошибки (статус «Ошибка»)
        self._ui_running = False
        self._recording = False
        self._picking = False
        self._pick_left = 0
        self._closing = False
        self._listener_poll = 0
        self._tick = 0
        self._perms = plat.check_permissions()
        self._input_was_ok = self._perms.can_listen_input is PermissionState.GRANTED

        self._matcher = HotkeyMatcher(self._settings.toggle_hotkey)
        self._bridge = qt_bridge_class()(self._matcher)
        self._bridge.toggle.connect(self._on_hotkey_toggle)
        self._bridge.escape.connect(self._on_escape)
        self._bridge.recorded.connect(self._on_hotkey_recorded)

        self._engine_signals = EngineSignals()
        self._engine_signals.finished.connect(self._refresh_runtime)
        self._engine = ClickEngine(
            adapter,
            on_finished=self._engine_signals.finished.emit,
            on_session_start=plat.begin_session,
            on_session_end=plat.end_session,
        )

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(UI_TICK_MS)
        self._ui_timer.timeout.connect(self._refresh_runtime)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._save)
        self._pick_timer = QTimer(self)
        self._pick_timer.setInterval(1000)
        self._pick_timer.timeout.connect(self._pick_tick)
        self._perm_timer = QTimer(self)
        self._perm_timer.setInterval(2000)
        self._perm_timer.timeout.connect(self._refresh_permissions)

        self.setWindowTitle("AutoClicker")
        self.setMinimumHeight(420)
        self.resize(460, 600)
        self._loading = True
        self._build_ui()
        self._load_into_ui()
        self._loading = False

        if stored.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(stored.window_geometry.encode("ascii")))
        if stored.warnings:
            self._show_info(
                "Часть сохранённых настроек была повреждена и заменена значениями по умолчанию.",
                error=False,
            )

        QApplication.instance().installEventFilter(self)
        self._refresh_permissions()
        self._revalidate()
        self._refresh_runtime()
        self._start_listener()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 12, 14, 8)
        outer.setSpacing(8)

        # --- шапка: всегда видна, «Стоп» доступен при любой прокрутке ---------
        head = QHBoxLayout()
        title = label("AutoClicker", "appTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.status_pill = label("Остановлен", "statusPill")
        self.status_pill.setAccessibleName("Статус")
        head.addWidget(self.status_pill)
        outer.addLayout(head)

        self.start_button = QPushButton("Старт")
        self.start_button.setObjectName("startButton")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.clicked.connect(self._on_start_clicked)
        outer.addWidget(self.start_button)

        self.block_hint = label("Запуск недоступен: исправьте поля, выделенные красным.", "error", wrap=True)
        self.block_hint.setVisible(False)
        outer.addWidget(self.block_hint)

        self.summary = label("", "summary", wrap=True)
        outer.addWidget(self.summary)

        stats = QHBoxLayout()
        stats.setSpacing(18)
        self.clicks_value = label("0", "statValue")
        self.time_value = label("0:00:00", "statValue")
        for caption, value in (("Клики", self.clicks_value), ("Время", self.time_value)):
            box = QHBoxLayout()
            box.setSpacing(6)
            box.addWidget(label(caption, "muted"))
            box.addWidget(value)
            stats.addLayout(box)
        stats.addStretch(1)
        outer.addLayout(stats)

        self.hotkey_hint = label("", "hint", wrap=True)
        outer.addWidget(self.hotkey_hint)
        self.info = label("", "hint", wrap=True)
        self.info.setVisible(False)
        outer.addWidget(self.info)

        # --- настройки в прокручиваемой области ------------------------------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("scrollContent")
        self.settings_box = content
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 4, 4, 8)
        col.setSpacing(10)
        col.addWidget(self._build_speed_card())
        col.addWidget(self._build_position_card())
        col.addWidget(self._build_run_card())
        col.addWidget(self._build_hotkey_card())
        if plat.IS_MAC:
            col.addWidget(self._build_permissions_card())
        col.addWidget(self._build_help_card())
        col.addStretch(1)
        self.scroll.setWidget(content)
        # Горизонтальной прокрутки нет, поэтому окно не может стать уже содержимого.
        self.scroll.setMinimumWidth(
            content.minimumSizeHint().width() + self.scroll.verticalScrollBar().sizeHint().width() + 2
        )
        outer.addWidget(self.scroll, 1)

        self.setCentralWidget(root)

    def _build_speed_card(self) -> Card:
        card = Card("Скорость")
        self.interval_field = NumberField(
            minimum=m.INTERVAL_MIN_MS, maximum=m.INTERVAL_MAX_MS, decimals=3, width=92,
            accessible_name="Интервал, мс",
        )
        self.cps_field = NumberField(
            minimum=m.CPS_MIN, maximum=m.CPS_MAX, decimals=6, width=92,
            accessible_name="Частота, кликов в секунду",
        )
        self.hold_field = NumberField(
            minimum=m.HOLD_MIN_MS, maximum=m.HOLD_MAX_MS, width=92,
            accessible_name="Длительность нажатия, мс",
        )
        self.interval_row = FieldRow("Интервал, мс", self.interval_field)
        self.interval_row.caption.setToolTip("От начала одного нажатия до начала следующего (10–60 000 мс)")
        self.cps_row = FieldRow("Частота, кликов/с", self.cps_field)
        self.cps_row.caption.setToolTip("Частота = 1000 / интервал (0,016667–100)")
        self.hold_row = FieldRow("Нажатие, мс", self.hold_field)
        self.hold_row.caption.setToolTip("Сколько кнопка удерживается (1–59 999 мс, меньше интервала)")
        card.body.addWidget(self.interval_row)
        card.body.addWidget(self.cps_row)

        presets = QHBoxLayout()
        presets.setSpacing(6)
        presets.addWidget(label("Пресеты", "muted"), 1)
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(False)
        self.preset_buttons: dict[int, QPushButton] = {}
        for cps in PRESETS_CPS:
            b = QPushButton(str(cps))
            b.setObjectName("preset")
            b.setCheckable(True)
            b.setToolTip(f"{cps} кликов/с — интервал {format_number(1000 / cps, 3)} мс")
            b.clicked.connect(lambda _c=False, v=cps: self._apply_preset(v))
            self.preset_buttons[cps] = b
            presets.addWidget(b)
        card.body.addLayout(presets)
        card.body.addWidget(self.hold_row)
        card.body.addWidget(
            label(
                "Точность зависит от ОС, нагрузки и энергосбережения: реальные интервалы "
                "могут быть немного длиннее. Опоздавшие клики пропускаются, а не догоняются.",
                "hint",
                wrap=True,
            )
        )

        self.interval_field.edited.connect(self._on_interval_edited)
        self.cps_field.edited.connect(self._on_cps_edited)
        self.hold_field.edited.connect(self._on_hold_edited)
        return card

    def _build_position_card(self) -> Card:
        card = Card("Кнопка и позиция")
        self.button_seg = Segmented([("left", "Левая"), ("right", "Правая"), ("middle", "Средняя")])
        self.button_seg.changed.connect(self._on_button_changed)
        card.body.addWidget(self.button_seg)

        self.pos_current = QRadioButton("Текущая позиция курсора")
        self.pos_fixed = QRadioButton("Фиксированная точка")
        self.pos_group = QButtonGroup(self)
        self.pos_group.addButton(self.pos_current)
        self.pos_group.addButton(self.pos_fixed)
        self.pos_current.toggled.connect(self._on_position_mode_changed)
        card.body.addWidget(self.pos_current)
        card.body.addWidget(self.pos_fixed)

        self.x_field = NumberField(minimum=-1_000_000, maximum=1_000_000, width=64, accessible_name="X")
        self.y_field = NumberField(minimum=-1_000_000, maximum=1_000_000, width=64, accessible_name="Y")
        self.pick_button = QPushButton("Выбрать точку")
        self.pick_button.clicked.connect(self._toggle_pick)

        self.coords_box = QWidget()
        grid = QGridLayout(self.coords_box)
        grid.setContentsMargins(22, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.addWidget(label("X"), 0, 0)
        grid.addWidget(self.x_field, 0, 1)
        grid.addWidget(label("Y"), 1, 0)
        grid.addWidget(self.y_field, 1, 1)
        grid.addWidget(self.pick_button, 0, 2, 2, 1, Qt.AlignmentFlag.AlignVCenter)
        grid.setColumnStretch(3, 1)
        card.body.addWidget(self.coords_box)
        self.coords_error = label("", "error", wrap=True)
        self.coords_error.setVisible(False)
        card.body.addWidget(self.coords_error)
        card.body.addWidget(
            label(
                f"Единицы: {plat.coordinate_units()}. Поддерживаются несколько мониторов "
                "и отрицательные координаты. «Выбрать точку» запоминает позицию курсора "
                f"через {PICK_SECONDS} с без клика; Esc — отмена.",
                "hint",
                wrap=True,
            )
        )

        self.x_field.edited.connect(lambda: self._on_coord_edited("fixed_x", self.x_field))
        self.y_field.edited.connect(lambda: self._on_coord_edited("fixed_y", self.y_field))
        return card

    def _build_run_card(self) -> Card:
        card = Card("Запуск и завершение")
        self.delay_field = NumberField(
            minimum=m.START_DELAY_MIN_S, maximum=m.START_DELAY_MAX_S, width=56,
            accessible_name="Задержка старта, с",
        )
        self.delay_row = FieldRow("Задержка старта, с", self.delay_field)
        self.delay_field.edited.connect(self._on_delay_edited)
        card.body.addWidget(self.delay_row)

        card.body.addWidget(label("Завершение", "muted"))
        self.stop_seg = Segmented([("manual", "Вручную"), ("count", "После N кликов"), ("time", "По времени")])
        self.stop_seg.changed.connect(self._on_stop_mode_changed)
        card.body.addWidget(self.stop_seg)

        self.count_field = NumberField(minimum=m.COUNT_MIN, maximum=m.COUNT_MAX, width=92, accessible_name="Число кликов")
        self.count_row = FieldRow("Число кликов", self.count_field)
        self.count_field.edited.connect(self._on_count_edited)
        card.body.addWidget(self.count_row)

        self.h_field = NumberField(minimum=0, maximum=24, width=34, accessible_name="Часы")
        self.min_field = NumberField(minimum=0, maximum=59, width=34, accessible_name="Минуты")
        self.s_field = NumberField(minimum=0, maximum=59, width=34, accessible_name="Секунды")
        self.time_box = QWidget()
        tcol = QVBoxLayout(self.time_box)
        tcol.setContentsMargins(0, 0, 0, 0)
        tcol.setSpacing(3)
        trow = QHBoxLayout()
        trow.setSpacing(4)
        for f, unit in ((self.h_field, "ч"), (self.min_field, "мин"), (self.s_field, "с")):
            trow.addWidget(f)
            trow.addWidget(label(unit, "muted"))
            trow.addSpacing(4)
            f.edited.connect(self._on_time_edited)
        trow.addStretch(1)
        tcol.addLayout(trow)
        self.time_error = label("", "error", wrap=True)
        self.time_error.setVisible(False)
        tcol.addWidget(self.time_error)
        card.body.addWidget(self.time_box)
        card.body.addWidget(
            label(
                "Время считается после задержки старта, первый клик — сразу. "
                "При остановке по времени кнопка отпускается немедленно.",
                "hint",
                wrap=True,
            )
        )
        return card

    def _build_hotkey_card(self) -> Card:
        card = Card("Горячие клавиши")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(label("Старт / Стоп"), 1)
        self.keycap = label("", "keycap")
        self.keycap.setProperty("recording", False)
        row.addWidget(self.keycap)
        self.assign_button = QPushButton("Назначить")
        self.assign_button.clicked.connect(self._toggle_record)
        row.addWidget(self.assign_button)
        card.body.addLayout(row)
        self.hotkey_error = label("", "error", wrap=True)
        self.hotkey_error.setVisible(False)
        card.body.addWidget(self.hotkey_error)
        self.hotkey_status = label("", "hint", wrap=True)
        card.body.addWidget(self.hotkey_status)
        card.body.addWidget(
            label(
                "Esc — аварийная остановка, назначить её нельзя. Клавиши не перехватываются: "
                "Esc и выбранное сочетание получит и активное приложение. Конфликты с "
                "сочетаниями других программ и системы обнаруживаются не все.",
                "hint",
                wrap=True,
            )
        )
        return card

    def _build_permissions_card(self) -> Card:
        card = Card("Разрешения macOS")
        self.perm_mouse = label("", wrap=True)
        self.perm_input = label("", wrap=True)
        self.perm_mouse_btn = QPushButton("Открыть настройки")
        self.perm_input_btn = QPushButton("Открыть настройки")
        self.perm_mouse_btn.clicked.connect(lambda: self._open_permission("mouse"))
        self.perm_input_btn.clicked.connect(lambda: self._open_permission("input"))
        for text_label, button in ((self.perm_mouse, self.perm_mouse_btn), (self.perm_input, self.perm_input_btn)):
            r = QHBoxLayout()
            r.setSpacing(8)
            r.addWidget(text_label, 1)
            r.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
            card.body.addLayout(r)
        self.perm_hint = label("", "hint", wrap=True)
        card.body.addWidget(self.perm_hint)
        self.perm_hint.setText(
            (
                "«Системные настройки → Конфиденциальность и безопасность»: включите "
                "AutoClicker в разделах «Универсальный доступ» и «Мониторинг ввода». "
                "При запуске из исходников разрешения выдаются программе, из которой "
                "запущен Python (Терминал, iTerm, VS Code), а не самому скрипту. "
                "После изменения перезапустите приложение. Запись экрана не нужна."
            )
        )
        self.perm_recheck = QPushButton("Проверить снова")
        self.perm_recheck.clicked.connect(self._refresh_permissions)
        rr = QHBoxLayout()
        rr.addStretch(1)
        rr.addWidget(self.perm_recheck)
        card.body.addLayout(rr)
        self.permissions_card = card
        return card

    def _build_help_card(self) -> Card:
        card = Card("Безопасность и ограничения")
        lines = [
            "Курсор в левый верхний угол основного экрана (5×5 точек) — немедленная остановка.",
            "Кнопка мыши всегда отпускается при остановке, ошибке и закрытии окна.",
            "Свёрнутое окно продолжает работу; закрытие окна останавливает клики и завершает приложение.",
        ]
        if plat.IS_WIN:
            lines.append(
                "Windows: клики не доходят до окон, запущенных от имени администратора, "
                "и до защищённых окон (UAC, экран блокировки) — это ограничение UIPI, "
                "обнаружить его нельзя, обходить его приложение не будет. Пока активно "
                "такое окно, Windows не передаёт и его клавиши: горячая клавиша и Esc там "
                "не сработают — используйте угол экрана или кнопку «Стоп»."
            )
            if plat.is_elevated():
                lines.append(
                    "Приложение запущено от имени администратора. Для обычной работы это "
                    "не нужно — запускайте его без повышенных прав."
                )
        if plat.IS_MAC:
            lines.append(
                "macOS: в полях ввода пароля и при «Защищённом вводе с клавиатуры» система "
                "скрывает нажатия — горячая клавиша и Esc там не сработают; используйте угол "
                "экрана или кнопку «Стоп». Если на левый верхний угол назначен «Активный угол», "
                "он тоже сработает."
            )
        lines.append("Работа в играх не гарантируется; обхода античит-систем нет.")
        card.body.addWidget(label("\n".join("• " + s for s in lines), "hint", wrap=True))
        return card

    # ------------------------------------------------- загрузка и синхронизация --

    def _load_into_ui(self) -> None:
        s = self._settings
        self.interval_field.set_value(s.interval_ms)
        self.cps_field.set_value(s.cps)
        self.hold_field.set_value(s.hold_ms)
        self.button_seg.set_current(s.button.value)
        (self.pos_fixed if s.position_mode is PositionMode.FIXED else self.pos_current).setChecked(True)
        self.x_field.set_value(s.fixed_x)
        self.y_field.set_value(s.fixed_y)
        self.delay_field.set_value(s.start_delay_s)
        self.stop_seg.set_current(s.stop_mode.value)
        self.count_field.set_value(s.stop_count)
        self.h_field.set_value(s.stop_seconds // 3600)
        self.min_field.set_value(s.stop_seconds % 3600 // 60)
        self.s_field.set_value(s.stop_seconds % 60)
        self._update_keycap()
        self._update_mode_visibility()

    def _changed(self) -> None:
        if self._loading:
            return
        self._revalidate()
        self._save_timer.start()

    def _on_interval_edited(self) -> None:
        value = self.interval_field.value()
        if value is None:
            self._parse_errors["interval"] = "Введите число, например 100 или 33,5."
        else:
            self._parse_errors.pop("interval", None)
            self._parse_errors.pop("cps", None)
            self._settings.interval_ms = value
            if value > 0:
                self.cps_field.set_value(1000.0 / value)
        self._changed()

    def _on_cps_edited(self) -> None:
        value = self.cps_field.value()
        if value is None or value <= 0:
            self._parse_errors["cps"] = "Введите частоту больше нуля, например 10 или 2,5."
        elif not cps_in_range(value):
            self._parse_errors["cps"] = (
                f"Частота должна быть от {format_number(m.CPS_MIN, 6)} до "
                f"{format_number(m.CPS_MAX, 0)} кликов/с."
            )
        else:
            self._parse_errors.pop("cps", None)
            self._parse_errors.pop("interval", None)
            self._settings.interval_ms = cps_to_interval_ms(value)  # точно, без округления
            self.interval_field.set_value(self._settings.interval_ms)
        self._changed()

    def _apply_preset(self, cps: int) -> None:
        self._parse_errors.pop("cps", None)
        self._parse_errors.pop("interval", None)
        self._settings.interval_ms = cps_to_interval_ms(cps)
        self.interval_field.set_value(self._settings.interval_ms)
        self.cps_field.set_value(cps)
        self._changed()

    def _int_from(self, key: str, field: NumberField) -> int | None:
        value = field.value()
        if value is None:
            self._parse_errors[key] = "Введите целое число."
            return None
        self._parse_errors.pop(key, None)
        return int(value)

    def _on_hold_edited(self) -> None:
        value = self._int_from("hold", self.hold_field)
        if value is not None:
            self._settings.hold_ms = value
        self._changed()

    def _on_button_changed(self, key: str) -> None:
        self._settings.button = MouseButton(key)
        self._changed()

    def _on_position_mode_changed(self) -> None:
        self._settings.position_mode = (
            PositionMode.CURRENT if self.pos_current.isChecked() else PositionMode.FIXED
        )
        self._point_error = ""
        self._update_mode_visibility()
        self._changed()

    def _on_coord_edited(self, attr: str, field: NumberField) -> None:
        value = self._int_from(attr, field)
        if value is not None:
            setattr(self._settings, attr, value)
        self._point_error = ""
        self._changed()

    def _on_delay_edited(self) -> None:
        value = self._int_from("delay", self.delay_field)
        if value is not None:
            self._settings.start_delay_s = value
        self._changed()

    def _on_stop_mode_changed(self, key: str) -> None:
        self._settings.stop_mode = StopMode(key)
        self._update_mode_visibility()
        self._changed()

    def _on_count_edited(self) -> None:
        value = self._int_from("count", self.count_field)
        if value is not None:
            self._settings.stop_count = value
        self._changed()

    def _on_time_edited(self) -> None:
        h, mi, s = (f.value() for f in (self.h_field, self.min_field, self.s_field))
        if h is None or mi is None or s is None:
            self._parse_errors["time"] = "Введите целые числа часов, минут и секунд."
        elif not (0 <= h <= 24 and 0 <= mi <= 59 and 0 <= s <= 59):
            self._parse_errors["time"] = "Часы — от 0 до 24, минуты и секунды — от 0 до 59."
        else:
            self._parse_errors.pop("time", None)
            self._settings.stop_seconds = int(h) * 3600 + int(mi) * 60 + int(s)
        self._changed()

    def _update_mode_visibility(self) -> None:
        fixed = self._settings.position_mode is PositionMode.FIXED
        self.coords_box.setEnabled(fixed)
        mode = self._settings.stop_mode
        self.count_row.setVisible(mode is StopMode.COUNT)
        self.time_box.setVisible(mode is StopMode.TIME)

    def _corner_size(self) -> tuple[int, int] | None:
        try:
            x0, y0, x1, y1 = self._adapter.corner_region()
        except Exception:  # noqa: BLE001
            return None
        return (x1 - x0, y1 - y0)

    def _blocking_errors(self) -> dict[str, str]:
        """Все ошибки, которые сейчас мешают запуску, по ключам строк интерфейса."""
        s = self._settings
        issues = {i.field: i.message for i in validate(s, self._corner_size())}
        errors: dict[str, str] = {}

        def put(key: str, *candidates: str | None) -> None:
            for c in candidates:
                if c:
                    errors[key] = c
                    return

        pe = self._parse_errors
        put("interval", pe.get("interval"), issues.get("interval_ms"))
        put("cps", pe.get("cps"))
        put("hold", pe.get("hold"), issues.get("hold_ms"))
        put("delay", pe.get("delay"), issues.get("start_delay_s"))
        if s.position_mode is PositionMode.FIXED:
            put(
                "coords",
                pe.get("fixed_x") and "X: " + pe["fixed_x"],
                pe.get("fixed_y") and "Y: " + pe["fixed_y"],
                issues.get("fixed_point"),
                self._point_error,
            )
        if s.stop_mode is StopMode.COUNT:
            put("count", pe.get("count"), issues.get("stop_count"))
        if s.stop_mode is StopMode.TIME:
            put("time", pe.get("time"), issues.get("stop_seconds"))
        return errors

    def _revalidate(self) -> dict[str, str]:
        errors = self._blocking_errors()
        pairs = (
            ("interval", self.interval_row, [self.interval_field]),
            ("cps", self.cps_row, [self.cps_field]),
            ("hold", self.hold_row, [self.hold_field]),
            ("delay", self.delay_row, [self.delay_field]),
            ("count", self.count_row, [self.count_field]),
        )
        for key, row, fields in pairs:
            row.set_error(errors.get(key))
            for f in fields:
                f.set_invalid(key in errors)
        coords_msg = errors.get("coords")
        self.coords_error.setText(coords_msg or "")
        self.coords_error.setVisible(bool(coords_msg))
        bad_x = bool(self._parse_errors.get("fixed_x")) or (coords_msg is not None and "fixed_x" not in self._parse_errors and "fixed_y" not in self._parse_errors)
        bad_y = bool(self._parse_errors.get("fixed_y")) or (coords_msg is not None and "fixed_x" not in self._parse_errors and "fixed_y" not in self._parse_errors)
        self.x_field.set_invalid(bad_x)
        self.y_field.set_invalid(bad_y)
        time_msg = errors.get("time")
        self.time_error.setText(time_msg or "")
        self.time_error.setVisible(bool(time_msg))
        for f in (self.h_field, self.min_field, self.s_field):
            f.set_invalid(bool(time_msg))

        speed_ok = "interval" not in self._parse_errors and "cps" not in self._parse_errors
        for cps, b in self.preset_buttons.items():
            b.setChecked(speed_ok and abs(self._settings.interval_ms - 1000.0 / cps) < 1e-6)
        self._update_summary()
        self._update_start_button()
        return errors

    def _update_summary(self) -> None:
        s = self._settings
        if s.position_mode is PositionMode.FIXED:
            where = f"точка ({s.fixed_x}, {s.fixed_y})"
        else:
            where = "текущая позиция"
        parts = [BUTTON_NAMES[s.button]]
        if s.interval_ms > 0:
            parts.append(f"{format_speed(s.cps)} кликов/с")
        parts += [f"удержание {s.hold_ms} мс", where]
        self.summary.setText(" · ".join(parts))

    def _update_keycap(self) -> None:
        if self._recording:
            self.keycap.setText("Нажмите сочетание…")
        else:
            hk = self._settings.toggle_hotkey
            self.keycap.setText(format_hotkey(hk.modifiers, hk.key, self._platform_key))
        self.keycap.setProperty("recording", self._recording)
        repolish(self.keycap)
        self.assign_button.setText("Отмена" if self._recording else "Назначить")
        hk = self._settings.toggle_hotkey
        combo = format_hotkey(hk.modifiers, hk.key, self._platform_key)
        self.hotkey_hint.setText(
            f"{combo} — старт/стоп · Esc или курсор в левый верхний угол — аварийная остановка"
        )

    # ------------------------------------------------------- запуск и стоп --

    def _update_start_button(self) -> None:
        active = self._ui_running
        has_errors = False
        b = self.start_button
        if active:
            b.setText("Стоп")
            b.setProperty("mode", "stop")
            b.setEnabled(True)  # «Стоп» доступен всегда
        else:
            b.setText("Старт")
            b.setProperty("mode", "start")
            has_errors = bool(self._blocking_errors())
            blocked = has_errors or self._recording or self._picking
            b.setEnabled(not blocked)
            if self._recording:
                b.setToolTip("Сначала завершите назначение горячей клавиши")
            elif self._picking:
                b.setToolTip("Идёт выбор точки")
            elif blocked:
                b.setToolTip("Исправьте выделенные поля")
            else:
                b.setToolTip("")
        self.block_hint.setVisible(not active and has_errors)
        repolish(b)

    def _on_start_clicked(self) -> None:
        if self._engine.is_active():
            self._engine.stop(StopReason.MANUAL)
        else:
            self._try_start()

    def _on_hotkey_toggle(self) -> None:
        if self._recording or self._closing:
            return
        if self._engine.is_active():
            self._engine.stop(StopReason.HOTKEY)
        else:
            self._try_start()

    def _on_escape(self) -> None:
        if self._recording:
            self._cancel_record()
            return
        if self._picking:
            self._cancel_pick("Выбор точки отменён.")
            return
        if self._engine.is_active():
            self._engine.stop(StopReason.ESCAPE)

    def _try_start(self) -> None:
        if self._closing or self._recording or self._picking or self._engine.is_active():
            return
        if self._ui_running:
            self._finalize_run()
        errors = self._revalidate()
        if errors:
            self._show_info("Запуск невозможен: исправьте выделенные поля.", error=True)
            return
        if plat.IS_MAC:
            self._refresh_permissions()
            if self._perms.can_control_mouse is not PermissionState.GRANTED:
                self._show_info(
                    "Нет разрешения «Универсальный доступ»: клики не будут доставлены. "
                    "Выдайте разрешение (раздел «Разрешения macOS» ниже).",
                    error=True,
                )
                self._scroll_to(self.permissions_card)
                return
        s = replace(self._settings)
        if s.position_mode is PositionMode.FIXED:
            try:
                ok = self._adapter.point_available(s.fixed_x, s.fixed_y)
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                self._point_error = (
                    f"Точка ({s.fixed_x}, {s.fixed_y}) не попадает ни на один подключённый "
                    "монитор. Возможно, монитор отключён — выберите точку заново."
                )
                self._revalidate()
                self._show_info("Запуск невозможен: фиксированная точка вне экранов.", error=True)
                return
        self._error_text = ""
        if not self._engine.start(s):
            return  # уже работает — второй поток не создаётся
        self._ui_running = True
        self.settings_box.setEnabled(False)
        if s.start_delay_s > 0:
            self._show_info(f"Старт через {s.start_delay_s} с. Переключитесь в нужное окно.")
        else:
            self._show_info("")
        self._update_start_button()
        self._ui_timer.start()
        self._refresh_runtime()

    def _finalize_run(self) -> None:
        """Перевести интерфейс в остановленное состояние после завершения потока."""
        self._ui_running = False
        self._ui_timer.stop()
        self.settings_box.setEnabled(True)
        engine = self._engine
        reason = engine.stop_reason
        if engine.state is State.ERROR or reason is StopReason.ERROR:
            self._error_text = engine.error or self._error_text or "Неизвестная ошибка."
            self._show_info(f"Ошибка: {self._error_text} Кнопка мыши отпущена.", error=True)
        elif reason is not None and engine.elapsed() == 0 and engine.clicks == 0 and reason in (
            StopReason.MANUAL, StopReason.HOTKEY, StopReason.ESCAPE, StopReason.CORNER
        ):
            prefix = "Курсор в защитном углу. " if reason is StopReason.CORNER else ""
            self._show_info(prefix + "Запуск отменён во время задержки старта.")
        else:
            text = STOP_MESSAGES.get(reason, "Остановлено.") if reason else "Остановлено."
            self._show_info(text, error=reason in (StopReason.ESCAPE, StopReason.CORNER))
        self._update_start_button()

    def _refresh_runtime(self) -> None:
        engine = self._engine
        if self._ui_running and not engine.is_active():
            self._finalize_run()
        self._tick += 1

        clicks = engine.clicks
        s = self._settings
        if self._ui_running and s.stop_mode is StopMode.COUNT:
            self.clicks_value.setText(f"{clicks:,} / {s.stop_count:,}".replace(",", " "))
        else:
            self.clicks_value.setText(f"{clicks:,}".replace(",", " "))
        elapsed = engine.elapsed()
        if self._ui_running and s.stop_mode is StopMode.TIME:
            self.time_value.setText(f"{format_duration(elapsed)} / {format_duration(s.stop_seconds)}")
        else:
            self.time_value.setText(format_duration(elapsed))

        if self._ui_running and engine.state is State.WAITING:
            left = math.ceil(engine.countdown_remaining())
            self._show_info(f"Старт через {max(left, 1)} с. Переключитесь в нужное окно.")
        elif self._ui_running and engine.state is State.RUNNING and self.info.text().startswith("Старт через"):
            self._show_info("")

        # Если во время работы отозвали «Универсальный доступ» — клики перестали
        # доходить; честно останавливаемся с ошибкой вместо ложного «Работает».
        if plat.IS_MAC and self._ui_running and self._tick % 8 == 0:
            self._perms = plat.check_permissions()
            if self._perms.can_control_mouse is not PermissionState.GRANTED:
                self._error_text = "разрешение «Универсальный доступ» отозвано."
                engine.stop(StopReason.ERROR)
        self._update_status()

    def _update_status(self) -> None:
        engine = self._engine
        if self._ui_running and engine.state is State.WAITING:
            text, tone = "Ожидание старта", "active"
        elif self._ui_running:
            text, tone = "Работает", "active"
        elif self._error_text:
            text, tone = "Ошибка", "danger"
        elif plat.IS_MAC and self._perms.can_control_mouse is not PermissionState.GRANTED:
            text, tone = "Нет разрешений", "danger"
        else:
            text, tone = "Остановлен", "neutral"
        if self.status_pill.text() != text or self.status_pill.property("tone") != tone:
            self.status_pill.setText(text)
            self.status_pill.setProperty("tone", tone)
            repolish(self.status_pill)

    def _show_info(self, text: str, *, error: bool = False) -> None:
        self.info.setText(text)
        name = "error" if error else "hint"
        if self.info.objectName() != name:
            self.info.setObjectName(name)
            repolish(self.info)
        self.info.setVisible(bool(text))

    def _scroll_to(self, widget: QWidget) -> None:
        self.scroll.ensureWidgetVisible(widget, 0, 0)

    # ------------------------------------------------------- выбор точки --

    def _toggle_pick(self) -> None:
        if self._picking:
            self._cancel_pick("Выбор точки отменён.")
            return
        if self._engine.is_active():
            return
        self._picking = True
        self._pick_left = PICK_SECONDS
        self.pick_button.setText("Отменить (Esc)")
        self._show_info(f"Наведите курсор на нужное место — точка запомнится через {self._pick_left} с.")
        self._pick_timer.start()
        self._update_start_button()

    def _pick_tick(self) -> None:
        self._pick_left -= 1
        if self._pick_left > 0:
            self._show_info(f"Наведите курсор на нужное место — точка запомнится через {self._pick_left} с.")
            return
        self._pick_timer.stop()
        self._picking = False
        self.pick_button.setText("Выбрать точку")
        try:
            x, y = self._adapter.get_position()
        except Exception as exc:  # noqa: BLE001
            self._show_info(f"Не удалось получить позицию курсора: {exc}", error=True)
            self._update_start_button()
            return
        self._settings.fixed_x, self._settings.fixed_y = x, y
        self._parse_errors.pop("fixed_x", None)
        self._parse_errors.pop("fixed_y", None)
        self._point_error = ""
        self.x_field.set_value(x)
        self.y_field.set_value(y)
        self._changed()
        if "coords" in self._blocking_errors():
            self._show_info("Эта точка не подходит — см. сообщение у координат.", error=True)
        else:
            self._show_info(f"Точка выбрана: ({x}, {y}).")

    def _cancel_pick(self, message: str) -> None:
        self._pick_timer.stop()
        self._picking = False
        self.pick_button.setText("Выбрать точку")
        self._show_info(message)
        self._update_start_button()

    # -------------------------------------------- назначение горячей клавиши --

    def _toggle_record(self) -> None:
        if self._recording:
            self._cancel_record()
            return
        if self._engine.is_active():
            return
        self._recording = True
        self._matcher.start_recording()
        self.hotkey_error.setVisible(False)
        self._update_keycap()
        self._update_start_button()
        hint = "Нажмите новое сочетание, Esc — отмена."
        if not self._listener_ok():
            hint += " Глобальные клавиши недоступны, поэтому окно должно оставаться активным."
        self._show_info(hint)

    def _cancel_record(self) -> None:
        self._matcher.cancel_recording()
        self._recording = False
        self.hotkey_error.setVisible(False)
        self._update_keycap()
        self._update_start_button()
        self._show_info("Назначение отменено, сочетание не изменилось.")

    def _on_hotkey_recorded(self, hotkey: m.Hotkey) -> None:
        if not self._recording:
            return
        error = validate_hotkey(hotkey)
        if error is not None:
            shown = format_hotkey(hotkey.modifiers, hotkey.key, self._platform_key)
            self.hotkey_error.setText(f"{shown}: {error}")
            self.hotkey_error.setVisible(True)
            return  # режим назначения продолжается
        self._recording = False
        self._settings.toggle_hotkey = hotkey
        self._matcher.set_hotkey(hotkey)  # тот же обработчик, новый образец
        self.hotkey_error.setVisible(False)
        self._update_keycap()
        self._update_start_button()
        self._save_timer.start()
        conflict = plat.probe_hotkey_conflict(hotkey.modifiers, hotkey.key)
        combo = format_hotkey(hotkey.modifiers, hotkey.key, self._platform_key)
        if conflict:
            self._show_info(
                f"Назначено: {combo}. Внимание: это сочетание уже зарегистрировано другой "
                "программой — она тоже на него среагирует. Лучше выбрать другое.",
                error=True,
            )
        else:
            self._show_info(f"Назначено: {combo}.")

    # ----------------------------------------------- слушатель клавиатуры --

    def _listener_ok(self) -> bool:
        return self._listener is not None and self._listener.available

    def _start_listener(self) -> None:
        if self._listener is None:
            self._update_listener_status()
            return
        try:
            self._listener.start(self._bridge.on_raw_event)
        except Exception as exc:  # noqa: BLE001
            self.hotkey_status.setText(f"Глобальные клавиши недоступны: {exc}")
            return
        self._listener_poll = 0
        self.hotkey_status.setText("Включаю глобальные клавиши…")
        QTimer.singleShot(100, self._poll_listener)

    def _poll_listener(self) -> None:
        if self._listener is None:
            return
        if self._listener.wait_ready(0):
            self._update_listener_status()
            return
        self._listener_poll += 1
        if self._listener_poll < 50:
            QTimer.singleShot(100, self._poll_listener)
        else:
            self.hotkey_status.setText("Глобальные клавиши не отвечают. Перезапустите приложение.")

    def _update_listener_status(self) -> None:
        if self._listener_ok():
            self.hotkey_status.setText("Глобальные клавиши работают в любом приложении.")
            self.hotkey_status.setObjectName("hint")
        else:
            reason = self._listener.error if self._listener is not None else ""
            self.hotkey_status.setText(
                (reason or "Глобальные клавиши недоступны.")
                + " Пока окно AutoClicker активно, Esc и назначение работают внутри окна."
            )
            self.hotkey_status.setObjectName("error")
        repolish(self.hotkey_status)

    def _restart_listener(self) -> None:
        if self._listener is None:
            return
        self._listener.stop()
        self._start_listener()

    # ------------------------------------------------------- разрешения --

    def _refresh_permissions(self) -> None:
        self._perms = plat.check_permissions()
        if plat.IS_MAC:
            p = self._perms
            mouse_ok = p.can_control_mouse is PermissionState.GRANTED
            input_ok = p.can_listen_input is PermissionState.GRANTED
            self.perm_mouse.setText(
                ("✓ " if mouse_ok else "✗ ")
                + "Универсальный доступ — отправка кликов в другие приложения"
                + ("" if mouse_ok else " (не выдано)")
            )
            self.perm_input.setText(
                ("✓ " if input_ok else "✗ ")
                + "Мониторинг ввода — глобальная горячая клавиша и Esc"
                + ("" if input_ok else " (не выдано)")
            )
            self.perm_mouse.setObjectName("" if mouse_ok else "error")
            self.perm_input.setObjectName("" if input_ok else "error")
            repolish(self.perm_mouse)
            repolish(self.perm_input)
            self.perm_mouse_btn.setVisible(not mouse_ok)
            self.perm_input_btn.setVisible(not input_ok)
            self.perm_hint.setVisible(not (mouse_ok and input_ok))
            self.perm_recheck.setVisible(not (mouse_ok and input_ok))
            if mouse_ok and input_ok:
                self._perm_timer.stop()
            elif not self._perm_timer.isActive():
                self._perm_timer.start()
            # Разрешение «Мониторинг ввода» выдали, пока приложение открыто — один раз
            # пробуем включить слушатель заново (иногда macOS требует перезапуск).
            if (
                input_ok
                and not self._input_was_ok
                and self._listener is not None
                and not self._listener.available
                and self._listener.wait_ready(0)
            ):
                self._restart_listener()
            self._input_was_ok = input_ok
        self._update_status()

    def _open_permission(self, kind: str) -> None:
        if kind == "mouse":
            plat.request_mouse_permission()
        else:
            plat.request_input_permission()
        url = plat.settings_url(kind)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    # --------------------------------------------------- события окна --

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        etype = event.type()
        if etype in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.ShortcutOverride):
            if self._recording:
                # Пока идёт назначение, клавиши не должны нажимать кнопки окна.
                if (
                    etype != QEvent.Type.ShortcutOverride
                    and isinstance(event, QKeyEvent)
                    and not self._listener_ok()
                ):
                    self._bridge.on_raw_event(qt_event_to_raw(event))
                return True
            if (
                etype == QEvent.Type.KeyPress
                and not self._listener_ok()
                and isinstance(event, QKeyEvent)
                and event.key() == Qt.Key.Key_Escape
                and not event.isAutoRepeat()
            ):
                self._on_escape()
        return super().eventFilter(obj, event)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self._refresh_permissions()
        super().changeEvent(event)

    def _save(self) -> None:
        try:
            geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self._store.save(self._settings, geometry)
        except OSError as exc:
            self._show_info(f"Не удалось сохранить настройки: {exc}", error=True)

    def emergency_release(self) -> None:
        """Для atexit: отпустить кнопку, если процесс завершается нештатно."""
        try:
            self._engine.stop(StopReason.CLOSING)
            self._engine.force_release()
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._closing = True
        self._pick_timer.stop()
        self._picking = False
        if self._recording:
            self._matcher.cancel_recording()
            self._recording = False
        if self._engine.is_active():
            self._engine.stop(StopReason.CLOSING)
            self._engine.join(2.0)
        self._engine.force_release()
        self._ui_timer.stop()
        self._perm_timer.stop()
        self._save_timer.stop()
        self._save()
        if self._listener is not None:
            self._listener.stop()
        QApplication.instance().removeEventFilter(self)
        event.accept()
        super().closeEvent(event)

    # Для тестов и проверки сборки.
    @property
    def engine(self) -> ClickEngine:
        return self._engine

    @property
    def settings(self) -> Settings:
        return self._settings

    def is_start_blocked(self) -> bool:
        return not self.start_button.isEnabled()


__all__ = ["MainWindow", "format_duration", "format_speed"]
