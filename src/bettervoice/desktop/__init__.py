"""Everything that differs between Windows, macOS and Linux, behind one interface.

`system` is the module for the system BetterVoice runs on. Each one provides:

    names:     NAME, COMPUTER, HOTKEY, TRAY_ICON, TRAY_PLACE, AUTOSTART_LABEL
    fonts:     DISPLAY_FONT, TEXT_FONT, OVERLAY_FONT, ICON_FONT (None: the default)
    process:   prepare_process(), init_ui(root), set_window_icon(window),
               bring_to_front(window), open_path(path)
    instance:  acquire_single_instance() -> bool, tell_already_running()
    hotkey:    Hotkeys(on_hotkey, on_cancel, on_error) with start(), dictating(active)
    paste:     paste(text), may raise PasteFallback
    overlay:   prepare_overlay(win) -> color key or None, shape_overlay(win, w, h),
               overlay_anchor(root) -> (x, y), clamp_to_work_area(root, x, y, w, h),
               overlay_shown(win)
    tray:      make_tray(name, title, menu) -> pystray icon, run_tray(icon)
    access:    missing_access() -> list of what the user must still allow,
               request_access()

Code that must run on the tk thread reaches it through `ui` (see base.Ui).
"""

import sys

from bettervoice.desktop.base import PasteFallback, ui

if sys.platform == "win32":
    from bettervoice.desktop import windows as system
elif sys.platform == "darwin":
    from bettervoice.desktop import macos as system
else:
    from bettervoice.desktop import linux as system

__all__ = ["PasteFallback", "system", "ui"]
