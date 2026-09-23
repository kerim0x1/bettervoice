"""What the system backends share: the key filter and the way to the UI thread."""

import threading


class PasteFallback(Exception):  # noqa: N818 - not an error: the text is waiting
    """The text couldn't be typed into the focused app; it's on the clipboard,
    and the message tells the user how to paste it."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class KeyFilter:
    """Decides which key events belong to BetterVoice.

    The backends feed it every key press and release. It claims the hotkey
    (autorepeat triggers it only once) and Esc while a dictation runs, plus
    the matching releases; feed() returns True for events to swallow.
    """

    def __init__(self, hotkey_key, escape_key, on_hotkey, on_cancel, before_hotkey=None):
        self.hotkey_key = hotkey_key
        self.escape_key = escape_key
        self.on_hotkey = on_hotkey
        self.on_cancel = on_cancel  # returns True if a dictation was cancelled
        self.before_hotkey = before_hotkey
        self.swallowed = set()  # keys whose release is ours too

    def feed(self, key, down, modifiers_held):
        """modifiers_held: the hotkey's modifiers, and only those, are down."""
        if key == self.hotkey_key and down and modifiers_held:
            if key not in self.swallowed:  # not the key's autorepeat
                self.swallowed.add(key)
                if self.before_hotkey:
                    self.before_hotkey()
                self.on_hotkey()
            return True
        if key == self.escape_key and down and (key in self.swallowed or self.on_cancel()):
            self.swallowed.add(key)
            return True  # the Esc belonged to us, not to the focused app
        if not down and key in self.swallowed:
            self.swallowed.discard(key)
            return True
        return False


class Ui:
    """How system code reaches the tk main thread, which app.main() sets up.

    call(fn) runs fn there and returns its result; from the main thread
    itself it just calls fn.
    """

    def __init__(self):
        self.root = None
        self._post = None

    def attach(self, root, post):
        """post(fn) queues fn for the tk thread (app.py's event queue)."""
        self.root, self._post = root, post

    def call(self, fn, timeout=5.0):
        if self._post is None or threading.current_thread() is threading.main_thread():
            return fn()
        done, box = threading.Event(), {}

        def run():
            try:
                box["result"] = fn()
            except BaseException as e:  # handed to the calling thread
                box["error"] = e
            finally:
                done.set()

        self._post(run)
        if not done.wait(timeout):
            raise TimeoutError("the UI thread did not respond")
        if "error" in box:
            raise box["error"]
        return box.get("result")


ui = Ui()
