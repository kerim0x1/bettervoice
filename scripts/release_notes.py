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

DOWNLOADS = (  # (file name suffix, who it is for)
    ("-setup.exe", "**Most PCs.** Installs {name} for your Windows account; no administrator "
                   "rights needed."),
    ("-cuda-setup.exe", "PCs with an NVIDIA graphics card: offline recognition runs on the GPU. "
                        "A larger download."),
    (".zip", "Use without installing: unzip, then start `{name}.exe`."),
    ("-cuda.zip", "The same, with GPU support for NVIDIA graphics cards."),
)


def changelog_entry(version, text):
    """The body of the `## <version>` section, or None."""
    match = re.search(rf"^## {re.escape(version)}(?: [^\n]*)?\n(.*?)(?=^## |\Z)", text,
                      re.M | re.S)
    return match.group(1).strip() if match else None


def notes(version, entry, dist=None):
    base = f"{brand.REPO_URL}/releases/download/v{version}"
    rows = []
    for suffix, purpose in DOWNLOADS:
        name = f"{brand.NAME}-{version}-win-x64{suffix}"
        path = os.path.join(dist, name) if dist else None
        size = f" ({os.path.getsize(path) / 1e6:.0f} MB)" if path and os.path.exists(path) else ""
        rows.append(f"| [{name}]({base}/{name}){size} | {purpose.format(name=brand.NAME)} |")
    return "\n".join([
        entry,
        "",
        "### Downloads",
        "",
        "| File | Choose it for |",
        "| --- | --- |",
        *rows,
        "",
        f"For Windows 10 and 11, 64-bit. {brand.NAME} is not code-signed yet: if SmartScreen "
        "warns about an unrecognized app, choose **More info → Run anyway**. "
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
