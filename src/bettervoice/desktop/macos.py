"""macOS: the hotkey through a Quartz event tap, Cmd+V into the focused app,
the text caret from the Accessibility API, and a menu bar icon.

The event tap and the key presses both need the Accessibility permission
(System Settings → Privacy & Security → Accessibility). BetterVoice asks for
it in the setup, and waits for it without a restart.
"""

import logging
import subprocess
import threading
import time

import AppKit
import Foundation
import pystray
import Quartz

from bettervoice import brand
from bettervoice.desktop.base import KeyFilter, PasteFallback
from bettervoice.desktop.posix import (  # noqa: F401 - part of this module's interface
    acquire_single_instance,
    tell_already_running,
)

log = logging.getLogger(__name__)

NAME = "macOS"
COMPUTER = "Mac"
HOTKEY = "⌃⌥O"
TRAY_ICON = "menu bar icon"
TRAY_PLACE = "the menu bar"
AUTOSTART_LABEL = "Open at login"
DISPLAY_FONT = TEXT_FONT = OVERLAY_FONT = ICON_FONT = None  # the system font
OVERLAY_FONT_SIZE = 12  # points are pixels on macOS: 9 would be tiny
OVERLAY_KEY_COLOR = "systemTransparent"

KEY_O, KEY_V, KEY_ESCAPE = 31, 9, 53  # virtual key codes (kVK_ANSI_O, ...)
MODIFIERS = (Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskAlternate
             | Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift)
HOTKEY_MODIFIERS = Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskAlternate
CLIPBOARD_RESTORE_DELAY = 1.0  # s; give the target app time to read the paste
ACCESSIBILITY_SETTINGS = ("x-apple.systempreferences:com.apple.preference.security"
                          "?Privacy_Accessibility")


# ------------------------------------------------------------------ access ---


def is_trusted():
    """Whether macOS lets BetterVoice watch and type keys (Accessibility)."""
    try:
        from ApplicationServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception:
        log.debug("could not check the Accessibility permission", exc_info=True)
        return True  # let the event tap tell


def missing_access():
    return [] if is_trusted() else ["accessibility"]


def self_check():
    """The Accessibility API is imported only when it's needed."""
    from ApplicationServices import AXIsProcessTrusted, AXUIElementCreateSystemWide  # noqa: F401


def request_access():
    """Show macOS's own prompt, and open the Accessibility settings."""
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    except Exception:
        log.debug("could not show the Accessibility prompt", exc_info=True)
    open_path(ACCESSIBILITY_SETTINGS)


# ---------------------------------------------------------------- process ---


def prepare_process():
    pass


def init_ui(root, on_reopen=None):
    """A menu bar app: no Dock icon (the packaged app says so in Info.plist)."""
    import tkinter as tk

    AppKit.NSApplication.sharedApplication().setActivationPolicy_(
        AppKit.NSApplicationActivationPolicyAccessory)
    root.iconphoto(True, tk.PhotoImage(master=root, file=brand.ICON_PNG_PATH))
    if on_reopen is not None:  # opened again, e.g. from the Applications folder
        root.createcommand("::tk::mac::ReopenApplication", on_reopen)


def set_window_icon(window):
    pass


def bring_to_front(window):
    """An app without a Dock icon has to activate itself for its windows to
    come forward and take keyboard input (e.g. to paste an API key)."""
    AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    window.lift()
    window.focus_force()


def open_path(path):
    subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ----------------------------------------------------------------- hotkey ---


class Hotkeys:
    """⌃⌥O and, during a dictation, Esc, from an event tap on its own run loop."""

    def __init__(self, on_hotkey, on_cancel, on_error):
        self.filter = KeyFilter(KEY_O, KEY_ESCAPE, on_hotkey, on_cancel)
        self.on_error = on_error
        self._tap = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def dictating(self, active):
        pass  # the tap asks on_cancel() on every Esc

    def _callback(self, proxy, event_type, event, refcon):
        if event_type in (Quartz.kCGEventTapDisabledByTimeout,
                          Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(self._tap, True)  # macOS switched it off: back on
            return event
        key = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        modifiers = Quartz.CGEventGetFlags(event) & MODIFIERS
        down = event_type == Quartz.kCGEventKeyDown
        if self.filter.feed(key, down, modifiers == HOTKEY_MODIFIERS):
            return None  # swallowed: the focused app never sees it
        return event

    def _run(self):
        mask = (Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
                | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp))
        told = False
        while True:  # without the permission there is no tap: wait for it
            self._tap = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionDefault, mask, self._callback, None)
            if self._tap:
                break
            if not told:
                log.warning("no Accessibility permission yet: waiting for it")
                self.on_error("Allow BetterVoice under Accessibility in System Settings")
                told = True
            time.sleep(2)
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), source,
                                  Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        log.info("ready: %s to dictate, Esc to cancel", HOTKEY)
        Quartz.CFRunLoopRun()


# ------------------------------------------------------------------ paste ---


def _restore_clipboard(text):
    board = AppKit.NSPasteboard.generalPasteboard()
    board.clearContents()
    board.setString_forType_(text, AppKit.NSPasteboardTypeString)


def paste(text):
    """Paste via the clipboard and ⌘V, then put the previous clipboard text back."""
    board = AppKit.NSPasteboard.generalPasteboard()
    previous = board.stringForType_(AppKit.NSPasteboardTypeString)
    board.clearContents()
    board.setString_forType_(text, AppKit.NSPasteboardTypeString)
    if not is_trusted():
        raise PasteFallback("Copied – press ⌘V to paste")
    # the user may still hold ⌃⌥ from the hotkey
    deadline = time.time() + 2
    while (Quartz.CGEventSourceFlagsState(Quartz.kCGEventSourceStateHIDSystemState)
           & MODIFIERS) and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.05)
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, KEY_V, down)
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(0.02)
    if previous:
        timer = threading.Timer(CLIPBOARD_RESTORE_DELAY, _restore_clipboard, (previous,))
        timer.daemon = True
        timer.start()


# ---------------------------------------------------------------- overlay ---

_front_app = None  # the app the user dictates into; it must keep the focus


def prepare_overlay(win):
    win.attributes("-transparent", True)
    win.config(bg=OVERLAY_KEY_COLOR)


def shape_overlay(win, width, height):
    pass  # the window is see-through around the pill


def _caret_position():
    """Below the text caret of the focused app, via the Accessibility API."""
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        AXUIElementCopyParameterizedAttributeValue,
        AXUIElementCreateSystemWide,
        AXUIElementSetMessagingTimeout,
        AXValueGetValue,
        kAXBoundsForRangeParameterizedAttribute,
        kAXFocusedUIElementAttribute,
        kAXSelectedTextRangeAttribute,
        kAXValueCGRectType,
    )

    system_wide = AXUIElementCreateSystemWide()
    AXUIElementSetMessagingTimeout(system_wide, 0.2)  # a hanging app mustn't hang us
    err, focused = AXUIElementCopyAttributeValue(system_wide, kAXFocusedUIElementAttribute, None)
    if err or focused is None:
        return None
    err, selection = AXUIElementCopyAttributeValue(focused, kAXSelectedTextRangeAttribute, None)
    if err or selection is None:
        return None
    err, bounds = AXUIElementCopyParameterizedAttributeValue(
        focused, kAXBoundsForRangeParameterizedAttribute, selection, None)
    if err or bounds is None:
        return None
    ok, rect = AXValueGetValue(bounds, kAXValueCGRectType, None)
    if not ok or rect.size.height <= 0:
        return None
    return int(rect.origin.x), int(rect.origin.y + rect.size.height) + 8


def overlay_anchor(root, width, height):
    """Below the text caret; next to the mouse pointer where there is none.
    Both come in the top-left based coordinates tk uses."""
    global _front_app
    _front_app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    try:
        caret = _caret_position()
    except Exception:
        log.debug("no caret position", exc_info=True)
        caret = None
    if caret is not None:
        return caret
    point = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return int(point.x) + 12, int(point.y) + 18


def overlay_shown(win):
    """Showing a window can activate BetterVoice: hand the focus back, so the
    text is pasted where the user was typing."""
    app = AppKit.NSApplication.sharedApplication()
    me = AppKit.NSRunningApplication.currentApplication()
    if app.isActive() and _front_app is not None and _front_app != me:
        _front_app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)


def clamp_to_work_area(root, x, y, w, h):
    """Inside the visible part (no menu bar, no Dock) of the screen at x, y.
    Cocoa counts from the bottom left of the main screen: flip it."""
    screens = AppKit.NSScreen.screens()
    height = screens[0].frame().size.height
    for screen in screens:
        visible = screen.visibleFrame()
        left, right = visible.origin.x, visible.origin.x + visible.size.width
        top = height - (visible.origin.y + visible.size.height)
        bottom = height - visible.origin.y
        if left <= x < right and top - 40 <= y < bottom + 40:
            break
    else:
        return x, y
    return (int(max(left + 4, min(x, right - w - 4))),
            int(max(top + 4, min(y, bottom - h - 4))))


# ------------------------------------------------------------------- tray ---


class MenuBarIcon(pystray.Icon):
    """The mark as a template image: macOS tints it for a light or dark menu
    bar, and it's drawn at twice the size for Retina screens."""

    def _assert_image(self):
        thickness = self._status_bar.thickness()
        if self._icon_image is not None:
            return
        size = int(thickness)
        png = brand.png_bytes(brand.draw_menu_bar_icon(size * 2))
        image = AppKit.NSImage.alloc().initWithData_(Foundation.NSData.dataWithBytes_length_(
            png, len(png)))
        image.setSize_((size, size))
        image.setTemplate_(True)
        self._icon_image = image
        self._status_item.button().setImage_(image)


def make_tray(name, title, menu):
    return MenuBarIcon(name, brand.draw_menu_bar_icon(44), title, menu)


def run_tray(icon):
    """AppKit runs on the main thread, driven by tk's event loop."""
    icon.run_detached(setup=lambda icon: None)
    icon.visible = True


def stop_tray(icon):
    icon.visible = False  # stop() would stop the event loop tk runs on
