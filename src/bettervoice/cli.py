"""The `bettervoice` command.

Commands for a running BetterVoice (--toggle, --cancel, --settings, --quit)
go out before the app itself is imported, so a desktop shortcut acts at once.
"""

import sys

COMMANDS = {"--toggle": "toggle", "--cancel": "cancel", "--settings": "settings",
            "--quit": "quit"}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    for flag, command in COMMANDS.items():
        if flag in args:
            from bettervoice import ipc

            if ipc.send(command) or command in ("cancel", "quit"):
                return
            break  # --toggle or --settings with nothing running: start BetterVoice
    from bettervoice.app import run

    run(args)
