"""Windows: a low-level keyboard hook for Win+O, Ctrl+V into the focused app,
the text caret's position, the tray icon, and the single-instance mutex."""

import ctypes
import ctypes.wintypes as wt
import logging
import os
import threading
import time

import pyperclip
import pystray

from bettervoice import brand
from bettervoice.desktop.base import KeyFilter

log = logging.getLogger(__name__)

NAME = "Windows"
COMPUTER = "PC"
HOTKEY = "Win+O"
TRAY_ICON = "tray icon"
TRAY_PLACE = "the notification area of the taskbar"
AUTOSTART_LABEL = "Start with Windows"
DISPLAY_FONT = "Segoe UI Variable Display"
TEXT_FONT = "Segoe UI Variable Text"
OVERLAY_FONT = "Segoe UI"
OVERLAY_FONT_SIZE = 9
ICON_FONT = "Segoe Fluent Icons"

user32 = ctypes.windll.user32
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------------------------------------------------------- process ---


def prepare_process():
    """Physical pixels for the overlay's position, and our own taskbar
    identity (without it a source run shows Python's icon)."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            user32.SetProcessDpiAware()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(brand.APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def init_ui(root, on_reopen=None):
    root.iconbitmap(default=brand.ICON_PATH)  # every window gets the mark


def set_window_icon(window):
    window.iconbitmap(brand.ICON_PATH)


def bring_to_front(window):
    window.lift()


def open_path(path):
    os.startfile(path)


def missing_access():
    return []  # Windows asks for the microphone itself, on first use


def request_access():
    pass


def self_check():
    pass  # everything is imported already


# --------------------------------------------------------------- instance ---

ERROR_ALREADY_EXISTS = 183
MB_ICONINFORMATION = 0x40
kernel32.CreateMutexW.restype = ctypes.c_void_p
# the second name is the one used before the rename, so an old copy and
# BetterVoice never run (and grab Win+O) at the same time. The installer
# waits for the first one (packaging/bettervoice.iss).
MUTEX_NAMES = ("BetterVoice.SingleInstance", "DictationWinO_SingleInstance")
_mutex_handles = []  # held for the lifetime of the process


def acquire_single_instance():
    """False if BetterVoice, or its predecessor, is already running."""
    for name in MUTEX_NAMES:
        _mutex_handles.append(kernel32.CreateMutexW(None, False, name))
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return False
    return True


def tell_already_running():
    user32.MessageBoxW(
        None,
        f"{brand.NAME} is already running – its icon is in the notification area of the "
        "taskbar.\n\n"
        f"If the older version (BetterTalk) is running there, quit it from its icon "
        f"and start {brand.NAME} again.",
        brand.NAME,
        MB_ICONINFORMATION,
    )


# ------------------------------------------------------------------ paste ---

VK_LWIN, VK_RWIN, VK_CONTROL, VK_V = 0x5B, 0x5C, 0x11, 0x56
KEYEVENTF_KEYUP = 0x0002
CLIPBOARD_RESTORE_DELAY = 1.0  # s; give the target app time to read the paste


def win_is_down():
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (VK_LWIN, VK_RWIN))


def wait_for_win_release(timeout=2.0):
    """The user is likely still holding the Win key from the hotkey press."""
    deadline = time.time() + timeout
    while win_is_down() and time.time() < deadline:
        time.sleep(0.02)


def _restore_clipboard(text):
    try:
        pyperclip.copy(text)
    except Exception:
        pass


def paste(text):
    """Paste via clipboard + Ctrl+V, then put the previous clipboard text back.

    Only text can be restored: if the clipboard held something else (e.g. an
    image), the transcript simply stays on the clipboard.
    """
    try:
        previous = pyperclip.paste()
    except Exception:
        previous = ""
    pyperclip.copy(text)
    wait_for_win_release()
    time.sleep(0.05)
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    if previous:
        timer = threading.Timer(CLIPBOARD_RESTORE_DELAY, _restore_clipboard, (previous,))
        timer.daemon = True
        timer.start()


# ----------------------------------------------------------------- hotkey ---
# Win+O is already claimed by Windows itself (rotation lock), so RegisterHotKey
# fails with ERROR_HOTKEY_ALREADY_REGISTERED. Instead we install a low-level
# keyboard hook that intercepts the combo before Windows processes it. The
# hook also turns Esc into "cancel" while a dictation is running.

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
VK_O = 0x4F
VK_ESCAPE = 0x1B
VK_DUMMY = 0xFF  # tapped so the Win key release doesn't open the Start menu

LRESULT = ctypes.c_ssize_t
HookProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


def _tap_dummy_key():
    user32.keybd_event(VK_DUMMY, 0, 0, 0)
    user32.keybd_event(VK_DUMMY, 0, KEYEVENTF_KEYUP, 0)


class Hotkeys:
    """Win+O and, during a dictation, Esc, from a keyboard hook on its own thread."""

    def __init__(self, on_hotkey, on_cancel, on_error):
        self.filter = KeyFilter(VK_O, VK_ESCAPE, on_hotkey, on_cancel,
                                before_hotkey=_tap_dummy_key)
        self.on_error = on_error
        self._proc = HookProc(self._callback)  # referenced: the hook calls it

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def dictating(self, active):
        pass  # the hook asks on_cancel() on every Esc

    def _callback(self, n_code, w_param, l_param):
        if n_code == 0:
            vk = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents.vkCode
            down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
            if self.filter.feed(vk, down, vk == VK_O and win_is_down()):
                return 1  # swallowed: neither Windows nor the app sees the key
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _run(self):
        """Install the keyboard hook and pump messages for it (blocks)."""
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        if not hook:
            log.error("could not install keyboard hook")
            self.on_error("Hotkey unavailable")
            return
        log.info("ready: %s to dictate, Esc to cancel", HOTKEY)
        msg = wt.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass  # hook callbacks are delivered while GetMessageW pumps
        finally:
            user32.UnhookWindowsHookEx(hook)


# ---------------------------------------------------------------- overlay ---

OVERLAY_KEY_COLOR = "#ff00fe"  # everything this color is see-through
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080  # no taskbar button
WS_EX_NOACTIVATE = 0x08000000  # never becomes the foreground window
MONITOR_DEFAULTTONEAREST = 2


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("flags", wt.DWORD),
        ("hwndActive", wt.HWND),
        ("hwndFocus", wt.HWND),
        ("hwndCapture", wt.HWND),
        ("hwndMenuOwner", wt.HWND),
        ("hwndMoveSize", wt.HWND),
        ("hwndCaret", wt.HWND),
        ("rcCaret", wt.RECT),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", wt.RECT),
        ("rcWork", wt.RECT),
        ("dwFlags", wt.DWORD),
    ]


user32.MonitorFromPoint.argtypes = [POINT, wt.DWORD]
user32.MonitorFromPoint.restype = ctypes.c_void_p
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.c_void_p]


def prepare_overlay(win):
    """A window that never takes the focus and has no taskbar button, where
    OVERLAY_KEY_COLOR is see-through. Called while it's withdrawn."""
    win.config(bg=OVERLAY_KEY_COLOR)
    win.attributes("-transparentcolor", OVERLAY_KEY_COLOR)
    win.update_idletasks()
    hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)


def shape_overlay(win, width, height):
    pass  # the color key cuts out the pill's shape


def overlay_shown(win):
    pass


def overlay_anchor(root, width, height):
    """Screen position just below the text caret of the focused control.

    Falls back to the mouse position (usually where the user last clicked
    into the field) for apps that don't expose a caret, e.g. some browsers.
    """
    fg = user32.GetForegroundWindow()
    tid = user32.GetWindowThreadProcessId(fg, None)
    info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    if user32.GetGUIThreadInfo(tid, ctypes.byref(info)) and info.hwndCaret:
        pt = POINT(info.rcCaret.left, info.rcCaret.bottom)
        user32.ClientToScreen(info.hwndCaret, ctypes.byref(pt))
        return pt.x, pt.y + 10
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x + 12, pt.y + 18


def clamp_to_work_area(root, x, y, w, h):
    mon = user32.MonitorFromPoint(POINT(x, y), MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    wa = mi.rcWork
    return (
        max(wa.left + 4, min(x, wa.right - w - 4)),
        max(wa.top + 4, min(y, wa.bottom - h - 4)),
    )


# ------------------------------------------------------------------- tray ---

IMAGE_ICON, LR_LOADFROMFILE, SM_CXSMICON = 1, 0x10, 49
user32.LoadImageW.restype = ctypes.c_void_p
user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                              ctypes.c_int, ctypes.c_int, ctypes.c_uint]


class TrayIcon(pystray.Icon):
    """pystray loads the icon at the large-icon size and Windows shrinks it
    for the tray, which blurs the mark. Load the ICO's own small frame."""

    def _assert_icon_handle(self):
        if getattr(self, "_icon_handle", None):
            return
        size = user32.GetSystemMetrics(SM_CXSMICON)
        handle = user32.LoadImageW(None, brand.ICON_PATH, IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if handle:
            self._icon_handle = handle
        else:
            super()._assert_icon_handle()


def make_tray(name, title, menu):
    return TrayIcon(name, brand.draw_mark(64), title, menu)


def run_tray(icon):
    threading.Thread(target=icon.run, daemon=True).start()


def stop_tray(icon):
    icon.stop()
