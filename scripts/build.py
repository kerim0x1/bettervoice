"""Build the Windows app, its archives and its installers.

    python scripts/build.py              # dist/BetterVoice/ + BetterVoice-<version>-win-x64.zip
    python scripts/build.py --installer  # also BetterVoice-<version>-win-x64-setup.exe
    python scripts/build.py --with-cuda  # the CUDA edition: cuBLAS for NVIDIA GPUs (~700 MB more)
    python scripts/build.py --release    # everything a GitHub release publishes: both
                                         # editions as zip and installer, and SHA256SUMS.txt

Needs `pip install -e ".[build]"` (and `.[gpu]` for the CUDA edition) in a
clean virtual environment: PyInstaller bundles whatever else is installed next
to it. The installers need Inno Setup 6.7 or newer (https://jrsoftware.org/isinfo.php).
"""

import argparse
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from bettervoice import __version__, brand  # noqa: E402

DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")
APP = os.path.join(DIST, brand.NAME)
INSTALLER_SCRIPT = os.path.join(ROOT, "packaging", "bettervoice.iss")

# Inno Setup's image areas at 100-250 % display scaling; Setup picks the closest
WIZARD_IMAGE_SIZES = ((202, 386), (269, 515), (336, 643), (403, 772), (430, 824), (498, 953),
                      (534, 1022))
WIZARD_SMALL_IMAGE_SIZES = (58, 77, 97, 116, 124, 143, 159)

VERSION_INFO = """\
VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{author}'),
      StringStruct('FileDescription', '{name}'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 {name} contributors. MIT License.'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', '{name}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def version_numbers():
    """0.1.0b1 -> (0, 1, 0, 0): the numeric form Windows version resources need."""
    major, minor, patch = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", __version__).groups("0")
    return int(major), int(minor), int(patch), 0


def version_file():
    """The exe's version resource: what Explorer, Task Manager and the
    Startup apps list show as name, publisher and version."""
    path = os.path.join(WORK, "version_info.txt")
    os.makedirs(WORK, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(VERSION_INFO.format(numbers=version_numbers(), author=brand.AUTHOR,
                                    name=brand.NAME, version=__version__))
    return path


def pyinstaller():
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onedir",  # a one-file exe would unpack ~250 MB on every start
        "--windowed",
        "--name", brand.NAME,
        "--icon", brand.ICON_PATH,
        "--version-file", version_file(),
        "--paths", os.path.join(ROOT, "src"),
        "--collect-data", "bettervoice",
        "--collect-data", "faster_whisper",  # the Silero VAD model
        "--collect-data", "customtkinter",
        # never used by BetterVoice (see bettervoice/stt/__init__.py)
        "--exclude-module", "av",
        "--exclude-module", "hf_xet",
        "--exclude-module", "torch",
        "--exclude-module", "transformers",
        "--distpath", DIST, "--workpath", WORK, "--specpath", WORK,
        os.path.join(ROOT, "src", "bettervoice", "__main__.py"),
    ], check=True)


def bundle_cuda():
    """Copy cuBLAS from the nvidia-cublas-cu12 package next to the exe."""
    import nvidia.cublas  # pip install -e ".[gpu]"

    source = os.path.join(list(nvidia.cublas.__path__)[0], "bin")
    target = os.path.join(APP, "cuda")
    os.makedirs(target, exist_ok=True)
    for dll in glob.glob(os.path.join(source, "cublas*64_12.dll")):
        shutil.copy2(dll, target)
        print("bundled", os.path.basename(dll))


def add_notices():
    """The license texts travel with every copy of the app."""
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(os.path.join(ROOT, name), os.path.join(APP, name))


def edition(with_cuda):
    return f"{brand.NAME}-{__version__}-win-x64" + ("-cuda" if with_cuda else "")


def archive(with_cuda):
    return shutil.make_archive(os.path.join(DIST, edition(with_cuda)), "zip", DIST, brand.NAME)


def find_iscc():
    """Inno Setup's command-line compiler: $ISCC, on PATH, or installed."""
    candidates = [os.environ.get("ISCC"), shutil.which("ISCC")] + [
        os.path.join(os.environ.get(base, ""), *folder, "Inno Setup 6", "ISCC.exe")
        for base, folder in (("ProgramFiles(x86)", ()), ("ProgramFiles", ()),
                             ("LOCALAPPDATA", ("Programs",)))
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    sys.exit("Inno Setup not found: install Inno Setup 6.7 or newer, or point ISCC at ISCC.exe")


def wizard_images():
    """The installer's images, rendered from the mark for every display scaling.

    Opaque near black like the pages around them, so no fill color shows at
    the edges.
    """
    folder = os.path.join(WORK, "installer")
    os.makedirs(folder, exist_ok=True)
    large, small = [], []
    for width, height in WIZARD_IMAGE_SIZES:
        image = Image.new("RGB", (width, height), brand.NEAR_BLACK)
        mark = brand.draw_mark(round(width * 0.5))
        image.paste(mark, ((width - mark.width) // 2, (height - mark.height) // 2), mark)
        large.append(os.path.join(folder, f"wizard-{width}x{height}.png"))
        image.save(large[-1], optimize=True)
    for size in WIZARD_SMALL_IMAGE_SIZES:
        image = Image.new("RGB", (size, size), brand.NEAR_BLACK)
        mark = brand.draw_mark(size)
        image.paste(mark, (0, 0), mark)
        small.append(os.path.join(folder, f"wizard-small-{size}.png"))
        image.save(small[-1], optimize=True)
    return ",".join(large), ",".join(small)


def installer(with_cuda):
    """Compile packaging/bettervoice.iss for the app in dist/BetterVoice."""
    images, small_images = wizard_images()
    defines = {
        "AppName": brand.NAME,
        "AppVersion": __version__,
        "FileVersion": ".".join(map(str, version_numbers())),
        "AppPublisher": brand.AUTHOR,
        "AppURL": brand.REPO_URL,
        "AppTagline": brand.TAGLINE,
        "AppUserModelID": brand.APP_USER_MODEL_ID,
        "AppDir": APP,
        "IconFile": brand.ICON_PATH,
        "BackColor": brand.NEAR_BLACK,
        "WizardImages": images,
        "WizardSmallImages": small_images,
        "OutputDir": DIST,
        "OutputName": edition(with_cuda) + "-setup",
    }
    subprocess.run([find_iscc(), "/Qp"] + [f"/D{name}={value}" for name, value in defines.items()]
                   + [INSTALLER_SCRIPT], check=True)
    return os.path.join(DIST, defines["OutputName"] + ".exe")


def write_checksums(paths):
    """SHA256SUMS.txt in the format of sha256sum, so `sha256sum -c` can check it."""
    lines = []
    for path in paths:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                digest.update(block)
        lines.append(f"{digest.hexdigest()}  {os.path.basename(path)}\n")
    target = os.path.join(DIST, "SHA256SUMS.txt")
    with open(target, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-cuda", action="store_true",
                        help="the CUDA edition: bundle cuBLAS for NVIDIA GPUs")
    parser.add_argument("--installer", action="store_true", help="also build the installer")
    parser.add_argument("--release", action="store_true",
                        help="both editions as zip and installer, with checksums")
    parser.add_argument("--no-zip", action="store_true", help="skip the zip archive")
    args = parser.parse_args()
    if args.release or args.installer:
        find_iscc()  # fail now, not after the PyInstaller build
    pyinstaller()
    add_notices()
    outputs = []
    for with_cuda in (False, True) if args.release else (args.with_cuda,):
        if with_cuda:
            bundle_cuda()
        if args.release or not args.no_zip:
            outputs.append(archive(with_cuda))
        if args.release or args.installer:
            outputs.append(installer(with_cuda))
    if args.release:
        outputs.append(write_checksums(outputs))
    print(f"app: {os.path.relpath(os.path.join(APP, brand.NAME + '.exe'), ROOT)}")
    for path in outputs:
        print(f"{os.path.relpath(path, ROOT)} ({os.path.getsize(path) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
