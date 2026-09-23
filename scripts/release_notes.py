"""Write the notes of a GitHub release: the version's changelog entry and the downloads.

    python scripts/release_notes.py                        # the current version, to stdout
    python scripts/release_notes.py --out dist/release-notes.md

Fails when CHANGELOG.md has no entry for the version, so a release can't go
out without one.
"""

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from bettervoice import __version__, brand  # noqa: E402

DOWNLOADS = (  # (system, file name after "BetterVoice-<version>-", who it is for)
    ("Windows", "win-x64-setup.exe",
     "**Most PCs.** Installs {name} for your Windows account; no administrator rights needed."),
    ("Windows", "win-x64-cuda-setup.exe",
     "PCs with an NVIDIA graphics card: offline recognition runs on the GPU. A larger download."),
    ("Windows", "win-x64.zip", "Use without installing: unzip, then start `{name}.exe`."),
    ("Windows", "win-x64-cuda.zip", "The same, with GPU support for NVIDIA graphics cards."),
    ("macOS", "macos-arm64.dmg", "Macs with Apple silicon (M1 and newer)."),
    ("macOS", "macos-x64.dmg", "Macs with an Intel processor."),
    ("Linux", "linux-x64.tar.gz",
     "64-bit Linux with X11 or Wayland: unpack, then run `./install.sh` for the app menu."),
)


def changelog_entry(version, text):
    """The body of the `## <version>` section, or None."""
    match = re.search(rf"^## {re.escape(version)}(?: [^\n]*)?\n(.*?)(?=^## |\Z)", text,
                      re.M | re.S)
    return match.group(1).strip() if match else None


def notes(version, entry, dist=None):
    base = f"{brand.REPO_URL}/releases/download/v{version}"
    rows = []
    for system, suffix, purpose in DOWNLOADS:
        name = f"{brand.NAME}-{version}-{suffix}"
        path = os.path.join(dist, name) if dist else None
        size = f" ({os.path.getsize(path) / 1e6:.0f} MB)" if path and os.path.exists(path) else ""
        rows.append(f"| {system} | [{name}]({base}/{name}){size} | "
                    f"{purpose.format(name=brand.NAME)} |")
    return "\n".join([
        entry,
        "",
        "### Downloads",
        "",
        "| System | File | Choose it for |",
        "| --- | --- | --- |",
        *rows,
        "",
        f"Windows 10 and 11, macOS 12 and newer, and 64-bit Linux. {brand.NAME} is not "
        "code-signed yet: on Windows, if SmartScreen warns about an unrecognized app, choose "
        "**More info → Run anyway**; on macOS, open the app once with a right-click and "
        "**Open** (or allow it under **System Settings → Privacy & Security**). On Linux it "
        "needs PortAudio (`libportaudio2`). "
        f"[SHA256SUMS.txt]({base}/SHA256SUMS.txt) lists the checksum of every file.",
        "",
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--dist", default=os.path.join(ROOT, "dist"),
                        help="where the release files are, for their sizes")
    parser.add_argument("--out", help="write to this file instead of stdout")
    args = parser.parse_args()
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        entry = changelog_entry(args.version, f.read())
    if not entry:
        sys.exit(f"CHANGELOG.md has no entry for {args.version}: add a '## {args.version}' section")
    text = notes(args.version, entry, args.dist)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
