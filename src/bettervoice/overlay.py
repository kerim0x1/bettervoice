"""Floating waveform pill shown near the text caret while dictating.

Frameless, always-on-top and never takes focus, so the paste lands in
the window the user was typing in. States: recording (bright bars + red
dot), processing (dimmed bars + grey dot), message (text, e.g. an error or
"the model is loading"; the pill widens to fit), hidden.
"""

import ctypes
import ctypes.wintypes as wt
import math
import tkinter as tk
import tkinter.font as tkfont

from bettervoice import brand

user32 = ctypes.windll.user32

# the brand's near-black tile and warm-white ink
PILL_W, PILL_H = 176, 40
MAX_W = 460  # messages wider than this are cut off
TEXT_PAD = 22
N_BARS = 26
TRANSPARENT = "#ff00fe"  # color key: everything this color is see-through
BG = brand.NEAR_BLACK
BG_ERROR = "#3a1418"
BG_INFO = "#1c1c1e"
BAR = brand.WARM_WHITE
BAR_DIM = "#5d5d5c"
DOT_REC = "#ff4d5e"
DOT_PROC = "#b1b1af"
TEXT = brand.WARM_WHITE

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


def enable_dpi_awareness():
    """Make screen coordinates physical pixels so the pill lands exactly."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            user32.SetProcessDpiAware()


def caret_screen_pos():
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


def clamp_to_work_area(x, y, w, h):
    mon = user32.MonitorFromPoint(POINT(x, y), MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    wa = mi.rcWork
    return (
        max(wa.left + 4, min(x, wa.right - w - 4)),
        max(wa.top + 4, min(y, wa.bottom - h - 4)),
    )


class Overlay:
    """All methods must be called from the tk main thread, except push_level.

    The canvas items are created once; each frame only moves and recolors
    them, and nothing is scheduled while the pill is hidden or shows text.
    """

    FRAME_MS = 40

    def __init__(self, root):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.config(bg=TRANSPARENT)
        self.win.attributes("-transparentcolor", TRANSPARENT)
        self.canvas = tk.Canvas(
            self.win, width=PILL_W, height=PILL_H, bg=TRANSPARENT, highlightthickness=0
        )
        self.canvas.pack()
        self.win.withdraw()
        self._make_no_activate()
        self.font = tkfont.Font(family="Segoe UI", size=9)
        self._create_items()

        self.state = "hidden"  # hidden | recording | processing | message
        self.width = PILL_W
        self.levels = [0.0] * N_BARS
        self._hide_job = None
        self._is_status = False  # the message shown is a status, not a flash
        self._frame_job = None
        self._tick = 0

    def _make_no_activate(self):
        self.win.update_idletasks()
        hwnd = user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)

    def _create_items(self):
        c = self.canvas
        self.pill = [
            c.create_oval(0, 0, 0, 0, fill=BG, outline=BG),
            c.create_oval(0, 0, 0, 0, fill=BG, outline=BG),
            c.create_rectangle(0, 0, 0, 0, fill=BG, outline=BG),
        ]
        self.dot = c.create_oval(0, 0, 0, 0, fill=DOT_REC, outline=DOT_REC)
        self.bars = [
            c.create_line(0, 0, 0, 0, fill=BAR, width=3, capstyle="round")
            for _ in range(N_BARS)
        ]
        self.text = c.create_text(0, PILL_H // 2, text="", fill=TEXT,
                                  font=self.font, state="hidden")
        self._resize(PILL_W)

    def _resize(self, width):
        self.width = width
        c, h, w = self.canvas, PILL_H, width
        c.config(width=w)
        c.coords(self.pill[0], 0, 0, h, h)
        c.coords(self.pill[1], w - h, 0, w, h)
        c.coords(self.pill[2], h // 2, 0, w - h // 2, h)
        c.coords(self.text, w // 2, h // 2)

    def _show_at_caret(self):
        x, y = caret_screen_pos()
        x, y = clamp_to_work_area(x, y, self.width, PILL_H)
        self.win.geometry(f"{self.width}x{PILL_H}+{x}+{y}")
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.win.lift()

    # -- state changes -------------------------------------------------------

    def show_recording(self):
        self._cancel_hide()
        self.levels = [0.0] * N_BARS
        self._resize(PILL_W)
        self._set_state("recording")
        self._show_at_caret()

    def set_processing(self):
        """Recording (or a status message) -> dimmed waveform while transcribing."""
        if self.state == "recording" or (self.state == "message" and self._is_status):
            self._cancel_hide()
            if self.width != PILL_W:
                self._resize(PILL_W)
                self.win.geometry(f"{PILL_W}x{PILL_H}")
            self._set_state("processing")

    def flash(self, message, kind="info", duration_ms=None):
        """Show a short message in place of the waveform, then hide."""
        self._show_message(message, BG_ERROR if kind == "error" else BG_INFO)
        self._is_status = False
        if duration_ms is None:
            duration_ms = 3000 if kind == "error" else 1800
        self._hide_job = self.root.after(duration_ms, self.hide)

    def status(self, message):
        """Show a progress message (e.g. while a model loads). It has to be
        refreshed: without an update for 2 s it hides itself."""
        self._show_message(message, BG)
        self._is_status = True
        self._hide_job = self.root.after(2000, self.hide)

    def hide(self):
        self._cancel_hide()
        self._set_state("hidden")
        self.win.withdraw()

    def _show_message(self, message, color):
        self._cancel_hide()
        width = min(MAX_W, max(PILL_W, self.font.measure(message) + 2 * TEXT_PAD))
        was_hidden = self.state == "hidden"
        self.canvas.itemconfigure(self.text, text=message)
        if width != self.width:
            self._resize(width)
            if not was_hidden:  # keep the left edge where it was
                self.win.geometry(f"{width}x{PILL_H}")
        self._set_state("message", color)
        if was_hidden:
            self._show_at_caret()

    def _cancel_hide(self):
        if self._hide_job is not None:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None

    def _set_state(self, state, pill_color=BG):
        self.state = state
        c = self.canvas
        for item in self.pill:
            c.itemconfigure(item, fill=pill_color, outline=pill_color)
        is_message = state == "message"
        c.itemconfigure(self.text, state="normal" if is_message else "hidden")
        wave = "hidden" if is_message else "normal"
        dot = DOT_REC if state == "recording" else DOT_PROC
        c.itemconfigure(self.dot, state=wave, fill=dot, outline=dot)
        bar_color = BAR if state == "recording" else BAR_DIM
        for bar in self.bars:
            c.itemconfigure(bar, state=wave, fill=bar_color)
        animate = state in ("recording", "processing")
        if animate and self._frame_job is None:
            self._frame()
        elif not animate and self._frame_job is not None:
            self.root.after_cancel(self._frame_job)
            self._frame_job = None

    # -- audio level input (called from the audio thread) --------------------

    def push_level(self, level):
        # swap in a new list instead of mutating: _frame may be iterating
        self.levels = self.levels[1:] + [min(1.0, max(0.0, level))]

    # -- drawing -------------------------------------------------------------

    def _frame(self):
        self._tick += 1
        c = self.canvas

        # status dot, gently pulsing
        r = 4 * (1.0 + 0.35 * math.sin(self._tick * 0.35))
        c.coords(self.dot, 17 - r, PILL_H / 2 - r, 17 + r, PILL_H / 2 + r)

        # scrolling waveform, newest sample on the right
        x0, x1 = 34, PILL_W - 14
        step = (x1 - x0) / N_BARS
        cy = PILL_H / 2
        max_h = PILL_H - 16
        for i, (bar, lv) in enumerate(zip(self.bars, self.levels, strict=True)):
            x = x0 + i * step
            h = 3 + lv * max_h
            c.coords(bar, x, cy - h / 2, x, cy + h / 2)

        self._frame_job = self.root.after(self.FRAME_MS, self._frame)
