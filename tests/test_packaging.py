"""The release tooling: installer script, build helpers and release notes."""

import hashlib
import importlib.util
import os
import re

import pytest
from PIL import Image

from bettervoice import __version__, autostart, brand
from conftest import ROOT


def load_script(name):
    path = os.path.join(ROOT, "scripts", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_script("build")
release_notes = load_script("release_notes")
with open(os.path.join(ROOT, "packaging", "bettervoice.iss"), encoding="utf-8") as f:
    ISS = f.read()


def size_of(path):
    with Image.open(path) as image:
        return image.size


def test_installer_matches_the_app():
    # Setup and Uninstall recognize the running app by its mutex...
    with open(os.path.join(ROOT, "src", "bettervoice", "desktop", "windows.py"),
              encoding="utf-8") as f:
        mutex = re.search(r'^MUTEX_NAMES = \("([^"]+)"', f.read(), re.M).group(1)
    assert re.search(r"^AppMutex=(.*)$", ISS, re.M).group(1) == mutex
    # ...and remove the autostart entry it writes, which they know as {#AppName}
    assert f"RunKey = '{autostart.RUN_KEY}';" in ISS
    assert autostart.VALUE_NAME == brand.NAME


@pytest.mark.parametrize("version, numbers", [
    ("0.1.0b1", (0, 1, 0, 0)),
    ("1.2.3", (1, 2, 3, 0)),
    ("1.2rc1", (1, 2, 0, 0)),
    ("2.0.10a3", (2, 0, 10, 0)),
])
def test_windows_version_numbers(monkeypatch, version, numbers):
    monkeypatch.setattr(build, "__version__", version)
    assert build.version_numbers() == numbers


def test_wizard_images_fit_every_display_scaling(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "WORK", str(tmp_path))
    large, small = (paths.split(",") for paths in build.wizard_images())
    assert [size_of(p) for p in large] == list(build.WIZARD_IMAGE_SIZES)
    assert [size_of(p) for p in small] == [(s, s) for s in build.WIZARD_SMALL_IMAGE_SIZES]
    with Image.open(large[0]) as image:
        page = tuple(int(brand.NEAR_BLACK[i:i + 2], 16) for i in (1, 3, 5))
        assert image.getpixel((0, 0)) == page  # blends into the page around it
        assert len(set(image.getdata())) > 2  # and shows the mark


def test_checksums_in_sha256sum_format(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "DIST", str(tmp_path))
    download = tmp_path / "BetterVoice-1.0.0-win-x64.zip"
    download.write_bytes(b"BetterVoice")
    with open(build.write_checksums([str(download)]), encoding="utf-8") as f:
        assert f.read() == (f"{hashlib.sha256(b'BetterVoice').hexdigest()}  "
                            "BetterVoice-1.0.0-win-x64.zip\n")


def test_the_current_version_has_a_changelog_entry():
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        assert release_notes.changelog_entry(__version__, f.read()), \
            f"add a '## {__version__}' section to CHANGELOG.md"


def test_release_notes(monkeypatch):
    changelog = ("# Changelog\n\n## 1.1.0 — 2026-10-01\n\n### Fixed\n\n- New.\n\n"
                 "## 1.0.0 — 2026-09-01\n\n- Old.\n")
    entry = release_notes.changelog_entry("1.1.0", changelog)
    assert entry == "### Fixed\n\n- New."
    assert release_notes.changelog_entry("1.0.0", changelog) == "- Old."
    assert release_notes.changelog_entry("1.0", changelog) is None

    text = release_notes.notes("1.1.0", entry)
    assert text.startswith(entry)
    # links to exactly the files the build makes, on each system
    base = f"{brand.REPO_URL}/releases/download/v1.1.0"
    monkeypatch.setattr(build, "__version__", "1.1.0")
    monkeypatch.setattr(build, "WINDOWS", True)
    names = [build.edition(cuda) + suffix for cuda in (False, True)
             for suffix in ("-setup.exe", ".zip")]
    monkeypatch.setattr(build, "WINDOWS", False)
    monkeypatch.setattr(build, "MACOS", True)
    for arch in ("arm64", "x64"):
        monkeypatch.setattr(build, "arch", lambda arch=arch: arch)
        names.append(build.edition() + ".dmg")
    monkeypatch.setattr(build, "MACOS", False)
    names.append(build.edition() + ".tar.gz")  # Linux, still x64
    for name in names + ["SHA256SUMS.txt"]:
        assert f"[{name}]({base}/{name})" in text, name
    assert text.count("](https://") == len(names) + 1
