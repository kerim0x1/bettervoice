#!/bin/sh
# Adds BetterVoice to your app menu, for your user, from wherever this folder is.
# Run it again after moving the folder; `./install.sh --uninstall` removes the entry.
# Your settings, keys and models stay in ~/.config/bettervoice and ~/.local/share/bettervoice.
set -e

here=$(cd "$(dirname "$0")" && pwd)
data="${XDG_DATA_HOME:-$HOME/.local/share}"
entry="$data/applications/bettervoice.desktop"
icon="$data/icons/hicolor/256x256/apps/bettervoice.png"

if [ "$1" = "--uninstall" ]; then
    rm -f "$entry" "$icon"
    echo "BetterVoice is no longer in your app menu."
    exit 0
fi

mkdir -p "$(dirname "$entry")" "$(dirname "$icon")"
cp "$here/_internal/bettervoice/assets/icon.png" "$icon"
cat > "$entry" <<EOF
[Desktop Entry]
Type=Application
Name=BetterVoice
Comment=Your voice, typed anywhere.
Exec="$here/bettervoice"
Icon=bettervoice
Terminal=false
Categories=Utility;Accessibility;
StartupWMClass=Bettervoice
EOF
if command -v update-desktop-database > /dev/null 2>&1; then
    update-desktop-database "$(dirname "$entry")" > /dev/null 2>&1 || true
fi
echo "BetterVoice is in your app menu now."

if ! ldconfig -p 2> /dev/null | grep -q "libportaudio\.so\.2"; then
    echo
    echo "BetterVoice records through PortAudio, which isn't installed yet:"
    echo "  Debian, Ubuntu:  sudo apt install libportaudio2"
    echo "  Fedora:          sudo dnf install portaudio"
    echo "  Arch:            sudo pacman -S portaudio"
fi
