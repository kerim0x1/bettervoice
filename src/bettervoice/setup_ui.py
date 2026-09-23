"""Setup wizard (first start) and settings window.

customtkinter on top of the app's hidden tk root, styled like the overlay:
near-black surfaces, warm off-white ink, Segoe UI Variable and Fluent icons.
Settings are saved as soon as they're valid; background work (key checks,
model list, GPU detection) reports back through a queue polled on the tk
thread, since tkinter must only be touched from there.
"""

import os
import queue
import sys
import threading
import webbrowser

import customtkinter as ctk

from bettervoice import __version__, autostart, brand, config, stt
from bettervoice.brand import draw_mark
from bettervoice.stt import local

# ---------------------------------------------------------------- design ---

BG = brand.NEAR_BLACK
SURFACE = "#141416"
SURFACE_HOVER = "#1a1a1e"
FIELD = "#1c1c1f"
SELECTED = "#3a3a40"
BORDER = "#26262a"
BORDER_HOVER = "#3d3d44"
TEXT = brand.WARM_WHITE
MUTED = "#8a8a86"
FAINT = "#5d5d5c"
ACCENT = brand.WARM_WHITE
ACCENT_HOVER = "#dddbd6"
ACCENT_TEXT = brand.NEAR_BLACK
SUCCESS = "#7bd88f"
ERROR = "#ff6b7a"
WARNING = "#f5c26b"

DISPLAY = "Segoe UI Variable Display"
BODY = "Segoe UI Variable Text"
ICON_FONT = "Segoe Fluent Icons"

ICONS = {
    config.LOCAL: "\ue7f4",
    config.DEEPGRAM: "\ue945",
    config.ELEVENLABS: "\ue9d9",
    config.OPENROUTER: "\uf4a5",
    "mic": "\ue720",
    "globe": "\ue774",
    "lock": "\ue72e",
    "check": "\ue73e",
    "cross": "\ue711",
    "warning": "\ue7ba",
    "download": "\ue896",
    "keyboard": "\ue765",
    "power": "\ue7e8",
    "pencil": "\ue70f",
    "link": "\ue8a7",
    "eye": "\ue890",
    "gear": "\ue713",
    "doc": "\ue7c3",
    "info": "\ue946",
    "clock": "\ue823",
    "back": "\ue72b",
    "next": "\ue72a",
}

ENGINE_CARDS = {
    config.LOCAL: ("Local", "Runs offline on your PC. Free and private.",
                   ("Offline", "Free")),
    config.DEEPGRAM: ("Deepgram", "Live in the cloud – your text is ready instantly.",
                      ("Live", "Very fast")),
    config.ELEVENLABS: ("ElevenLabs", "Scribe v2 – one of the most accurate recognizers.",
                        ("Very accurate", "90+ languages")),
    config.OPENROUTER: ("OpenRouter", "AI models like Gemini write along as you speak.",
                        ("AI", "Flexible")),
}

WIZARD_STEPS = ("welcome", "engine", "setup", "language", "done")
SETTINGS_PAGES = (
    ("engine", "Recognition", ICONS["mic"]),
    ("language", "Language", ICONS["globe"]),
    ("general", "General", ICONS["gear"]),
)

POLL_MS = 150


def _bind_tree(widget, sequence, callback):
    """Bind on a widget and all its descendants (customtkinter widgets are
    several tk widgets deep, and clicks land on the innermost one)."""
    widget.bind(sequence, callback, add="+")
    for child in widget.winfo_children():
        _bind_tree(child, sequence, callback)


def badge(master, ui, glyph, size, icon_size, fg, text_color, radius=None):
    """A fixed-size rounded square (or circle) with an icon centered in it."""
    frame = ctk.CTkFrame(master, width=size, height=size, fg_color=fg,
                         corner_radius=size // 2 if radius is None else radius)
    frame.pack_propagate(False)
    inner = int(size * 0.66)  # stays inside the rounding, even for a circle
    ctk.CTkLabel(frame, text=glyph, font=ui.icon(icon_size), text_color=text_color,
                 fg_color="transparent", width=inner, height=inner).place(
        relx=0.5, rely=0.5, anchor="center")
    return frame


def _pointer_inside(widget):
    x, y = widget.winfo_pointerxy()
    left, top = widget.winfo_rootx(), widget.winfo_rooty()
    return left <= x < left + widget.winfo_width() and top <= y < top + widget.winfo_height()


# ------------------------------------------------------------ components ---


class Card(ctk.CTkFrame):
    """A selectable engine card."""

    def __init__(self, master, ui, engine, command, text_width):
        super().__init__(master, fg_color=SURFACE, corner_radius=14, border_width=1,
                         border_color=BORDER, height=124)
        self.selected = False
        title, text, chips = ENGINE_CARDS[engine]
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)

        badge(self, ui, ICONS[engine], 40, 19, FIELD, TEXT, radius=10).grid(
            row=0, column=0, rowspan=2, padx=(16, 12), pady=(16, 0), sticky="n")
        ctk.CTkLabel(self, text=title, font=ui.font(15, "bold"), text_color=TEXT,
                     anchor="w").grid(row=0, column=1, sticky="w", pady=(14, 0))
        self.check = badge(self, ui, ICONS["check"], 24, 12, ACCENT, ACCENT_TEXT)
        self.check.grid(row=0, column=2, padx=14, pady=(14, 0), sticky="ne")
        self.check.grid_remove()
        ctk.CTkLabel(self, text=text, font=ui.font(12.5), text_color=MUTED, anchor="w",
                     justify="left", wraplength=text_width).grid(row=1, column=1, columnspan=2,
                                                                 sticky="w", padx=(0, 14))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=2, column=1, columnspan=2, sticky="w", pady=(6, 12))
        for chip in chips:
            ctk.CTkLabel(row, text=chip, font=ui.font(11.5), text_color=MUTED, fg_color=FIELD,
                         corner_radius=8, height=22).pack(side="left", padx=(0, 6), ipadx=6)

        _bind_tree(self, "<Button-1>", lambda e: command(engine))
        _bind_tree(self, "<Enter>", lambda e: self._hover(True))
        _bind_tree(self, "<Leave>", lambda e: self._hover(_pointer_inside(self)))

    def _hover(self, inside):
        if not self.selected:
            self.configure(border_color=BORDER_HOVER if inside else BORDER,
                           fg_color=SURFACE_HOVER if inside else SURFACE)

    def set_selected(self, selected):
        self.selected = selected
        self.configure(border_color=ACCENT if selected else BORDER,
                       border_width=2 if selected else 1,
                       fg_color=SURFACE_HOVER if selected else SURFACE)
        if selected:
            self.check.grid()
        else:
            self.check.grid_remove()


class StatusLine(ctk.CTkFrame):
    """Icon + text in one color: ok / error / warning / info / busy."""

    STYLES = {
        "ok": (ICONS["check"], SUCCESS),
        "error": (ICONS["cross"], ERROR),
        "warning": (ICONS["warning"], WARNING),
        "info": (ICONS["info"], MUTED),
        "busy": (ICONS["clock"], MUTED),
    }

    def __init__(self, master, ui):
        super().__init__(master, fg_color="transparent")
        self.icon = ctk.CTkLabel(self, text="", font=ui.icon(13), width=18)
        self.icon.pack(side="left", anchor="n", pady=(1, 0))
        self.text = ctk.CTkLabel(self, text="", font=ui.font(12.5), anchor="w",
                                 justify="left", wraplength=ui.text_width - 30)
        self.text.pack(side="left", fill="x", expand=True, padx=(6, 0))

    def set(self, kind, text):
        icon, color = self.STYLES[kind]
        self.icon.configure(text=icon, text_color=color)
        self.text.configure(text=text, text_color=color)


class KeyPanel(ctk.CTkFrame):
    """API key entry for one engine: paste, check, save."""

    def __init__(self, master, ui, engine, on_valid=None):
        super().__init__(master, fg_color="transparent")
        self.ui = ui
        self.engine = engine
        self.setting = config.key_setting(engine)
        self.on_valid = on_valid
        self.checked_key = None  # the key that was last confirmed valid

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text="API key", font=ui.font(13, "bold"),
                     text_color=TEXT).pack(side="left")
        link = ctk.CTkLabel(head, text=f"Get a {config.engine_label(engine)} key ↗",
                            font=ui.font(12.5), text_color=MUTED, cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: webbrowser.open(stt.KEY_URLS[engine]))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=(8, 6))
        self.entry = ctk.CTkEntry(row, show="•", height=42, corner_radius=10, border_width=1,
                                  fg_color=FIELD, border_color=BORDER, text_color=TEXT,
                                  placeholder_text="Paste your key here",
                                  placeholder_text_color=FAINT, font=ui.font(13))
        self.entry.pack(side="left", fill="x", expand=True)
        self.eye = ctk.CTkButton(row, text=ICONS["eye"], width=42, height=42, corner_radius=10,
                                 fg_color=FIELD, hover_color=SURFACE_HOVER, text_color=MUTED,
                                 font=ui.icon(15), command=self._toggle_visible)
        self.eye.pack(side="left", padx=(8, 0))
        self.button = ctk.CTkButton(row, text="Verify", width=96, height=42, corner_radius=10,
                                    fg_color=SELECTED, hover_color=BORDER_HOVER,
                                    text_color=TEXT, font=ui.font(13, "bold"),
                                    command=self.check)
        self.button.pack(side="left", padx=(8, 0))
        self.status = StatusLine(self, ui)
        self.status.pack(fill="x")

        saved = config.get(self.setting)
        if saved:
            self.entry.insert(0, saved)
            self.checked_key = saved
            self.status.set("ok", "Saved")
        else:
            self.status.set("info", "Stored only on this PC.")
        self.entry.bind("<Return>", lambda e: self.check())

    @property
    def key(self):
        return self.entry.get().strip()

    @property
    def is_valid(self):
        return bool(self.key) and self.key == self.checked_key

    def _toggle_visible(self):
        hidden = self.entry.cget("show") == "•"
        self.entry.configure(show="" if hidden else "•")
        self.eye.configure(text_color=TEXT if hidden else MUTED)

    def check(self, then=None):
        """Validate in the background; saves the key if it's (probably) good.
        then(ok) runs afterwards on the tk thread."""
        key = self.key
        if not key:
            self.status.set("error", "Paste a key first.")
            return
        self.button.configure(state="disabled", text="Checking…")
        self.status.set("busy", "Connecting to " + config.engine_label(self.engine) + "…")

        def done(result):
            if not self.winfo_exists():
                return
            self.button.configure(state="normal", text="Verify")
            if result is False:
                self.status.set("error", "This key was rejected.")
            else:
                config.set(self.setting, key)
                self.checked_key = key
                if result:
                    self.status.set("ok", "Key verified – saved")
                else:
                    self.status.set("warning", "Couldn't verify (no connection) – "
                                               "saved anyway.")
                if self.on_valid:
                    self.on_valid()
            if then:
                then(result is not False)

        self.ui.run_async(lambda: stt.check_key(self.engine, key), done)


class LocalPanel(ctk.CTkFrame):
    """Model choice, device info and download progress for local recognition."""

    CHOICES = {label: choice for choice, (label, _) in config.LOCAL_MODELS.items()}

    def __init__(self, master, ui, on_change=None):
        super().__init__(master, fg_color="transparent")
        self.ui = ui
        self.on_change = on_change
        self.gpu = None  # "ok" / "no_cublas" / "none", detected in the background
        self._downloaded = {}  # model name -> bool

        ctk.CTkLabel(self, text="Model", font=ui.font(13, "bold"),
                     text_color=TEXT).pack(anchor="w")
        current = config.LOCAL_MODELS[config.get("local_model")][0]
        self.choice = ctk.CTkSegmentedButton(
            self, values=list(self.CHOICES), height=38, corner_radius=10,
            fg_color=FIELD, selected_color=SELECTED, selected_hover_color=BORDER_HOVER,
            unselected_color=FIELD, unselected_hover_color=SURFACE_HOVER,
            text_color=TEXT, font=ui.font(12.5), command=self._choose)
        self.choice.set(current)
        self.choice.pack(fill="x", pady=(8, 6))
        self.about = ctk.CTkLabel(self, text="", font=ui.font(12.5), text_color=MUTED,
                                  anchor="w", justify="left", wraplength=ui.text_width)
        self.about.pack(fill="x", pady=(0, 12))
        self._describe(config.get("local_model"))

        self.device = StatusLine(self, ui)
        self.device.pack(fill="x")
        self.device.set("busy", "Checking the graphics card…")
        self.model = StatusLine(self, ui)
        self.model.pack(fill="x", pady=(2, 0))
        self.progress = ctk.CTkProgressBar(self, height=6, corner_radius=3, fg_color=FIELD,
                                           progress_color=ACCENT)
        self.progress.set(0)
        self.retry = ctk.CTkButton(self, text="Try again", width=150, height=34,
                                   corner_radius=10, fg_color=SELECTED, hover_color=BORDER_HOVER,
                                   text_color=TEXT, font=ui.font(12.5), command=self.start_download)

        ui.run_async(local.gpu_status, self._gpu_detected)

    @property
    def wanted(self):
        return local.resolve(config.get("local_model"), self.gpu == "ok")

    @property
    def downloaded(self):
        if self.gpu is None:
            return False
        name = self.wanted
        if name not in self._downloaded:
            self._downloaded[name] = local.model_path(name) is not None
        return self._downloaded[name]

    ABOUT = {
        config.LOCAL_AUTO: "Fits your hardware: large-v3-turbo with an NVIDIA GPU, "
                           "small otherwise.",
        "base": "base · 150 MB – very fast, a little less accurate.",
        "small": "small · 490 MB – a good balance, quick on a processor too.",
        "large-v3-turbo": "large-v3-turbo · 1.6 GB – the most accurate; needs a GPU.",
    }

    def _describe(self, choice):
        self.about.configure(text=self.ABOUT.get(choice, choice))

    def _choose(self, label):
        self._describe(self.CHOICES[label])
        config.set("local_model", self.CHOICES[label])
        if self.on_change:
            self.on_change()
        self.refresh()

    def _gpu_detected(self, status):
        if not self.winfo_exists():
            return  # the panel was replaced (another card was picked) meanwhile
        self.gpu = status = status or "none"  # None: the detection itself failed
        if status == "ok":
            self.device.set("ok", "NVIDIA GPU detected – recognition runs on the GPU.")
        elif status == "no_cublas" and getattr(sys, "frozen", False):
            self.device.set("warning", "NVIDIA GPU found, but this edition runs on the CPU – "
                                       "install the CUDA edition to use the GPU.")
        elif status == "no_cublas":
            self.device.set("warning", "NVIDIA GPU found, but cuBLAS is missing – running on "
                                       "the CPU (pip install nvidia-cublas-cu12).")
        else:
            self.device.set("info", "No NVIDIA GPU – recognition runs on the CPU.")
        self.refresh()

    def start_download(self):
        local.ENGINE.load(config.get("local_model"))
        self.refresh()

    def refresh(self):
        """Mirror the local engine's state (called periodically)."""
        if self.gpu is None or not self.winfo_exists():
            return
        engine = local.ENGINE
        name = self.wanted
        size = next((s for c, (_, s) in config.LOCAL_MODELS.items() if c == name), "")
        status = engine.status[:1].upper() + engine.status[1:]
        if engine.state == "downloading":
            self._downloaded.clear()
            self.model.set("busy", status)
            self.progress.set(engine.progress or 0)
            self.progress.pack(fill="x", pady=(8, 0))
            return
        self.progress.pack_forget()
        if engine.state == "error":
            self.model.set("error", f"{engine.error_message or 'Loading failed'}. "
                                    "Details are in the log.")
            self.retry.pack(anchor="w", pady=(10, 0))
            return
        self.retry.pack_forget()
        if engine.state == "loading":
            self.model.set("busy", status)
        elif engine.state == "ready":
            self.model.set("ok", status)
        elif self.downloaded:
            self.model.set("ok", f"{name} is downloaded.")
        else:
            self.model.set("info", f"{name} ({size}) is downloaded once.")


# ---------------------------------------------------------------- window ---


class SetupWindow(ctk.CTkToplevel):
    """wizard=True: first-start setup in steps; False: settings with a sidebar."""

    def __init__(self, master, wizard, page=None, on_change=None, on_close=None):
        ctk.set_appearance_mode("dark")
        super().__init__(master, fg_color=BG)
        self.wizard = wizard
        width, height = (840, 640) if wizard else (920, 660)
        self.text_width = width - 72 if wizard else width - 210 - 72
        # an engine card's text column: half the body minus icon, check, padding
        self.card_text_width = (self.text_width - 16) // 2 - 120
        self.on_change = on_change or (lambda: None)
        self.on_close = on_close
        self.engine = config.get("engine")  # the card selected in the UI
        self.page = None
        self.panel = None  # the KeyPanel / LocalPanel on screen, if any
        self.cards = {}
        self._results = queue.Queue()
        self._fonts = {}

        self.title(f"{brand.NAME} – {'Setup' if wizard else 'Settings'}")
        self.configure(fg_color=BG)
        self.resizable(False, False)
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 3
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.iconbitmap(brand.ICON_PATH)

        self.logo = ctk.CTkImage(draw_mark(160), size=(40, 40))
        self.autostart_on = ctk.BooleanVar(value=True if wizard else autostart.is_enabled())
        self._build_frame()
        self.show(page or ("welcome" if wizard else "engine"))
        self._poll()
        self.lift()
        self.attributes("-topmost", True)
        self.after(400, lambda: self.attributes("-topmost", False))
        self.focus_force()

    # -- helpers -------------------------------------------------------------

    def font(self, size, weight="normal", family=BODY):
        key = (size, weight, family)
        if key not in self._fonts:
            self._fonts[key] = ctk.CTkFont(family=family, size=round(size), weight=weight)
        return self._fonts[key]

    def icon(self, size):
        return self.font(size, family=ICON_FONT)

    def run_async(self, work, callback):
        """work() on a thread, then callback(result) on the tk thread."""

        def run():
            try:
                result = work()
            except Exception:
                result = None
            self._results.put((callback, result))

        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        if not self.winfo_exists():
            return  # closed: stop polling
        while True:
            try:
                callback, result = self._results.get_nowait()
            except queue.Empty:
                break
            callback(result)
        if isinstance(self.panel, LocalPanel):
            self.panel.refresh()
            if self.wizard and self.page == "setup" and self.panel.gpu is not None:
                needs_download = (local.ENGINE.state in ("off", "error")
                                  and not self.panel.downloaded)
                self.next_button.configure(
                    text="Download & continue" if needs_download else "Next")
        self.after(POLL_MS, self._poll)

    def iconbitmap(self, bitmap=None, default=None):
        # customtkinter puts its own logo into the title bar shortly after a
        # window opens (5.2 even when an icon is already set): keep ours
        if bitmap and "customtkinter" in os.path.basename(str(bitmap)).lower():
            return
        super().iconbitmap(bitmap, default)

    def _button(self, master, text, command, primary=True, width=140):
        if primary:
            return ctk.CTkButton(master, text=text, command=command, width=width, height=42,
                                 corner_radius=10, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                 text_color=ACCENT_TEXT, font=self.font(13.5, "bold"))
        return ctk.CTkButton(master, text=text, command=command, width=width, height=42,
                             corner_radius=10, fg_color="transparent", hover_color=SURFACE_HOVER,
                             text_color=MUTED, font=self.font(13.5))

    def _heading(self, title, subtitle=None):
        ctk.CTkLabel(self.body, text=title, font=self.font(24, "bold", DISPLAY),
                     text_color=TEXT, anchor="w").pack(fill="x")
        if subtitle:
            ctk.CTkLabel(self.body, text=subtitle, font=self.font(13.5), text_color=MUTED,
                         anchor="w", justify="left",
                         wraplength=self.text_width).pack(fill="x", pady=(4, 0))

    def _section(self, title):
        ctk.CTkLabel(self.body, text=title.upper(), font=self.font(11, "bold"),
                     text_color=FAINT, anchor="w").pack(fill="x", pady=(22, 8))

    def _switch_row(self, master, icon, title, text, variable, command):
        row = ctk.CTkFrame(master, fg_color=SURFACE, corner_radius=14, border_width=1,
                           border_color=BORDER)
        row.pack(fill="x", pady=(0, 10))
        row.grid_columnconfigure(1, weight=1)
        badge(row, self, icon, 38, 17, FIELD, TEXT, radius=10).grid(
            row=0, column=0, rowspan=2, padx=(14, 12), pady=14)
        ctk.CTkLabel(row, text=title, font=self.font(14, "bold"), text_color=TEXT,
                     anchor="w").grid(row=0, column=1, sticky="sw", pady=(12, 0))
        ctk.CTkLabel(row, text=text, font=self.font(12.5), text_color=MUTED, anchor="w",
                     justify="left", wraplength=self.text_width - 150).grid(
            row=1, column=1, sticky="nw", pady=(0, 12))
        ctk.CTkSwitch(row, text="", variable=variable, command=command, width=46,
                      switch_width=42, switch_height=22, fg_color=SELECTED,
                      progress_color=ACCENT, button_color=BG, button_hover_color=SURFACE,
                      ).grid(row=0, column=2, rowspan=2, padx=16)
        return row

    # -- frame: header/sidebar, body, footer ---------------------------------

    def _build_frame(self):
        if self.wizard:
            header = ctk.CTkFrame(self, fg_color="transparent", height=76)
            header.pack(fill="x", padx=36, pady=(22, 0))
            ctk.CTkLabel(header, image=self.logo, text="").pack(side="left")
            ctk.CTkLabel(header, text=brand.NAME, font=self.font(17, "bold", DISPLAY),
                         text_color=TEXT).pack(side="left", padx=12)
            self.dots = ctk.CTkFrame(header, fg_color="transparent")
            self.dots.pack(side="right")
            content = self
        else:
            sidebar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, width=210)
            sidebar.pack(side="left", fill="y")
            sidebar.pack_propagate(False)
            header = ctk.CTkFrame(sidebar, fg_color="transparent")
            header.pack(fill="x", padx=20, pady=(26, 26))
            ctk.CTkLabel(header, image=self.logo, text="").pack(side="left")
            ctk.CTkLabel(header, text=brand.NAME, font=self.font(16, "bold", DISPLAY),
                         text_color=TEXT).pack(side="left", padx=10)
            self.nav = {}
            for page, label, icon in SETTINGS_PAGES:
                button = ctk.CTkButton(
                    sidebar, text=f"{icon}   {label}", anchor="w", height=40, corner_radius=10,
                    fg_color="transparent", hover_color=SURFACE_HOVER, text_color=MUTED,
                    font=self.font(13.5), command=lambda p=page: self.show(p))
                button.pack(fill="x", padx=12, pady=2)
                self.nav[page] = button
            ctk.CTkLabel(sidebar, text=f"Version {__version__}", font=self.font(11.5),
                         text_color=FAINT, anchor="w").pack(side="bottom", fill="x", padx=24,
                                                           pady=(4, 22))
            ctk.CTkLabel(sidebar, text="Win+O  dictate\nEsc  cancel", font=self.font(12),
                         text_color=MUTED, justify="left", anchor="w").pack(
                side="bottom", fill="x", padx=24)
            content = ctk.CTkFrame(self, fg_color="transparent")
            content.pack(side="left", fill="both", expand=True)

        if self.wizard:  # settings are saved right away: no buttons needed there
            self.footer = ctk.CTkFrame(content, fg_color="transparent", height=76)
            self.footer.pack(side="bottom", fill="x", padx=36, pady=(0, 24))
        self.body = ctk.CTkFrame(content, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=36, pady=(24, 0))

    def show(self, page):
        """Switch to a page ("engine", "setup", "language", ...)."""
        if page is None:
            return
        self.page = page
        self.panel = None
        self.cards = {}
        footer = self.footer.winfo_children() if self.wizard else ()
        for widget in (*self.body.winfo_children(), *footer):
            widget.destroy()
        getattr(self, f"_page_{page}")()
        if self.wizard:
            self._draw_dots()
        else:
            for name, button in self.nav.items():
                active = name == page
                button.configure(fg_color=FIELD if active else "transparent",
                                 text_color=TEXT if active else MUTED)
        self.lift()

    def _draw_dots(self):
        for dot in self.dots.winfo_children():
            dot.destroy()
        step = WIZARD_STEPS.index(self.page)
        for i in range(len(WIZARD_STEPS)):
            ctk.CTkFrame(self.dots, width=22 if i == step else 8, height=8, corner_radius=4,
                         fg_color=ACCENT if i <= step else SELECTED).pack(side="left", padx=3)

    def _wizard_footer(self, next_text="Next", next_command=None, back=True):
        if back:
            self._button(self.footer, "Back", self._back, primary=False,
                         width=100).pack(side="left")
        self.next_button = self._button(self.footer, next_text, next_command or self._next,
                                        width=160)
        self.next_button.pack(side="right")

    def _next(self):
        steps = WIZARD_STEPS
        self.show(steps[steps.index(self.page) + 1])

    def _back(self):
        steps = WIZARD_STEPS
        self.show(steps[steps.index(self.page) - 1])

    # -- pages ---------------------------------------------------------------

    def _page_welcome(self):
        self._heading(f"Welcome to {brand.NAME}",
                      "Speak instead of typing – in any app, in 13 languages.")
        features = ctk.CTkFrame(self.body, fg_color="transparent")
        features.pack(fill="x", pady=(34, 0))
        for icon, title, text in (
            (ICONS["keyboard"], "Press Win+O and start talking",
             "Press Win+O again – your text appears where your cursor is. Esc cancels."),
            (ICONS["globe"], "Understands how you speak",
             "English, German, French and ten more languages – also detected automatically."),
            (ICONS["lock"], "Local or in the cloud",
             "Offline on your PC – or with Deepgram, ElevenLabs and OpenRouter."),
        ):
            row = ctk.CTkFrame(features, fg_color="transparent")
            row.pack(fill="x", pady=8)
            badge(row, self, icon, 42, 18, SURFACE, TEXT, radius=12).pack(side="left")
            texts = ctk.CTkFrame(row, fg_color="transparent")
            texts.pack(side="left", fill="x", expand=True, padx=16)
            ctk.CTkLabel(texts, text=title, font=self.font(14.5, "bold"), text_color=TEXT,
                         anchor="w").pack(fill="x")
            ctk.CTkLabel(texts, text=text, font=self.font(13), text_color=MUTED,
                         anchor="w").pack(fill="x")
        self._wizard_footer("Set up", back=False)

    def _page_engine(self):
        if self.wizard:
            self._heading(f"How should {brand.NAME} listen?",
                          "You can change this anytime from the tray icon.")
        else:
            self._heading("Recognition", "Choose what turns your speech into text.")
        grid = ctk.CTkFrame(self.body, fg_color="transparent")
        grid.pack(fill="x", pady=(22, 0))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="cards")
        for i, engine in enumerate(config.ENGINES):
            card = Card(grid, self, engine, self.select_engine, self.card_text_width)
            card.grid(row=i // 2, column=i % 2, sticky="ew",
                      padx=(0, 8) if i % 2 == 0 else (8, 0), pady=(0, 16))
            self.cards[engine] = card
        if self.wizard:
            self._wizard_footer()
        else:
            self.engine_panel = ctk.CTkFrame(self.body, fg_color="transparent")
            self.engine_panel.pack(fill="x", pady=(4, 0))
        self.select_engine(self.engine)

    def select_engine(self, engine):
        """A card was clicked (or the tray asked for an engine without a key)."""
        if self.page != "engine":
            self.show("engine")
        self.engine = engine
        for name, card in self.cards.items():
            card.set_selected(name == engine)
        if self.wizard:
            return
        # settings: switch right away if the engine is usable, else ask for its key
        for widget in self.engine_panel.winfo_children():
            widget.destroy()
        if config.has_key(engine):
            self._use_selected_engine()
        else:
            hint = StatusLine(self.engine_panel, self)
            hint.set("warning", f"{config.engine_label(config.get('engine'))} stays active "
                                "until a valid key is saved.")
            hint.pack(fill="x", pady=(0, 12))
        self._engine_setup(self.engine_panel, engine, self._on_key_saved)

    def _on_key_saved(self):
        self.select_engine(self.engine)  # redraw without the hint, and switch

    def _use_selected_engine(self):
        if config.get("engine") != self.engine:
            config.set("engine", self.engine)
            self.on_change()

    def _engine_setup(self, master, engine, on_valid):
        """The key panel (or the local model panel) for an engine."""
        if engine == config.LOCAL:
            self.panel = LocalPanel(master, self, on_change=None if self.wizard else self.on_change)
        else:
            self.panel = KeyPanel(master, self, engine, on_valid=on_valid)
        self.panel.pack(fill="x")
        if engine == config.OPENROUTER:
            self._openrouter_model(master)

    def _openrouter_model(self, master):
        box = ctk.CTkFrame(master, fg_color="transparent")
        box.pack(fill="x", pady=(14, 0))
        ctk.CTkLabel(box, text="Model", font=self.font(13, "bold"),
                     text_color=TEXT).pack(anchor="w")
        current = config.get("openrouter_model")
        combo = ctk.CTkComboBox(
            box, values=[current], height=40, corner_radius=10, border_width=1,
            fg_color=FIELD, border_color=BORDER, button_color=FIELD,
            button_hover_color=SURFACE_HOVER, dropdown_fg_color=SURFACE,
            dropdown_hover_color=SURFACE_HOVER, dropdown_text_color=TEXT, text_color=TEXT,
            font=self.font(13), dropdown_font=self.font(12.5),
            command=lambda value: config.set("openrouter_model", value.strip()))
        combo.set(current)
        combo.pack(fill="x", pady=(8, 4))
        combo.bind("<FocusOut>", lambda e: config.set("openrouter_model", combo.get().strip())
                   if combo.get().strip() else None)
        ctk.CTkLabel(box, text="Every model with audio input. Gemini Flash is fast and "
                               "inexpensive.", font=self.font(12.5), text_color=MUTED,
                     anchor="w").pack(fill="x")

        def loaded(models):
            if models and combo.winfo_exists():
                combo.configure(values=models)

        from bettervoice.stt.openrouter import audio_models

        self.run_async(audio_models, loaded)

    def _page_setup(self):  # wizard only
        engine = self.engine
        name = config.engine_label(engine)
        if engine == config.LOCAL:
            self._heading("Local model",
                          "Recognition runs entirely on your PC. The model is downloaded "
                          "once – after that, everything works offline.")
        else:
            self._heading(f"Connect {name}",
                          f"Paste your {name} API key. It stays on this PC.")
        box = ctk.CTkFrame(self.body, fg_color="transparent")
        box.pack(fill="x", pady=(26, 0))
        self._engine_setup(box, engine, on_valid=None)
        if engine == config.LOCAL:
            self._wizard_footer("Next", self._local_next)
        else:
            self._wizard_footer(next_command=self._key_next)

    def _key_next(self):
        panel = self.panel
        if panel.is_valid:
            self._next()
            return
        panel.check(then=lambda ok: ok and self.page == "setup" and self._next())

    def _local_next(self):
        if self.panel.gpu is None:
            return  # still detecting the GPU
        if local.ENGINE.state in ("off", "error") and not self.panel.downloaded:
            self.panel.start_download()  # keeps going in the background
        self._next()

    def _page_language(self):
        self._heading("Which language do you speak?" if self.wizard else "Language",
                      "Automatic detects the language for you. A fixed language is slightly "
                      "more accurate if you always speak the same one.")
        grid = ctk.CTkFrame(self.body, fg_color="transparent")
        grid.pack(fill="x", pady=(24, 0))
        grid.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="langs")
        self.language_buttons = {}
        for i, (code, label) in enumerate(config.LANGUAGES.items()):
            button = ctk.CTkButton(
                grid, text=label, height=44, corner_radius=10, border_width=1,
                font=self.font(13.5), command=lambda c=code: self._choose_language(c))
            button.grid(row=i // 4, column=i % 4, sticky="ew", padx=5, pady=5)
            self.language_buttons[code] = button
        self._choose_language(config.get("language"), save=False)
        if self.wizard:
            self._wizard_footer()

    def _choose_language(self, code, save=True):
        if save and code != config.get("language"):
            config.set("language", code)
            if not self.wizard:
                self.on_change()
        for c, button in self.language_buttons.items():
            selected = c == code
            button.configure(fg_color=ACCENT if selected else SURFACE,
                             hover_color=ACCENT_HOVER if selected else SURFACE_HOVER,
                             text_color=ACCENT_TEXT if selected else TEXT,
                             border_color=ACCENT if selected else BORDER)

    def _page_general(self):  # settings only
        self._heading("General")
        self._section("Extras")
        polish = ctk.BooleanVar(value=config.enabled("polish"))
        self.polish_var = polish
        self._switch_row(self.body, ICONS["pencil"], "AI Polish",
                         "Removes filler words like “um” and “uh” and small slips, and fixes "
                         "punctuation. "
                         "Uses a fast model via OpenRouter.",
                         polish, self._toggle_polish)
        self.polish_key = ctk.CTkFrame(self.body, fg_color="transparent", height=1)
        self.polish_key.pack(fill="x")
        self._switch_row(self.body, ICONS["power"], "Start with Windows",
                         f"{brand.NAME} starts in the background when you sign in.",
                         self.autostart_on, lambda: autostart.set_enabled(self.autostart_on.get()))
        self._section("Help")
        links = ctk.CTkFrame(self.body, fg_color="transparent")
        links.pack(fill="x")
        for text, action in (("Run setup again", self._restart_wizard),
                             ("Open log", lambda: os.startfile(config.LOG_PATH)),
                             ("Help & documentation ↗", lambda: webbrowser.open(brand.REPO_URL))):
            ctk.CTkButton(links, text=text, height=36, corner_radius=10, fg_color=SURFACE,
                          hover_color=SURFACE_HOVER, text_color=TEXT, border_width=1,
                          border_color=BORDER, font=self.font(13),
                          command=action).pack(side="left", padx=(0, 10))

    def _toggle_polish(self):
        on = self.polish_var.get()
        for widget in self.polish_key.winfo_children():
            widget.destroy()
        if on and not config.has_key(config.OPENROUTER):
            # needs an OpenRouter key first: ask for it right here
            self.polish_var.set(False)

            def valid():
                self.polish_var.set(True)
                config.set("polish", "1")
                self.on_change()

            KeyPanel(self.polish_key, self, config.OPENROUTER, on_valid=valid).pack(
                fill="x", pady=(0, 14))
            return
        config.set("polish", "1" if on else "0")
        self.on_change()

    def _restart_wizard(self):
        master, on_change = self.master, self.on_change
        self.close()
        SetupWindow(master, wizard=True, on_change=on_change)

    def _page_done(self):  # wizard only
        badge(self.body, self, ICONS["check"], 64, 26, ACCENT, ACCENT_TEXT).pack(
            anchor="w", pady=(8, 20))
        self._heading("You're all set",
                      f"{brand.NAME} runs in the background – you'll find its icon in the "
                      "notification area of the taskbar. From there you can change recognition "
                      "and language anytime.")
        how = ctk.CTkFrame(self.body, fg_color=SURFACE, corner_radius=14, border_width=1,
                           border_color=BORDER)
        how.pack(fill="x", pady=(26, 16))
        for i, (keys, text) in enumerate((("Win + O", "Start recording"),
                                          ("Win + O", "Stop – your text is pasted"),
                                          ("Esc", "Cancel"))):
            ctk.CTkLabel(how, text=keys, font=self.font(12.5, "bold"), text_color=TEXT,
                         fg_color=FIELD, corner_radius=8, width=76, height=30).grid(
                row=i, column=0, padx=(16, 14), pady=(14 if i == 0 else 6, 14 if i == 2 else 6))
            ctk.CTkLabel(how, text=text, font=self.font(13.5), text_color=MUTED,
                         anchor="w").grid(row=i, column=1, sticky="w")
        self._switch_row(self.body, ICONS["power"], "Start with Windows",
                         f"{brand.NAME} starts in the background when you sign in.",
                         self.autostart_on, None)
        self._wizard_footer("Get started", self._finish)

    def _finish(self):
        try:
            autostart.set_enabled(self.autostart_on.get())
        except OSError:
            pass
        config.set("engine", self.engine)
        config.set("setup_done", "1")
        self.on_change()
        self.close()

    def close(self):
        self.destroy()
        if self.on_close:
            self.on_close()
