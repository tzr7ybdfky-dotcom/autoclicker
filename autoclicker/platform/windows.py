"""Адаптеры Windows: мышь через SendInput, глобальные клавиши через WH_KEYBOARD_LL.

• Работает без прав администратора. Из-за UIPI SendInput не вставляет ввод в окна
  с более высоким уровнем целостности (приложения, запущенные от администратора)
  и в часть защищённых окон; по документации Microsoft такую блокировку нельзя
  обнаружить ни по коду возврата, ни через GetLastError. UAC не обходится.
• Координаты — физические пиксели виртуального рабочего стола. Все вызовы
  с координатами выполняются в потоке с контекстом Per-Monitor-V2 DPI
  (SetThreadDpiAwarenessContext), поэтому при любом масштабировании Windows
  GetCursorPos/SetCursorPos/MonitorFromPoint работают в реальных пикселях.
• Хук клавиатуры только наблюдает (CallNextHookEx) — клавиши не подавляются.

Структуры объявлены переносимыми типами фиксированной ширины, а DLL загружаются
лениво, поэтому раскладку структур можно проверить тестами и на других ОС.
"""

from __future__ import annotations

import ctypes
import threading
from contextlib import contextmanager
from ctypes import c_int, c_int32, c_size_t, c_ssize_t, c_uint16, c_uint32, c_void_p
from typing import Callable

from ..model import MouseButton
from .base import KeyEventKind, PermissionInfo, PermissionState, RawKeyEvent
from .keymaps import WIN_VK_MODIFIERS, WIN_VK_TO_NAME

CORNER_LOGICAL = 5

LONG = c_int32
DWORD = c_uint32
UINT = c_uint32
WORD = c_uint16
BOOL = c_int32
ULONG_PTR = c_size_t
WPARAM = c_size_t
LPARAM = c_ssize_t
LRESULT = c_ssize_t


# --- структуры (раскладка как в Windows x64) ---------------------------------


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", LONG),
        ("dy", LONG),
        ("mouseData", DWORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", WORD),
        ("wScan", WORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class _INPUTUNION(ctypes.Union):
    # Объединение должно быть полного размера, иначе SendInput отвергнет cbSize.
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", DWORD), ("u", _INPUTUNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", DWORD),
        ("scanCode", DWORD),
        ("flags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", c_void_p),
        ("message", UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", DWORD),
        ("pt", POINT),
        ("lPrivate", DWORD),
    ]


class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", c_uint32), ("ControlMask", c_uint32), ("StateMask", c_uint32)]


INPUT_MOUSE = 0
MOUSE_FLAGS = {
    (MouseButton.LEFT, True): 0x0002,
    (MouseButton.LEFT, False): 0x0004,
    (MouseButton.RIGHT, True): 0x0008,
    (MouseButton.RIGHT, False): 0x0010,
    (MouseButton.MIDDLE, True): 0x0020,
    (MouseButton.MIDDLE, False): 0x0040,
}

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000
MONITOR_DEFAULTTONULL = 0
MONITOR_DEFAULTTOPRIMARY = 1
MDT_EFFECTIVE_DPI = 0
DPI_CONTEXT_PER_MONITOR_AWARE_V2 = -4
DPI_CONTEXT_PER_MONITOR_AWARE = -3

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409


# --- ленивая загрузка WinAPI с явными типами ---------------------------------

_api_cache: dict[str, object] = {}


def _api():  # noqa: ANN202
    if "user32" in _api_cache:
        return _api_cache["user32"], _api_cache["kernel32"]
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def sig(fn, res, *args):  # noqa: ANN001, ANN202
        fn.restype = res
        fn.argtypes = list(args)

    sig(user32.SendInput, UINT, UINT, ctypes.POINTER(INPUT), c_int)
    sig(user32.GetCursorPos, BOOL, ctypes.POINTER(POINT))
    sig(user32.SetCursorPos, BOOL, c_int, c_int)
    sig(user32.MonitorFromPoint, c_void_p, POINT, DWORD)
    sig(user32.SetWindowsHookExW, c_void_p, c_int, c_void_p, c_void_p, DWORD)
    sig(user32.UnhookWindowsHookEx, BOOL, c_void_p)
    sig(user32.CallNextHookEx, LRESULT, c_void_p, c_int, WPARAM, LPARAM)
    sig(user32.GetMessageW, BOOL, ctypes.POINTER(MSG), c_void_p, UINT, UINT)
    sig(user32.PeekMessageW, BOOL, ctypes.POINTER(MSG), c_void_p, UINT, UINT, UINT)
    sig(user32.TranslateMessage, BOOL, ctypes.POINTER(MSG))
    sig(user32.DispatchMessageW, LRESULT, ctypes.POINTER(MSG))
    sig(user32.PostThreadMessageW, BOOL, DWORD, UINT, WPARAM, LPARAM)
    sig(user32.GetAsyncKeyState, ctypes.c_short, c_int)
    sig(user32.RegisterHotKey, BOOL, c_void_p, c_int, UINT, UINT)
    sig(user32.UnregisterHotKey, BOOL, c_void_p, c_int)
    sig(kernel32.GetCurrentThreadId, DWORD)
    sig(kernel32.GetModuleHandleW, c_void_p, ctypes.c_wchar_p)
    sig(kernel32.GetCurrentProcess, c_void_p)
    sig(kernel32.SetThreadExecutionState, c_uint32, c_uint32)
    try:
        sig(user32.SetThreadDpiAwarenessContext, c_void_p, c_void_p)
    except AttributeError:  # Windows старше 10 1607
        pass
    try:
        sig(kernel32.SetProcessInformation, BOOL, c_void_p, c_int, c_void_p, DWORD)
    except AttributeError:
        pass
    _api_cache["user32"] = user32
    _api_cache["kernel32"] = kernel32
    return user32, kernel32


@contextmanager
def _physical_pixels():
    """Временно перевести текущий поток в Per-Monitor-V2 DPI: координаты в физических пикселях."""
    user32, _ = _api()
    fn = getattr(user32, "SetThreadDpiAwarenessContext", None)
    old = None
    if fn is not None:
        old = fn(c_void_p(DPI_CONTEXT_PER_MONITOR_AWARE_V2)) or fn(
            c_void_p(DPI_CONTEXT_PER_MONITOR_AWARE)
        )
    try:
        yield
    finally:
        if fn is not None and old:
            fn(c_void_p(old))


# --- мышь --------------------------------------------------------------------


class MouseSendError(RuntimeError):
    pass


class WinMouseAdapter:
    def _send(self, button: MouseButton, down: bool) -> None:
        user32, _ = _api()
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.u.mi = MOUSEINPUT(0, 0, 0, MOUSE_FLAGS[(button, down)], 0, 0)
        # Без координат: нажатие в текущей позиции курсора.
        if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
            raise MouseSendError(
                f"Windows отклонила отправку события мыши (код {ctypes.get_last_error()})."
            )

    def press(self, button: MouseButton) -> None:
        self._send(button, True)

    def release(self, button: MouseButton) -> None:
        self._send(button, False)

    def move_to(self, x: int, y: int) -> None:
        user32, _ = _api()
        with _physical_pixels():
            if not user32.SetCursorPos(int(x), int(y)):
                raise MouseSendError(f"Не удалось переместить курсор в ({x}, {y}).")

    def get_position(self) -> tuple[int, int]:
        user32, _ = _api()
        pt = POINT()
        with _physical_pixels():
            if not user32.GetCursorPos(ctypes.byref(pt)):
                raise MouseSendError("Не удалось получить позицию курсора (экран заблокирован?).")
        return int(pt.x), int(pt.y)

    def corner_region(self) -> tuple[int, int, int, int]:
        # Левый верхний угол основного монитора — всегда (0, 0) в физических пикселях.
        # 5 логических пикселей переводим в физические по DPI основного монитора.
        scale = 1.0
        user32, _ = _api()
        try:
            shcore = ctypes.WinDLL("shcore")
            with _physical_pixels():
                mon = user32.MonitorFromPoint(POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
                dpi_x, dpi_y = c_uint32(), c_uint32()
                if shcore.GetDpiForMonitor(c_void_p(mon), MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
                    scale = dpi_x.value / 96.0
        except Exception:  # noqa: BLE001
            scale = 1.0
        size = max(1, round(CORNER_LOGICAL * scale))
        return (0, 0, size, size)

    def point_available(self, x: int, y: int) -> bool:
        user32, _ = _api()
        with _physical_pixels():
            return bool(user32.MonitorFromPoint(POINT(int(x), int(y)), MONITOR_DEFAULTTONULL))


# --- глобальный хук клавиатуры ----------------------------------------------


def modifiers_from_state(tracked: set[str], is_down: Callable[[int], bool]) -> frozenset[str]:
    """Модификаторы, которые реально удержаны: отслеженные по событиям и
    подтверждённые системным состоянием (защита от «залипания», если отпускание
    пришлось на окно, чьи события хук не видит)."""
    result = set()
    for vk, name in WIN_VK_MODIFIERS.items():
        if name in tracked and is_down(vk):
            result.add(name)
    return frozenset(result)


class WinKeyListener:
    """WH_KEYBOARD_LL в отдельном потоке с собственным циклом сообщений."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._proc = None  # ссылка на колбэк, чтобы его не собрал GC
        self._callback: Callable[[RawKeyEvent], None] | None = None
        self._mods: set[str] = set()
        self._down: set[int] = set()
        self._available = False
        self._error = ""

    @property
    def available(self) -> bool:
        return self._available

    @property
    def error(self) -> str:
        return self._error

    def start(self, callback: Callable[[RawKeyEvent], None]) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._callback = callback
        self._ready.clear()
        self._error = ""
        self._thread = threading.Thread(target=self._run, name="win-key-hook", daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        user32, _ = _api()
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(1.0)
        self._available = False

    def _run(self) -> None:
        user32, kernel32 = _api()
        self._thread_id = kernel32.GetCurrentThreadId()
        msg = MSG()
        # Создаём очередь сообщений потока заранее, чтобы WM_QUIT дошёл.
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)

        hookproc_type = ctypes.WINFUNCTYPE(LRESULT, c_int, WPARAM, LPARAM)

        def proc(n_code, w_param, l_param):  # noqa: ANN001, ANN202
            if n_code == 0:
                try:
                    self._handle(w_param, l_param)
                except Exception:  # noqa: BLE001 — хук должен быстро возвращать управление
                    pass
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._proc = hookproc_type(proc)
        hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, ctypes.cast(self._proc, c_void_p), kernel32.GetModuleHandleW(None), 0
        )
        if not hook:
            self._error = (
                f"Не удалось включить глобальные клавиши (код {ctypes.get_last_error()})."
            )
            self._ready.set()
            return
        self._available = True
        self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnhookWindowsHookEx(hook)
            self._available = False
            self._thread_id = 0

    def _handle(self, w_param: int, l_param: int) -> None:
        callback = self._callback
        if callback is None or w_param not in (WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP):
            return
        user32, _ = _api()
        info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk = int(info.vkCode)
        is_up = w_param in (WM_KEYUP, WM_SYSKEYUP)
        kind = KeyEventKind.UP if is_up else KeyEventKind.DOWN

        def is_down(code: int) -> bool:
            return bool(user32.GetAsyncKeyState(code) & 0x8000)

        mod = WIN_VK_MODIFIERS.get(vk)
        if mod is not None:
            if is_up:
                self._mods.discard(mod)
            else:
                self._mods.add(mod)
            callback(RawKeyEvent(kind=kind, key="", modifiers=frozenset(self._mods), autorepeat=False))
            return

        autorepeat = False
        if is_up:
            self._down.discard(vk)
        else:
            # Повторный DOWN без UP — автоповтор, но только если система подтверждает,
            # что клавиша действительно удержана (иначе мы пропустили её отпускание).
            autorepeat = vk in self._down and is_down(vk)
            self._down.add(vk)
        # В момент вызова LL-хука системное состояние текущей клавиши ещё не обновлено,
        # а вот удержанные модификаторы уже отражены — сверяемся с ним.
        self._mods = set(modifiers_from_state(self._mods, is_down))
        key = WIN_VK_TO_NAME.get(vk, f"VK{vk}")
        callback(RawKeyEvent(kind=kind, key=key, modifiers=frozenset(self._mods), autorepeat=autorepeat))


def probe_hotkey_conflict(modifiers: frozenset[str], key: str) -> bool | None:
    """Проверить через RegisterHotKey, не занято ли сочетание другой программой.

    Находит только сочетания, зарегистрированные другими программами тем же
    способом; прочие конфликты Windows обнаружить не позволяет. True — занято,
    False — свободно (по данным RegisterHotKey), None — проверить не удалось.
    """
    vk = next((code for code, name in WIN_VK_TO_NAME.items() if name == key), None)
    if vk is None:
        return None
    flags = MOD_NOREPEAT
    flags |= MOD_CONTROL if "ctrl" in modifiers else 0
    flags |= MOD_ALT if "alt" in modifiers else 0
    flags |= MOD_SHIFT if "shift" in modifiers else 0
    flags |= MOD_WIN if "meta" in modifiers else 0
    user32, _ = _api()
    probe_id = 0x7A11
    if user32.RegisterHotKey(None, probe_id, flags, vk):
        user32.UnregisterHotKey(None, probe_id)
        return False
    return ctypes.get_last_error() == ERROR_HOTKEY_ALREADY_REGISTERED or None


# --- разрешения и сессия -----------------------------------------------------


def is_elevated() -> bool:
    try:
        return bool(ctypes.WinDLL("shell32").IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def check_permissions() -> PermissionInfo:
    return PermissionInfo(
        can_control_mouse=PermissionState.GRANTED,
        can_listen_input=PermissionState.GRANTED,
        details="",
    )


_timer_period_set = False


def _set_power_throttling(control_mask: int, state_mask: int) -> None:
    _, kernel32 = _api()
    fn = getattr(kernel32, "SetProcessInformation", None)
    if fn is None:
        return
    state = PROCESS_POWER_THROTTLING_STATE(1, control_mask, state_mask)  # Version = 1
    fn(kernel32.GetCurrentProcess(), 4, ctypes.byref(state), ctypes.sizeof(state))  # ProcessPowerThrottling


def begin_session() -> None:
    """На время работы (вызывается в рабочем потоке движка):
    • разрешение таймера 1 мс — иначе ожидания округляются до ~15,6 мс;
    • Windows 11: всегда соблюдать это разрешение и не замедлять процесс даже при
      свёрнутом окне (PROCESS_POWER_THROTTLING_*: ControlMask = флаг, StateMask = 0);
    • не уходить в сон по бездействию (SetThreadExecutionState для этого потока).
    """
    global _timer_period_set
    try:
        if ctypes.WinDLL("winmm").timeBeginPeriod(1) == 0:
            _timer_period_set = True
    except Exception:  # noqa: BLE001
        pass
    try:
        _set_power_throttling(0x1 | 0x4, 0)  # EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION → выкл.
    except Exception:  # noqa: BLE001
        pass
    try:
        _api()[1].SetThreadExecutionState(0x80000000 | 0x00000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except Exception:  # noqa: BLE001
        pass


def end_session() -> None:
    global _timer_period_set
    if _timer_period_set:
        try:
            ctypes.WinDLL("winmm").timeEndPeriod(1)
        except Exception:  # noqa: BLE001
            pass
        _timer_period_set = False
    try:
        _set_power_throttling(0, 0)  # вернуть управление системе
    except Exception:  # noqa: BLE001
        pass
    try:
        _api()[1].SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS — снять требование
    except Exception:  # noqa: BLE001
        pass
